from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from . import access, store

MAX_FILE = 20 * 1024 * 1024
MEMBER_ROLES = {"viewer", "editor", "manager"}
FILE_WRITERS = {"owner", "manager", "editor"}
MANAGERS = {"owner", "manager"}
logger = logging.getLogger(__name__)

_SPACE_SELECT = """
    SELECT s.*, owner.email AS owner_email, owner.data AS owner_data,
           membership.role AS member_role,
           coalesce(members.member_count, 0) AS member_count,
           coalesce(files.file_count, 0) AS file_count,
           coalesce(files.total_size, 0) AS total_size
    FROM team_spaces s
    JOIN users owner ON owner.id=s.owner_id
    LEFT JOIN team_members membership ON membership.space_id=s.id AND membership.user_id=?
    LEFT JOIN (SELECT space_id, count(*) AS member_count FROM team_members GROUP BY space_id) members
        ON members.space_id=s.id
    LEFT JOIN (SELECT space_id, count(*) AS file_count, sum(size) AS total_size FROM team_files GROUP BY space_id) files
        ON files.space_id=s.id
"""
_MEMBER_SELECT = """
    SELECT m.*, u.email, u.data AS user_data
    FROM team_members m JOIN users u ON u.id=m.user_id
"""
_FILE_SELECT = """
    SELECT f.*, u.email AS uploader_email, u.data AS uploader_data
    FROM team_files f LEFT JOIN users u ON u.id=f.uploader_id
"""


def initialize():
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS team_spaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                deleted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_team_spaces_owner ON team_spaces(owner_id);
            CREATE TABLE IF NOT EXISTS team_members (
                space_id TEXT NOT NULL REFERENCES team_spaces(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner','manager','editor','viewer')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(space_id,user_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_team_members_owner ON team_members(space_id) WHERE role='owner';
            CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id,space_id);
            CREATE TABLE IF NOT EXISTS team_files (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL REFERENCES team_spaces(id) ON DELETE RESTRICT,
                name TEXT NOT NULL,
                size INTEGER NOT NULL CHECK(size>0 AND size<=20971520),
                mime TEXT NOT NULL,
                storage_name TEXT NOT NULL UNIQUE,
                uploader_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_team_files_space ON team_files(space_id,created_at DESC,id);
            CREATE INDEX IF NOT EXISTS idx_team_files_uploader ON team_files(uploader_id);
        """)


def assert_account_changes(db, ids, action, changes=None):
    if action != "delete" and (changes or {}).get("role") != "admin":
        return
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    if db.execute(f"SELECT 1 FROM team_spaces WHERE owner_id IN ({marks}) LIMIT 1", tuple(ids)).fetchone():
        raise HTTPException(409, "所选账号仍拥有团队空间（包括已归档空间），请先转交所有权")


def _user(row):
    return {**store.loads(row["data"], {}), "id": row["id"], "email": row["email"]}


def _modules(user):
    return access.enabled_spaces(user)


def _actor(db, user, admin):
    row = db.execute("SELECT id,email,data FROM users WHERE id=?", (user["id"],)).fetchone()
    if row is None:
        raise HTTPException(401, "账号已不存在，请重新登录")
    latest = _user(row)
    access.active_user(latest)
    if latest.get("must_change_password"):
        raise HTTPException(403, "首次登录必须修改初始密码")
    if admin:
        access.require_admin(latest)
    else:
        if access.role(latest) != "user":
            raise HTTPException(403, "仅普通账号可访问团队空间入口")
        access.require_space(latest, "team")
    return latest


@contextmanager
def _operation(user, admin=False, write=False):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield db, _actor(db, user, admin)


def _body(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body):
        raise HTTPException(422, "请求字段无效")
    return body


def _text(value, label, maximum, empty=False):
    if not isinstance(value, str):
        raise HTTPException(422, f"{label}必须为文本")
    value = value.strip()
    if len(value) > maximum or (not empty and not value) or "\x00" in value:
        raise HTTPException(422, f"{label}需为{'0' if empty else '1'}–{maximum}个字符")
    return value


def _role(value):
    if not isinstance(value, str) or value not in MEMBER_ROLES:
        raise HTTPException(422, "成员角色必须为 viewer、editor 或 manager")
    return value


def _audit(db, actor, action, resource, detail=None):
    prefix = "admin." if access.role(actor) == "admin" else ""
    db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?)", (
        store.uid(), actor["id"], prefix + action, resource,
        store.dumps(detail or {}), store.now(),
    ))


def _touch(db, space_id, timestamp):
    db.execute("UPDATE team_spaces SET updated_at=? WHERE id=?", (timestamp, space_id))


def _space(db, actor, space_id, admin, active=False):
    row = db.execute(_SPACE_SELECT + " WHERE s.id=?", (actor["id"], space_id)).fetchone()
    if row is None or (not admin and row["member_role"] is None):
        raise HTTPException(404, "团队空间不存在或没有权限")
    if not admin and ((row["member_role"] == "owner") != (row["owner_id"] == actor["id"])):
        raise HTTPException(409, "空间所有者状态不一致，请联系管理员")
    if active and row["deleted_at"] is not None:
        raise HTTPException(409, "团队空间已归档，请先恢复")
    return row


def _permit(space, roles, admin):
    if not admin and space["member_role"] not in roles:
        raise HTTPException(403, "没有执行此团队操作的权限")


def _space_public(row, admin):
    owner = store.loads(row["owner_data"], {})
    return {
        "id": row["id"], "name": row["name"], "description": row["description"],
        "owner_id": row["owner_id"], "owner_name": owner.get("name") or row["owner_email"],
        "role": "admin" if admin else row["member_role"], "archived": row["deleted_at"] is not None,
        "member_count": row["member_count"], "file_count": row["file_count"], "total_size": row["total_size"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _member(db, space_id, user_id):
    row = db.execute(_MEMBER_SELECT + " WHERE m.space_id=? AND m.user_id=?", (space_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "团队成员不存在")
    return row


def _member_public(row):
    user = store.loads(row["user_data"], {})
    return {
        "user_id": row["user_id"], "email": row["email"], "name": user.get("name") or row["email"],
        "role": row["role"], "team_module_enabled": "team" in _modules(user),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _target(row):
    if row is None:
        raise HTTPException(404, "目标账号不存在或不可邀请")
    user = _user(row)
    if access.role(user) != "user" or user.get("disabled") or user.get("must_change_password"):
        raise HTTPException(409, "目标必须为已修改初始密码的启用普通账号")
    return user


def _enable_team(db, target, actor, space_id):
    row = db.execute("SELECT data FROM users WHERE id=?", (target["id"],)).fetchone()
    data = store.loads(row["data"], {})
    modules = _modules(data)
    if "team" in modules:
        return
    if data.get("team_invites_blocked", False):
        raise HTTPException(409, "目标账号的团队入口已被平台关闭，请联系平台管理员重新开启")
    data["space_modules"] = [*modules, "team"]
    db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), target["id"]))
    _audit(db, actor, "team.module.enable", target["id"], {"space_id": space_id})


def list_spaces(user, include_archived=False, *, admin=False):
    with _operation(user, admin) as (db, actor):
        clauses = []
        if not admin:
            clauses.append("membership.user_id IS NOT NULL")
        if not include_archived:
            clauses.append("s.deleted_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = db.execute(_SPACE_SELECT + where + " ORDER BY s.updated_at DESC,s.id", (actor["id"],)).fetchall()
        return [_space_public(row, admin) for row in rows]


def get_space(user, space_id, *, admin=False):
    with _operation(user, admin) as (db, actor):
        return _space_public(_space(db, actor, space_id, admin), admin)


def create_space(user, body, *, admin=False):
    _body(body, {"name", "description", "owner_id"} if admin else {"name", "description"}, {"name", "owner_id"} if admin else {"name"})
    name = _text(body["name"], "空间名称", 200)
    description = _text(body.get("description", ""), "空间描述", 10000, empty=True)
    with _operation(user, admin, write=True) as (db, actor):
        if admin:
            owner_id = _text(body["owner_id"], "所有者 ID", 200)
            owner = _target(db.execute("SELECT id,email,data FROM users WHERE id=?", (owner_id,)).fetchone())
        else:
            owner = actor
        space_id, timestamp = store.uid(), store.now()
        if admin:
            _enable_team(db, owner, actor, space_id)
        db.execute("INSERT INTO team_spaces(id,name,description,owner_id,created_at,updated_at) VALUES (?,?,?,?,?,?)", (
            space_id, name, description, owner["id"], timestamp, timestamp,
        ))
        db.execute("INSERT INTO team_members VALUES (?,?,?,?,?)", (space_id, owner["id"], "owner", timestamp, timestamp))
        _audit(db, actor, "team.space.create", space_id, {"owner_id": owner["id"]})
        return _space_public(_space(db, actor, space_id, admin), admin)


def update_space(user, space_id, body, *, admin=False):
    _body(body, {"name", "description"})
    if not body:
        raise HTTPException(422, "请提供空间名称或描述")
    values = {}
    if "name" in body:
        values["name"] = _text(body["name"], "空间名称", 200)
    if "description" in body:
        values["description"] = _text(body["description"], "空间描述", 10000, empty=True)
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        _permit(space, MANAGERS, admin)
        db.execute("UPDATE team_spaces SET name=?,description=?,updated_at=? WHERE id=?", (
            values.get("name", space["name"]), values.get("description", space["description"]), store.now(), space_id,
        ))
        _audit(db, actor, "team.space.update", space_id, {"fields": sorted(values)})
        return _space_public(_space(db, actor, space_id, admin), admin)


def archive_space(user, space_id, *, admin=False):
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin)
        _permit(space, {"owner"}, admin)
        if space["deleted_at"] is None:
            timestamp = store.now()
            db.execute("UPDATE team_spaces SET deleted_at=?,updated_at=? WHERE id=?", (timestamp, timestamp, space_id))
            _audit(db, actor, "team.space.archive", space_id)
    return {"ok": True}


def restore_space(user, space_id, *, admin=False):
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin)
        _permit(space, {"owner"}, admin)
        if space["deleted_at"] is not None:
            db.execute("UPDATE team_spaces SET deleted_at=NULL,updated_at=? WHERE id=?", (store.now(), space_id))
            _audit(db, actor, "team.space.restore", space_id)
        return _space_public(_space(db, actor, space_id, admin), admin)


def transfer_space(user, space_id, body, *, admin=False):
    _body(body, {"user_id"}, {"user_id"})
    user_id = _text(body["user_id"], "目标成员 ID", 200)
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        _permit(space, {"owner"}, admin)
        if user_id == space["owner_id"]:
            raise HTTPException(409, "目标成员已经是空间所有者")
        _member(db, space_id, user_id)
        target = _target(db.execute("SELECT id,email,data FROM users WHERE id=?", (user_id,)).fetchone())
        _enable_team(db, target, actor, space_id)
        owner_member = _member(db, space_id, space["owner_id"])
        if owner_member["role"] != "owner":
            raise HTTPException(409, "空间所有者状态不一致，请联系管理员")
        timestamp = store.now()
        db.execute("UPDATE team_members SET role='manager',updated_at=? WHERE space_id=? AND user_id=?", (
            timestamp, space_id, space["owner_id"],
        ))
        db.execute("UPDATE team_members SET role='owner',updated_at=? WHERE space_id=? AND user_id=?", (timestamp, space_id, user_id))
        db.execute("UPDATE team_spaces SET owner_id=?,updated_at=? WHERE id=?", (user_id, timestamp, space_id))
        _audit(db, actor, "team.space.transfer", space_id, {"previous_owner_id": space["owner_id"], "owner_id": user_id})
        return _space_public(_space(db, actor, space_id, admin), admin)


def list_members(user, space_id, *, admin=False):
    with _operation(user, admin) as (db, actor):
        _space(db, actor, space_id, admin)
        rows = db.execute(_MEMBER_SELECT + " WHERE m.space_id=? ORDER BY m.created_at,m.user_id", (space_id,)).fetchall()
        return [_member_public(row) for row in rows]


def add_member(user, space_id, body, *, admin=False):
    _body(body, {"email", "role"}, {"email", "role"})
    email = _text(body["email"], "账号", 254).lower()
    role = _role(body["role"])
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        _permit(space, MANAGERS, admin)
        if not admin and space["member_role"] == "manager" and role == "manager":
            raise HTTPException(403, "仅所有者或平台管理员可授予管理者角色")
        row = db.execute("SELECT id,email,data FROM users WHERE email=?", (email,)).fetchone()
        if row is not None and db.execute("SELECT 1 FROM team_members WHERE space_id=? AND user_id=?", (space_id, row["id"])).fetchone():
            raise HTTPException(409, "此账号已经是团队成员")
        target = _target(row)
        _enable_team(db, target, actor, space_id)
        timestamp = store.now()
        db.execute("INSERT INTO team_members VALUES (?,?,?,?,?)", (space_id, target["id"], role, timestamp, timestamp))
        _touch(db, space_id, timestamp)
        _audit(db, actor, "team.member.add", space_id, {"user_id": target["id"], "role": role})
        return _member_public(_member(db, space_id, target["id"]))


def update_member(user, space_id, user_id, body, *, admin=False):
    _body(body, {"role"}, {"role"})
    role = _role(body["role"])
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        _permit(space, MANAGERS, admin)
        member = _member(db, space_id, user_id)
        if user_id == space["owner_id"] or member["role"] == "owner":
            raise HTTPException(409, "不能降级空间所有者，请先转交所有权")
        if not admin and space["member_role"] == "manager" and (member["role"] == "manager" or role == "manager"):
            raise HTTPException(403, "管理者只能管理编辑者和查看者，不能管理或授予管理者")
        timestamp = store.now()
        db.execute("UPDATE team_members SET role=?,updated_at=? WHERE space_id=? AND user_id=?", (role, timestamp, space_id, user_id))
        _touch(db, space_id, timestamp)
        _audit(db, actor, "team.member.update", space_id, {"user_id": user_id, "role": role})
        return _member_public(_member(db, space_id, user_id))


def remove_member(user, space_id, user_id, *, admin=False):
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        member = _member(db, space_id, user_id)
        if user_id == space["owner_id"] or member["role"] == "owner":
            raise HTTPException(409, "所有者不能被移除或退出，请先转交所有权")
        if admin or user_id != actor["id"]:
            _permit(space, MANAGERS, admin)
            if not admin and space["member_role"] == "manager" and member["role"] == "manager":
                raise HTTPException(403, "管理者不能移除其他管理者")
        db.execute("DELETE FROM team_members WHERE space_id=? AND user_id=?", (space_id, user_id))
        _touch(db, space_id, store.now())
        _audit(db, actor, "team.member.leave" if user_id == actor["id"] else "team.member.remove", space_id, {"user_id": user_id})
    return {"ok": True}


def _file(db, space_id, file_id):
    row = db.execute(_FILE_SELECT + " WHERE f.space_id=? AND f.id=?", (space_id, file_id)).fetchone()
    if row is None:
        raise HTTPException(404, "团队文件不存在")
    return row


def _file_public(row):
    uploader = store.loads(row["uploader_data"], {})
    return {
        "id": row["id"], "space_id": row["space_id"], "name": row["name"], "size": row["size"], "mime": row["mime"],
        "uploader_id": row["uploader_id"], "uploader_name": uploader.get("name") or row["uploader_email"] or "已删除用户",
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _filename(value):
    if not isinstance(value, str):
        raise HTTPException(422, "文件名称必须为文本")
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or len(name) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise HTTPException(422, "文件名称需为1–200个字符的有效文件名")
    return name


def _content(content, mime):
    if len(content) > MAX_FILE:
        raise HTTPException(413, "文件超过 20 MB 上限")
    if not content:
        raise HTTPException(422, "不能上传空文件")
    return _text(mime or "application/octet-stream", "文件类型", 255)


def _unlink(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("团队文件清理失败", exc_info=True)


def _write_blob(content):
    storage_name = "team-" + store.uid()
    path = store.UPLOADS / storage_name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        _unlink(path)
        raise
    return storage_name, path


def list_files(user, space_id, *, admin=False):
    with _operation(user, admin) as (db, actor):
        _space(db, actor, space_id, admin, active=True)
        rows = db.execute(_FILE_SELECT + " WHERE f.space_id=? ORDER BY f.created_at DESC,f.id", (space_id,)).fetchall()
        return [_file_public(row) for row in rows]


def get_file(user, space_id, file_id, *, admin=False):
    with _operation(user, admin) as (db, actor):
        _space(db, actor, space_id, admin, active=True)
        return _file_public(_file(db, space_id, file_id))


def upload_file(user, space_id, content, name, mime=None, *, admin=False):
    name, mime = _filename(name), _content(content, mime)
    new_path = None
    try:
        with _operation(user, admin, write=True) as (db, actor):
            space = _space(db, actor, space_id, admin, active=True)
            _permit(space, FILE_WRITERS, admin)
            storage_name, new_path = _write_blob(content)
            file_id, timestamp = store.uid(), store.now()
            db.execute("INSERT INTO team_files VALUES (?,?,?,?,?,?,?,?,?)", (
                file_id, space_id, name, len(content), mime, storage_name, actor["id"], timestamp, timestamp,
            ))
            _touch(db, space_id, timestamp)
            _audit(db, actor, "team.file.upload", file_id, {"space_id": space_id})
            result = _file_public(_file(db, space_id, file_id))
    except BaseException:
        if new_path is not None:
            _unlink(new_path)
        raise
    return result


def rename_file(user, space_id, file_id, body, *, admin=False):
    _body(body, {"name"}, {"name"})
    name = _filename(body["name"])
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        _permit(space, FILE_WRITERS, admin)
        _file(db, space_id, file_id)
        timestamp = store.now()
        db.execute("UPDATE team_files SET name=?,updated_at=? WHERE space_id=? AND id=?", (name, timestamp, space_id, file_id))
        _touch(db, space_id, timestamp)
        _audit(db, actor, "team.file.rename", file_id, {"space_id": space_id})
        return _file_public(_file(db, space_id, file_id))


def replace_file(user, space_id, file_id, content, mime=None, *, admin=False):
    mime = _content(content, mime)
    new_path = None
    try:
        with _operation(user, admin, write=True) as (db, actor):
            space = _space(db, actor, space_id, admin, active=True)
            _permit(space, FILE_WRITERS, admin)
            existing = _file(db, space_id, file_id)
            old_path = store.UPLOADS / existing["storage_name"]
            storage_name, new_path = _write_blob(content)
            timestamp = store.now()
            db.execute("UPDATE team_files SET size=?,mime=?,storage_name=?,updated_at=? WHERE space_id=? AND id=?", (
                len(content), mime, storage_name, timestamp, space_id, file_id,
            ))
            _touch(db, space_id, timestamp)
            _audit(db, actor, "team.file.replace", file_id, {"space_id": space_id})
            result = _file_public(_file(db, space_id, file_id))
    except BaseException:
        if new_path is not None:
            _unlink(new_path)
        raise
    _unlink(old_path)
    return result


def download_file(user, space_id, file_id, *, admin=False):
    with _operation(user, admin) as (db, actor):
        _space(db, actor, space_id, admin, active=True)
        existing = _file(db, space_id, file_id)
        path = Path(store.UPLOADS) / existing["storage_name"]
        if not path.is_file():
            raise HTTPException(404, "团队文件内容不存在")
        return _file_public(existing), path


def delete_file(user, space_id, file_id, *, admin=False):
    with _operation(user, admin, write=True) as (db, actor):
        space = _space(db, actor, space_id, admin, active=True)
        _permit(space, FILE_WRITERS, admin)
        existing = _file(db, space_id, file_id)
        path = store.UPLOADS / existing["storage_name"]
        db.execute("DELETE FROM team_files WHERE space_id=? AND id=?", (space_id, file_id))
        _touch(db, space_id, store.now())
        _audit(db, actor, "team.file.delete", file_id, {"space_id": space_id})
    _unlink(path)
    return {"ok": True}
