from __future__ import annotations

from urllib.parse import urlparse

from . import store


def validate_remote_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 33 for char in value):
        raise ValueError("远程智能体链接必须为不含空白的有效 HTTP(S) 地址")
    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("远程智能体链接端口无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or "\\" in value:
        raise ValueError("远程智能体只支持 HTTP(S) 网页链接，不允许脚本、文件协议或内嵌账号密码")
    return value


def ensure_order(owner):
    with store.connect() as db:
        rows = db.execute("SELECT id,data,created_at FROM entities WHERE owner=? AND kind='agents' ORDER BY created_at,id", (owner,)).fetchall()
        managed = [store.loads(row["data"], {}) for row in rows]
        if all(data.get("default_template_id") or type(data.get("sort_order")) is int and data["sort_order"] >= 0 for data in managed):
            return len(rows)
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id,data,created_at FROM entities WHERE owner=? AND kind='agents' ORDER BY created_at,id", (owner,)).fetchall()
        ranked, pending = [], []
        for row in rows:
            data = store.loads(row["data"], {})
            value = data.get("sort_order")
            (ranked if type(value) is int and value >= 0 else pending).append((row, data))
        ranked.sort(key=lambda item: (item[1]["sort_order"], item[0]["created_at"], item[0]["id"]))
        for index, (row, data) in enumerate([*ranked, *pending]):
            if data.get("sort_order") != index and not data.get("default_template_id"):
                data["sort_order"] = index
                db.execute("UPDATE entities SET data=? WHERE id=? AND owner=? AND kind='agents'", (store.dumps(data), row["id"], owner))
    return len(rows)


def reorder(owner, ids):
    if not isinstance(ids, list) or not all(isinstance(id_, str) for id_ in ids) or len(ids) != len(set(ids)):
        raise ValueError("智能体排序必须为无重复的 ID 数组")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id,data FROM entities WHERE owner=? AND kind='agents'", (owner,)).fetchall()
        values = {row["id"]: store.loads(row["data"], {}) for row in rows}
        if set(ids) != set(values):
            raise ValueError("智能体列表已变化或包含无权限资源，请刷新后重新排序")
        db.execute("INSERT INTO agent_orders VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET ids=excluded.ids", (owner, store.dumps(ids)))
        for index, id_ in enumerate(ids):
            data = values[id_]
            if data.get("default_template_id"):
                continue
            data["sort_order"] = index
            db.execute("UPDATE entities SET data=? WHERE owner=? AND kind='agents' AND id=?", (store.dumps(data), owner, id_))
    store.audit(owner, "agents.reorder", "agents", f"保存 {len(ids)} 个智能体的自定义顺序")
    return store.list_entities(owner, "agents")


def create_agent(owner, data):
    ensure_order(owner)
    id_, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT data FROM entities WHERE owner=? AND kind='agents'", (owner,)).fetchall()
        maximum = max((store.loads(row["data"], {}).get("sort_order", -1) for row in rows), default=-1)
        values = {**data, "sort_order": maximum + 1}
        db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (id_, owner, "agents", store.dumps(values), stamp, stamp))
    return store.get_entity(owner, "agents", id_)


def update_agent(owner, id_, data):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM entities WHERE owner=? AND kind='agents' AND id=?", (owner, id_)).fetchone()
        if row is None:
            raise ValueError("智能体已删除，请刷新列表")
        latest = store.loads(row["data"], {})
        values = {key: value for key, value in data.items() if key != "sort_order"}
        if "sort_order" in latest:
            values["sort_order"] = latest["sort_order"]
        db.execute("UPDATE entities SET data=?,updated_at=? WHERE owner=? AND kind='agents' AND id=?", (store.dumps(values), store.now(), owner, id_))
    return store.get_entity(owner, "agents", id_)


def is_local(agent):
    return agent is not None and agent.get("kind", "local") == "local"
