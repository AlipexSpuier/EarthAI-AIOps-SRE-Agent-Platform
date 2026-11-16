from __future__ import annotations

from . import store


def pin_first_key(server, actual):
    id_ = server.get("id")
    if not id_:
        raise ValueError("自动信任需要已保存的服务器连接")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT owner,data FROM entities WHERE kind='servers' AND id=?", (id_,)).fetchone()
        if row is None:
            raise ValueError("服务器已删除，未信任主机密钥")
        data = store.loads(row["data"], {})
        if data.get("kind", "ssh") != "ssh" or any(data.get(field, default) != server.get(field, default) for field, default in (("host", ""), ("port", 22))):
            raise ValueError("连接期间服务器目标已变化，未信任旧目标指纹")
        expected = data.get("fingerprint", "")
        if expected:
            if expected.rstrip("=") != actual:
                raise ValueError("SSH 主机指纹已变化，自动信任不会覆盖已固定指纹")
        else:
            if data.get("trust_on_first_use") is not True or server.get("trust_on_first_use") is not True:
                raise ValueError("此连接未启用首次自动信任")
            data["fingerprint"] = actual
            data["fingerprint_trusted_at"] = store.now()
            db.execute("UPDATE entities SET data=? WHERE id=? AND owner=? AND kind='servers'", (store.dumps(data), id_, row["owner"]))
            db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?)", (store.uid(), row["owner"], "server.fingerprint.trust_first", id_, "首次连接自动记录主机指纹 " + actual, store.now()))
    server["fingerprint"] = actual
    if data.get("fingerprint_trusted_at"):
        server["fingerprint_trusted_at"] = data["fingerprint_trusted_at"]
    return actual
