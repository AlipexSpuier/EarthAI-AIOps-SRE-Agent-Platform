from __future__ import annotations

from . import defaults, engine, store


def install():
    with store.connect() as db:
        if db.execute("SELECT 1 FROM platform_settings WHERE key='legacy_defaults_migrated'").fetchone():
            return
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM platform_settings WHERE key='legacy_defaults_migrated'").fetchone():
            return
        templates = {row["builtin_key"]: row for row in db.execute("SELECT * FROM default_templates WHERE builtin_key IS NOT NULL")}
        owners = [row["id"] for row in db.execute("SELECT id FROM users")]
        for owner in owners:
            for row in db.execute("SELECT * FROM entities WHERE owner=?", (owner,)).fetchall():
                data = store.loads(row["data"], {})
                source = templates.get(data.get("builtin_key"))
                if source is None or data.get("default_template_id"):
                    continue
                original = store.loads(source["data"], {})
                fields = {"agents": ("name", "description", "system_prompt", "icon", "color", "control_level", "provider_id", "model"), "skills": ("name", "description", "content", "enabled"), "knowledge": ("name", "description")}[row["kind"]]
                expected = dict(original)
                if row["kind"] == "knowledge":
                    expected["description"] += " 通用参考；具体环境、阈值和授权需核实，远端写操作须后台审批。"
                if any(data.get(field) != expected.get(field) for field in fields):
                    continue
                if row["kind"] == "agents":
                    changed_links = False
                    for field, target in (("skill_ids", "skills"), ("knowledge_ids", "knowledge")):
                        links = []
                        for linked_id in data.get(field, []):
                            linked = db.execute("SELECT data FROM entities WHERE owner=? AND kind=? AND id=?", (owner, target, linked_id)).fetchone()
                            links.append(store.loads(linked["data"], {}).get("builtin_key") if linked else None)
                        if links != [f"earthai.{target}.{original['builtin_domain']}"]:
                            changed_links = True
                    if changed_links:
                        continue
                if row["kind"] == "knowledge":
                    old_docs = {(item["name"], item["size"]) for item in db.execute("SELECT name,size FROM documents WHERE owner=? AND knowledge_id=?", (owner, row["id"]))}
                    new_documents = {item["name"]: item["content"] for item in db.execute("SELECT name,content FROM template_documents WHERE template_id=?", (source["id"],))}
                    new_docs = {(name, len(content.encode())) for name, content in new_documents.items()}
                    if old_docs != new_docs:
                        continue
                    identical = True
                    for document in db.execute("SELECT id,name FROM documents WHERE owner=? AND knowledge_id=?", (owner, row["id"])).fetchall():
                        chunks = [item["content"] for item in db.execute("SELECT content FROM chunks WHERE owner=? AND knowledge_id=? AND document_id=? ORDER BY rowid", (owner, row["id"], document["id"]))]
                        text = "".join([chunks[0], *(chunk[250:] for chunk in chunks[1:])]) if chunks else ""
                        if text != new_documents.get(document["name"]):
                            identical = False
                    if not identical:
                        continue
                data["default_template_id"] = source["id"]
                data["read_only"] = True
                db.execute("UPDATE entities SET data=? WHERE id=?", (store.dumps(data), row["id"]))
        db.execute("INSERT INTO platform_settings VALUES (?,?,?)", ("legacy_defaults_migrated", "true", store.now()))


def audit(actor, action, ids):
    store.audit(actor["id"], "admin." + action, ",".join(ids)[:500], store.dumps({"actor": actor["id"], "count": len(ids)}))


def validate_batch(body):
    if not isinstance(body, dict) or set(body) - {"ids", "action", "changes"}:
        raise ValueError("批量操作格式无效")
    ids, action, changes = body.get("ids"), body.get("action"), body.get("changes", {})
    if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or not all(isinstance(id_, str) for id_ in ids) or len(ids) != len(set(ids)):
        raise ValueError("请选择1–500个不重复资源")
    if not isinstance(action, str) or action not in {"delete", "update"} or not isinstance(changes, dict):
        raise ValueError("批量操作仅支持删除或更新")
    return ids, action, changes


def document_details(template_id):
    with store.connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM template_documents WHERE template_id=? ORDER BY created_at,id", (template_id,))]


def save_document(template_id, name, content, id_=None):
    defaults.assert_not_running([template_id])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if id_:
            existing = db.execute("SELECT id FROM template_documents WHERE id=? AND template_id=?", (id_, template_id)).fetchone()
            if existing is None:
                raise ValueError("文档不存在")
            db.execute("UPDATE template_documents SET name=?,content=? WHERE id=? AND template_id=?", (name, content, id_, template_id))
        else:
            id_ = store.uid()
            db.execute("INSERT INTO template_documents VALUES (?,?,?,?,?)", (id_, template_id, name, content, store.now()))
        db.execute("UPDATE default_templates SET updated_at=? WHERE id=?", (store.now(), template_id))
        defaults.sync_all(db)
    return {"id": id_, "name": name, "content": content}


def delete_documents(template_id, ids):
    defaults.assert_not_running([template_id])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = {row["id"] for row in db.execute("SELECT id FROM template_documents WHERE template_id=?", (template_id,))}
        if set(ids) - existing:
            raise ValueError("文档列表已变化")
        for id_ in ids:
            db.execute("DELETE FROM template_documents WHERE template_id=? AND id=?", (template_id, id_))
        db.execute("UPDATE default_templates SET updated_at=? WHERE id=?", (store.now(), template_id))
        defaults.sync_all(db)
    return {"ok": True, "count": len(ids)}


def all_audit(start=None, end=None):
    from .audit_log import boundary
    first, last = boundary(start, "开始时间"), boundary(end, "结束时间")
    if first and last and first > last:
        raise ValueError("结束时间不能早于开始时间")
    clauses, params = [], []
    if first:
        clauses.append("julianday(a.created_at)>=julianday(?)")
        params.append(first)
    if last:
        clauses.append("julianday(a.created_at)<=julianday(?)")
        params.append(last)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with store.connect() as db:
        return [dict(row) for row in db.execute("SELECT a.*,u.email owner_email FROM audit a LEFT JOIN users u ON u.id=a.owner" + where + " ORDER BY julianday(a.created_at) DESC LIMIT 100", params)]


def ensure_template(kind, id_):
    if kind not in defaults.KINDS:
        raise ValueError("默认资源类型无效")
    item = defaults.get_template(kind, id_)
    if item is None:
        raise ValueError("默认资源不存在")
    return item


def next_rank():
    return max((item.get("sort_order", -1) for item in defaults.list_templates("agents")), default=-1) + 1


def validate_schedule(values):
    if values.get("enabled") and not (values.get("provider_id") or any(provider.get("enabled") for provider in defaults.list_templates("providers"))):
        raise ValueError("启用默认定时任务前需配置可用的默认模型供应商，以免为所有用户产生失败任务")
    if values.get("provider_id"):
        provider = defaults.get_template("providers", values["provider_id"])
        if provider and not provider.get("enabled", True) and values.get("enabled"):
            raise ValueError("定时任务关联的供应商已停用")
    values["next_run_at"] = engine.next_cron(values["cron"], values["timezone"])
