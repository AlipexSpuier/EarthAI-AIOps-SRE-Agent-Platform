from __future__ import annotations

import copy
import hashlib
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from . import access, presets, store

KINDS = ("knowledge", "skills", "servers", "providers", "agents", "projects", "schedules")
SINGLE_REFS = {"server_id": "servers", "provider_id": "providers", "agent_id": "agents", "project_id": "projects"}
MULTI_REFS = {"skill_ids": "skills", "knowledge_ids": "knowledge", "server_ids": "servers"}
SYNC_SIGNATURE_KEY = "default_sync_signature_v1"


def init_tables():
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS default_templates (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL,
            builtin_key TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS template_documents (
            id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES default_templates(id) ON DELETE CASCADE,
            name TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_template_documents_template ON template_documents(template_id);
        CREATE TABLE IF NOT EXISTS platform_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS default_sync_revisions (
            owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            sync_revision TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS default_owner_states (
            owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            template_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('override','deleted')),
            PRIMARY KEY(owner,template_id)
        );
        """)


def initialize():
    init_tables()
    with store.connect() as db:
        if db.execute("SELECT 1 FROM platform_settings WHERE key='default_catalog_v1'").fetchone():
            return
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM platform_settings WHERE key='default_catalog_v1'").fetchone():
            return
        stamp = store.now()
        for position, preset in enumerate(presets.PRESETS):
            knowledge_id, skill_id, agent_id = [store.uid() for _ in range(3)]
            rows = [
                (knowledge_id, "knowledge", {"name": preset["knowledge_name"], "description": preset["description"]}),
                (skill_id, "skills", {"name": preset["skill_name"], "description": preset["skill_description"], "content": preset["skill_content"], "enabled": True}),
                (agent_id, "agents", {"name": preset["agent_name"], "description": preset["agent_role"], "system_prompt": preset["agent_role"] + presets.AGENT_BOUNDARIES, "kind": "local", "url": "", "icon": "Bot", "color": preset["color"], "skill_ids": [skill_id], "knowledge_ids": [knowledge_id], "provider_id": None, "model": "", "control_level": preset["control_level"], "sort_order": position}),
            ]
            for id_, kind, data in rows:
                data.update(builtin_domain=preset["key"], builtin_key=f"earthai.{kind}.{preset['key']}", builtin_version=presets.PRESET_VERSION)
                db.execute("INSERT INTO default_templates VALUES (?,?,?,?,?,?)", (id_, kind, store.dumps(data), data["builtin_key"], stamp, stamp))
            for document in preset["documents"]:
                text = f"# {document['name'].removesuffix('.md')}\n\n{presets.REFERENCE_NOTICE}{document['content']}"
                db.execute("INSERT INTO template_documents VALUES (?,?,?,?,?)", (store.uid(), knowledge_id, document["name"], text, stamp))
        db.execute("INSERT INTO platform_settings VALUES (?,?,?)", ("default_catalog_v1", store.dumps({"version": presets.PRESET_VERSION}), stamp))


def template(row):
    return {**store.loads(row["data"], {}), "id": row["id"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_templates(kind):
    with store.connect() as db:
        rows = db.execute("SELECT * FROM default_templates WHERE kind=? ORDER BY created_at,id", (kind,)).fetchall()
    values = [template(row) for row in rows]
    if kind == "agents":
        values.sort(key=lambda item: (item.get("sort_order", 10**9), item["created_at"], item["id"]))
    return values


def get_template(kind, id_):
    with store.connect() as db:
        row = db.execute("SELECT * FROM default_templates WHERE kind=? AND id=?", (kind, id_)).fetchone()
    return template(row) if row else None


def remap(data, mapping):
    values = copy.deepcopy(data)
    lost_reference = False
    for field in SINGLE_REFS:
        if values.get(field):
            values[field] = mapping.get(values[field])
            lost_reference |= values[field] is None
    for field in MULTI_REFS:
        if field in values:
            links = [mapping.get(id_) for id_ in values[field]]
            values[field] = [id_ for id_ in links if id_ is not None]
            lost_reference |= len(values[field]) != len(links)
    if lost_reference and "cron" in values:
        values.update(enabled=False, default_references_disabled=True)
    return values


def mark_personal(owner, kind, resource, state, db):
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    latest = store.entity(db.execute("SELECT * FROM entities WHERE owner=? AND kind=? AND id=?",
                                     (owner, kind, resource["id"])).fetchone())
    if latest is None:
        raise HTTPException(404, "资源不存在或没有权限")
    access.writable(kind, latest)
    if latest.get("default_template_id"):
        db.execute("""INSERT INTO default_owner_states(owner,template_id,entity_id,state) VALUES (?,?,?,?)
            ON CONFLICT(owner,template_id) DO UPDATE SET entity_id=excluded.entity_id,state=excluded.state""",
                   (owner, latest["default_template_id"], latest["id"], state))
        if state == "override" and not latest.get("personal_override"):
            latest["personal_override"] = True
            values = {key: value for key, value in latest.items() if key not in {"id", "created_at", "updated_at"}}
            db.execute("UPDATE entities SET data=? WHERE owner=? AND kind=? AND id=?", (store.dumps(values), owner, kind, latest["id"]))
    return latest


def save_personal(owner, kind, id_, data):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = mark_personal(owner, kind, {"id": id_}, "override", db)
        if latest.get("default_template_id") and kind == "agents" and data.get("kind", "local") != "local":
            raise HTTPException(422, "个人默认本地智能体不能改为远程智能体")
        metadata = {"id", "created_at", "updated_at", "sort_order", "read_only", "personal_override"}
        values = {key: value for key, value in data.items()
                  if key not in metadata and not key.startswith(("default_", "builtin_"))}
        values.update({key: value for key, value in latest.items()
                       if key in {"sort_order", "read_only", "personal_override"} or key.startswith(("default_", "builtin_"))})
        stamp = store.now()
        db.execute("UPDATE entities SET data=?,updated_at=? WHERE owner=? AND kind=? AND id=?",
                   (store.dumps(values), stamp, owner, kind, latest["id"]))
        return {**values, "id": latest["id"], "created_at": latest["created_at"], "updated_at": stamp}


def delete_personal(owner, kind, id_):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if kind in {"skills", "knowledge"} and db.execute("SELECT 1 FROM runs WHERE owner=? AND status IN ('queued','running','waiting_approval') LIMIT 1", (owner,)).fetchone():
            raise HTTPException(409, "账号仍有活动任务，请先停止任务再删除技能或知识库")
        latest = mark_personal(owner, kind, {"id": id_}, "deleted", db)
        db.execute("DELETE FROM chunks WHERE owner=? AND knowledge_id=?", (owner, id_))
        db.execute("DELETE FROM documents WHERE owner=? AND knowledge_id=?", (owner, id_))
        db.execute("DELETE FROM entities WHERE owner=? AND kind=? AND id=?", (owner, kind, id_))
        _clear_references(owner, [{"id": latest["id"], "kind": kind}], db, store.now())
    return {"ok": True}


def _catalog_revision(rows):
    revisions = [(row["id"], row["updated_at"]) for row in rows]
    return hashlib.sha256(store.dumps(revisions).encode()).hexdigest()


def _prepare_templates(db):
    rows = db.execute("SELECT * FROM default_templates ORDER BY id").fetchall()
    return {
        "templates": [{**dict(row), "data": store.loads(row["data"], {})} for row in rows],
        "revision": _catalog_revision(rows),
    }


def _template_documents(db, prepared):
    if "documents" not in prepared:
        documents = {}
        for row in db.execute("SELECT * FROM template_documents ORDER BY id"):
            text = row["content"]
            documents.setdefault(row["template_id"], []).append({
                "id": row["id"], "name": row["name"], "size": len(text.encode()),
                "chunks": [text[index:index + 1400] for index in range(0, len(text), 1150)],
            })
        prepared["documents"] = documents
    return prepared["documents"]


def _sync_users(db):
    return db.execute("""SELECT u.id,coalesce(json_extract(u.data,'$.role'),'user') role,s.sync_revision
        FROM users u LEFT JOIN default_sync_revisions s ON s.owner=u.id ORDER BY u.id""").fetchall()


def _sync_signature(revision, users):
    value = {"catalog": revision, "users": [(row["id"], row["role"]) for row in users]}
    return hashlib.sha256(store.dumps(value).encode()).hexdigest()


def _store_sync_signature(db, signature):
    old = db.execute("SELECT value FROM platform_settings WHERE key=?", (SYNC_SIGNATURE_KEY,)).fetchone()
    if old is None or old["value"] != signature:
        db.execute("""INSERT INTO platform_settings VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                   (SYNC_SIGNATURE_KEY, signature, store.now()))


def _clear_references(owner, removed, db, stamp):
    clauses, params = [], [owner]
    for field, kind in SINGLE_REFS.items():
        ids = [row["id"] for row in removed if row["kind"] == kind]
        if ids:
            clauses.append(f"json_extract(data,'$.{field}') IN ({','.join('?' for _ in ids)})")
            params.extend(ids)
    for field, kind in MULTI_REFS.items():
        ids = [row["id"] for row in removed if row["kind"] == kind]
        if ids:
            clauses.append(f"EXISTS (SELECT 1 FROM json_each(entities.data,'$.{field}') WHERE value IN ({','.join('?' for _ in ids)}))")
            params.extend(ids)
    if not clauses:
        return {}
    rows = db.execute("SELECT id,kind,data FROM entities WHERE owner=? AND (" + " OR ".join(clauses) + ")", params).fetchall()
    removed_ids = {kind: {row["id"] for row in removed if row["kind"] == kind} for kind in KINDS}
    changed = {}
    for resource in rows:
        values = store.loads(resource["data"], {})
        for field, kind in SINGLE_REFS.items():
            if values.get(field) in removed_ids[kind]:
                values[field] = None
        for field, kind in MULTI_REFS.items():
            if removed_ids[kind] and removed_ids[kind].intersection(values.get(field, [])):
                values[field] = [value for value in values[field] if value not in removed_ids[kind]]
        if resource["kind"] == "schedules":
            values["enabled"] = False
            if values.get("default_template_id"):
                values["default_references_disabled"] = True
        db.execute("UPDATE entities SET data=?,updated_at=? WHERE owner=? AND id=?", (store.dumps(values), stamp, owner, resource["id"]))
        changed[resource["id"]] = values
    return changed


def sync_user(owner, db=None):
    if db is None:
        with store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return sync_user(owner, connection)
    row = db.execute("""SELECT coalesce(json_extract(u.data,'$.role'),'user') role,s.sync_revision
        FROM users u LEFT JOIN default_sync_revisions s ON s.owner=u.id WHERE u.id=?""", (owner,)).fetchone()
    if row is None or row["role"] == "admin":
        return
    _sync_user(owner, db, _prepare_templates(db), row["sync_revision"])


def _sync_user(owner, db, prepared, sync_revision):
    templates = prepared["templates"]
    states = {row["template_id"]: row for row in db.execute(
        "SELECT template_id,entity_id,state FROM default_owner_states WHERE owner=?", (owner,))}
    existing = db.execute("SELECT * FROM entities WHERE owner=? AND kind IN (" + ",".join("?" for _ in KINDS)
                          + ") AND json_extract(data,'$.default_template_id') IS NOT NULL", (owner, *KINDS)).fetchall()
    by_source = {}
    for item in existing:
        values = store.loads(item["data"], {})
        if values.get("default_template_id"):
            by_source[values["default_template_id"]] = (item, values)
    mapping = {item["id"]: (states[item["id"]]["entity_id"] if item["id"] in states
                            else by_source[item["id"]][0]["id"] if item["id"] in by_source
                            else str(uuid5(NAMESPACE_URL, f"earthai.default:{owner}:{item['id']}"))) for item in templates}
    mapping.update({source: state["entity_id"] if state["state"] == "override" else None
                    for source, state in states.items()})
    template_ids = {item["id"] for item in templates}
    stamp = store.now()
    removed = [old for source, (old, _) in by_source.items()
               if (source in states and states[source]["state"] == "deleted")
               or (source not in template_ids and source not in states)]
    for old in removed:
        db.execute("DELETE FROM chunks WHERE owner=? AND knowledge_id=?", (owner, old["id"]))
        db.execute("DELETE FROM documents WHERE owner=? AND knowledge_id=?", (owner, old["id"]))
        db.execute("DELETE FROM entities WHERE owner=? AND id=?", (owner, old["id"]))
    if removed:
        changed = _clear_references(owner, removed, db, stamp)
        by_source = {source: (old, changed.get(old["id"], data)) for source, (old, data) in by_source.items()}
    for row in templates:
        old, old_data = by_source.get(row["id"], (None, {}))
        state = states.get(row["id"])
        if state:
            if state["state"] == "override" and old and old["kind"] == row["kind"] == "agents":
                data = dict(old_data)
                if "sort_order" in row["data"]:
                    data["sort_order"] = row["data"]["sort_order"]
                else:
                    data.pop("sort_order", None)
                if data != old_data:
                    db.execute("UPDATE entities SET data=?,updated_at=? WHERE owner=? AND kind='agents' AND id=?",
                               (store.dumps(data), stamp, owner, old["id"]))
            continue
        if old and old_data.get("default_revision") == row["updated_at"]:
            continue
        data = remap(row["data"], mapping)
        data.update(default_template_id=row["id"], default_revision=row["updated_at"], read_only=True)
        if row["kind"] == "servers" and (data.get("host"), data.get("port")) == (old_data.get("host"), old_data.get("port")):
            if not data.get("fingerprint"):
                for key in ("fingerprint", "fingerprint_trusted_at"):
                    if old_data.get(key):
                        data[key] = old_data[key]
            for key in ("status", "last_checked_at"):
                if key in old_data:
                    data[key] = old_data[key]
        if row["kind"] == "schedules":
            if old_data.get("default_references_disabled"):
                data.update(enabled=False, default_references_disabled=True)
            for key in ("last_run_at", "last_run_id"):
                if key in old_data:
                    data[key] = old_data[key]
            if old_data.get("cron") == data.get("cron") and old_data.get("timezone") == data.get("timezone") and old_data.get("next_run_at"):
                data["next_run_at"] = old_data["next_run_at"]
        db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at", (mapping[row["id"]], owner, row["kind"], store.dumps(data), old["created_at"] if old else stamp, stamp))
        if row["kind"] == "knowledge":
            knowledge_id = mapping[row["id"]]
            db.execute("DELETE FROM chunks WHERE owner=? AND knowledge_id=?", (owner, knowledge_id))
            db.execute("DELETE FROM documents WHERE owner=? AND knowledge_id=?", (owner, knowledge_id))
            for document in _template_documents(db, prepared).get(row["id"], []):
                id_ = str(uuid5(NAMESPACE_URL, f"earthai.document:{owner}:{document['id']}"))
                chunks = document["chunks"]
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", (id_, owner, knowledge_id, document["name"], document["size"], len(chunks), stamp))
                db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)", [(store.uid(), owner, knowledge_id, id_, document["name"], chunk) for chunk in chunks])
    if sync_revision != prepared["revision"]:
        db.execute("""INSERT INTO default_sync_revisions VALUES (?,?)
            ON CONFLICT(owner) DO UPDATE SET sync_revision=excluded.sync_revision""", (owner, prepared["revision"]))


def sync_all(db=None):
    if db is None:
        with store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return sync_all(connection)
    prepared = _prepare_templates(db)
    users = _sync_users(db)
    for user in users:
        if user["role"] != "admin":
            _sync_user(user["id"], db, prepared, user["sync_revision"])
    _store_sync_signature(db, _sync_signature(prepared["revision"], users))


def _sync_needed(db):
    rows = db.execute("SELECT id,updated_at FROM default_templates ORDER BY id").fetchall()
    revision = _catalog_revision(rows)
    users = _sync_users(db)
    stored = db.execute("SELECT value FROM platform_settings WHERE key=?", (SYNC_SIGNATURE_KEY,)).fetchone()
    return (stored is None or stored["value"] != _sync_signature(revision, users)
            or any(user["role"] != "admin" and user["sync_revision"] != revision for user in users))


def sync_all_if_needed():
    with store.connect() as db:
        if not _sync_needed(db):
            return False
        db.execute("BEGIN IMMEDIATE")
        # Recheck after taking the write lock so concurrent startup syncs remain no-ops.
        if not _sync_needed(db):
            return False
        sync_all(db)
        return True


def references(kind, id_):
    result = []
    for other_kind in KINDS:
        for item in list_templates(other_kind):
            if item["id"] == id_:
                continue
            if any(item.get(field) == id_ for field, target in SINGLE_REFS.items() if target == kind) or any(id_ in item.get(field, []) for field, target in MULTI_REFS.items() if target == kind):
                result.append(item["name"])
    return result


def assert_not_running(ids):
    with store.connect() as db:
        copies = [(row["owner"], row["id"], row["kind"]) for row in db.execute("SELECT owner,id,kind,data FROM entities") if store.loads(row["data"], {}).get("default_template_id") in ids]
        for owner, id_, kind in copies:
            for run in db.execute("SELECT data FROM runs WHERE owner=? AND status IN ('queued','running','waiting_approval')", (owner,)):
                data = store.loads(run["data"], {})
                if kind in {"skills", "knowledge"} or any(data.get(field) == id_ for field in SINGLE_REFS):
                    raise ValueError("默认资源被执行中的任务使用，请等待任务完成后修改")


def save(kind, data, id_=None, db=None):
    if db is None:
        with store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            value = save(kind, data, id_, connection)
            sync_all(connection)
            return value
    stamp = store.now()
    if id_:
        old = db.execute("SELECT * FROM default_templates WHERE kind=? AND id=?", (kind, id_)).fetchone()
        if old is None:
            raise ValueError("默认资源不存在")
        builtin = old["builtin_key"]
        created = old["created_at"]
    else:
        id_, builtin, created = store.uid(), None, stamp
    db.execute("INSERT INTO default_templates VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at", (id_, kind, store.dumps(data), builtin, created, stamp))
    return {**data, "id": id_, "created_at": created, "updated_at": stamp}


def delete_many(kind, ids, db):
    for id_ in ids:
        db.execute("DELETE FROM default_templates WHERE kind=? AND id=?", (kind, id_))
    for row in db.execute("SELECT * FROM default_templates").fetchall():
        data = store.loads(row["data"], {})
        changed = False
        for field, target in SINGLE_REFS.items():
            if target == kind and data.get(field) in ids:
                data[field] = None
                changed = True
        for field, target in MULTI_REFS.items():
            if target == kind and set(data.get(field, [])) & set(ids):
                data[field] = [value for value in data[field] if value not in ids]
                changed = True
        if changed:
            if row["kind"] == "schedules":
                data["enabled"] = False
            db.execute("UPDATE default_templates SET data=?,updated_at=? WHERE id=?", (store.dumps(data), store.now(), row["id"]))
