from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from queue import Empty, Full, LifoQueue
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet

from .storage_paths import paths

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT, DATA, UPLOADS = paths()
DATA.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)
UPLOADS.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "earthai.db"
_CONNECTIONS = {}
_CONNECTION_LOCK = threading.Lock()
_CONNECTION_LOCAL = threading.local()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid4())


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value else default


def journal_mode():
    mode = os.getenv("EARTHAI_SQLITE_JOURNAL_MODE", "WAL").strip().upper()
    if mode not in {"WAL", "DELETE"}:
        raise ValueError("EARTHAI_SQLITE_JOURNAL_MODE 只允许 WAL 或 DELETE，不能关闭数据库事务日志。")
    return mode


@contextmanager
def connect():
    key = (os.getpid(), str(DB_PATH), journal_mode())
    with _CONNECTION_LOCK:
        pool = _CONNECTIONS.setdefault(key, LifoQueue(maxsize=8))
    try:
        conn = pool.get_nowait()
    except Empty:
        conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA synchronous=FULL")
    previous = getattr(_CONNECTION_LOCAL, "current", None)
    _CONNECTION_LOCAL.current = conn
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        _CONNECTION_LOCAL.current = previous
        if conn.in_transaction:
            conn.rollback()
        conn.set_authorizer(None)
        conn.set_trace_callback(None)
        try:
            pool.put_nowait(conn)
        except Full:
            conn.close()


def close_connections():
    with _CONNECTION_LOCK:
        pools = list(_CONNECTIONS.values())
        _CONNECTIONS.clear()
    for pool in pools:
        while True:
            try:
                pool.get_nowait().close()
            except Empty:
                break


def current_connection():
    return getattr(_CONNECTION_LOCAL, "current", None)


def init_db():
    if os.getenv("EARTHAI_STATE_DIR") and DATA != DATA_ROOT and (DATA_ROOT / "earthai.db").is_file() and not DB_PATH.is_file():
        raise RuntimeError("检测到原数据目录数据库，但新的 EARTHAI_STATE_DIR 尚未迁移。请停机备份并迁移数据库和原 master.key 后再启动，不能用空库覆盖原账号。")
    if os.getenv("EARTHAI_STATE_DIR") and DB_PATH.is_file() and not os.getenv("EARTHAI_MASTER_KEY") and not (DATA / "master.key").is_file() and DATA != DATA_ROOT and (DATA_ROOT / "master.key").is_file():
        raise RuntimeError("本地数据库缺少原 master.key，请完成主密钥迁移，不能生成新密钥替代。")
    mode = journal_mode()
    with connect() as db:
        configured = db.execute(f"PRAGMA journal_mode={mode}").fetchone()[0].upper()
        if configured != mode:
            raise RuntimeError(f"数据库未能切换到 {mode} 日志模式，请停止其他使用同一数据目录的实例后重试。")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            data TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entities_owner_kind ON entities(owner,kind,updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,created_at);
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
            status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_owner ON runs(owner,created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_single_active_run ON runs(conversation_id)
            WHERE status IN ('queued','running','waiting_approval');
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            type TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id,id);
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL,
            tool_name TEXT NOT NULL, arguments TEXT NOT NULL, risk TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, knowledge_id TEXT NOT NULL,
            name TEXT NOT NULL, size INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_documents_owner_knowledge ON documents(owner,knowledge_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_documents_knowledge ON documents(knowledge_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            id UNINDEXED, owner UNINDEXED, knowledge_id UNINDEXED,
            document_id UNINDEXED, document_name UNINDEXED, content, tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS audit (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, action TEXT NOT NULL,
            resource TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_orders (
            owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            ids TEXT NOT NULL
        );
        """)
    from . import teams
    teams.initialize()
    os.chmod(DB_PATH, 0o600)


def cipher() -> Fernet:
    return _cipher(os.getenv("EARTHAI_MASTER_KEY"), str(DATA))


@lru_cache(maxsize=4)
def _cipher(key, directory) -> Fernet:
    if not key:
        path = Path(directory) / "master.key"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            with os.fdopen(fd, "w") as out:
                out.write(key)
    return Fernet(key.encode())


def seal(value: str) -> str:
    return cipher().encrypt(value.encode()).decode() if value else ""


def unseal(value: str) -> str:
    return cipher().decrypt(value.encode()).decode() if value else ""


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.b64encode(salt + key).decode()


def password_matches(password: str, encoded: str) -> bool:
    raw = base64.b64decode(encoded)
    key = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
    return hmac.compare_digest(raw[16:], key)


def new_session(user_id: str) -> str:
    token = secrets.token_urlsafe(40)
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
        db.execute("INSERT INTO sessions VALUES (?,?,?)", (
            hashlib.sha256(token.encode()).hexdigest(), user_id,
            (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        ))
    return token


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as db:
        row = db.execute("""SELECT users.* FROM users JOIN sessions ON users.id=sessions.user_id
            WHERE sessions.token=? AND sessions.expires_at>?""", (
            hashlib.sha256(token.encode()).hexdigest(), now(),
        )).fetchone()
    return {"id": row["id"], "email": row["email"], **loads(row["data"])} if row else None


def entity(row) -> dict | None:
    if row is None:
        return None
    return {**loads(row["data"], {}), "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def get_entity(owner: str, kind: str, id_: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM entities WHERE id=? AND owner=? AND kind=?", (id_, owner, kind)).fetchone()
    return entity(row)


def list_entities(owner: str, kind: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM entities WHERE owner=? AND kind=? ORDER BY updated_at DESC", (owner, kind)).fetchall()
    values = [entity(row) for row in rows]
    if kind == "agents":
        values.sort(key=lambda item: (item.get("sort_order") if type(item.get("sort_order")) is int and item["sort_order"] >= 0 else float("inf"), item["created_at"], item["id"]))
        with connect() as db:
            order = db.execute("SELECT ids FROM agent_orders WHERE owner=?", (owner,)).fetchone()
        if order:
            positions = {id_: index for index, id_ in enumerate(loads(order["ids"], []))}
            values.sort(key=lambda item: positions.get(item["id"], len(positions)))
    return values


def save_entity(owner: str, kind: str, data: dict, id_: str | None = None) -> dict:
    timestamp = now()
    if id_ is None:
        id_ = uid()
        with connect() as db:
            db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (id_, owner, kind, dumps(data), timestamp, timestamp))
    else:
        with connect() as db:
            db.execute("UPDATE entities SET data=?,updated_at=? WHERE id=? AND owner=? AND kind=?", (dumps(data), timestamp, id_, owner, kind))
    return get_entity(owner, kind, id_)


def delete_entity(owner: str, kind: str, id_: str):
    with connect() as db:
        db.execute("DELETE FROM entities WHERE owner=? AND kind=? AND id=?", (owner, kind, id_))


def audit(owner: str, action: str, resource: str, detail: str = ""):
    with connect() as db:
        db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?)", (uid(), owner, action, resource, detail[:2000], now()))


def add_message(owner: str, conversation_id: str, role: str, content: str, run_id: str | None = None):
    id_ = uid()
    with connect() as db:
        db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (id_, owner, conversation_id, role, content, run_id, now()))
    return id_


def list_messages(owner: str, conversation_id: str):
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT id,role,content,run_id,created_at FROM messages WHERE owner=? AND conversation_id=? ORDER BY created_at", (owner, conversation_id))]


def run_from_row(row):
    if row is None:
        return None
    return {**loads(row["data"]), "id": row["id"], "conversation_id": row["conversation_id"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def get_run(owner: str, id_: str):
    with connect() as db:
        return run_from_row(db.execute("SELECT * FROM runs WHERE id=? AND owner=?", (id_, owner)).fetchone())


def list_runs(owner: str, conversation_id: str | None = None):
    with connect() as db:
        if conversation_id:
            rows = db.execute("SELECT * FROM runs WHERE owner=? AND conversation_id=? ORDER BY created_at DESC LIMIT 200", (owner, conversation_id)).fetchall()
        else:
            rows = db.execute("SELECT * FROM runs WHERE owner=? ORDER BY created_at DESC LIMIT 200", (owner,)).fetchall()
    return [run_from_row(row) for row in rows]


def update_run(owner: str, id_: str, **changes):
    run = get_run(owner, id_)
    status = changes.pop("status", run["status"])
    data = {k: v for k, v in run.items() if k not in {"id", "conversation_id", "status", "created_at", "updated_at"}}
    data.update(changes)
    with connect() as db:
        db.execute("UPDATE runs SET status=?,data=?,updated_at=? WHERE id=? AND owner=?", (status, dumps(data), now(), id_, owner))
    return get_run(owner, id_)


def emit(run_id: str, type_: str, data: dict):
    timestamp = now()
    with connect() as db:
        id_ = db.execute("INSERT INTO events(run_id,type,data,created_at) VALUES (?,?,?,?)", (run_id, type_, dumps(data), timestamp)).lastrowid
    from . import live_events
    live_events.notify(run_id)
    return {"id": id_, "run_id": run_id, "type": type_, "data": data, "created_at": timestamp}


def events(run_id: str, after: int = 0):
    with connect() as db:
        rows = db.execute("SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 1000", (run_id, after)).fetchall()
    return [{**dict(row), "data": loads(row["data"])} for row in rows]


def approvals(owner: str, run_id: str):
    with connect() as db:
        rows = db.execute("SELECT * FROM approvals WHERE owner=? AND run_id=? ORDER BY created_at", (owner, run_id)).fetchall()
    return [{**dict(row), "arguments": loads(row["arguments"])} for row in rows]


def search_knowledge(owner: str, query: str, knowledge_ids: list[str] | None = None, limit: int = 6):
    import re
    terms = re.findall(r"[\w\u4e00-\u9fff]+", query)[:15]
    if not terms:
        return []
    expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    params: list[Any] = [expression, owner]
    clause = ""
    if knowledge_ids:
        clause = " AND knowledge_id IN (" + ",".join("?" for _ in knowledge_ids) + ")"
        params += knowledge_ids
    with connect() as db:
        rows = db.execute("SELECT id,knowledge_id,document_name,content,bm25(chunks) AS score FROM chunks WHERE chunks MATCH ? AND owner=?" + clause + " ORDER BY score LIMIT ?", (*params, limit)).fetchall()
        if not rows:
            params = [owner]
            clause = ""
            if knowledge_ids:
                clause = " AND knowledge_id IN (" + ",".join("?" for _ in knowledge_ids) + ")"
                params += knowledge_ids
            # unicode61 does not segment Chinese. LIKE keeps local Chinese retrieval useful.
            patterns = " OR ".join("content LIKE ? ESCAPE '\\'" for _ in terms[:6])
            escaped = ["%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for term in terms[:6]]
            rows = db.execute("SELECT id,knowledge_id,document_name,content,0 AS score FROM chunks WHERE owner=?" + clause + " AND (" + patterns + ") LIMIT ?", (*params, *escaped, limit)).fetchall()
    return [dict(row) for row in rows]
