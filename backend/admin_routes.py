from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import admin, admin_catalog, branding, defaults, provider_sync, store, usage


def create_router(current_admin, prepare_entity, public_entity):
    router = APIRouter()

    def public_template(kind, value, knowledge_counts=None, usage_counts=None):
        counts = knowledge_counts if knowledge_counts is not None else {} if kind == "knowledge" else None
        result = public_entity(kind, value, counts)
        result["read_only"] = False
        if kind in usage.KINDS:
            totals = usage.counts(kind) if usage_counts is None else usage_counts
            result["usage_count"] = totals.get(value["id"], 0)
        if kind == "knowledge":
            if knowledge_counts is None:
                docs = admin_catalog.document_details(value["id"])
                result["document_count"] = len(docs)
                result["chunk_count"] = sum(len(range(0, len(item["content"]), 1150)) for item in docs)
        return result

    def validate(kind, body, user, existing=None):
        if kind not in defaults.KINDS:
            raise HTTPException(404, "默认资源类型无效")
        value = prepare_entity(user["id"], kind, body, user, existing, template_mode=True)
        if kind == "schedules":
            if existing is None and "enabled" not in body:
                value["enabled"] = False
            admin_catalog.validate_schedule(value)
        if kind == "agents":
            if "sort_order" in body:
                order = body["sort_order"]
                if type(order) is not int or not 0 <= order <= 100000:
                    raise ValueError("默认排序需为0–100000的整数")
                value["sort_order"] = order
            elif existing is None:
                value["sort_order"] = admin_catalog.next_rank()
        return value

    def apply(kind, ids, action, changes, user):
        if kind not in defaults.KINDS:
            raise HTTPException(404, "默认资源类型无效")
        existing = [admin_catalog.ensure_template(kind, id_) for id_ in ids]
        defaults.assert_not_running(ids)
        values = [validate(kind, changes, user, item) for item in existing] if action == "update" else []
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if action == "delete":
                defaults.delete_many(kind, ids, db)
            else:
                for id_, value in zip(ids, values):
                    defaults.save(kind, value, id_, db)
            defaults.sync_all(db)
        admin_catalog.audit(user, f"defaults.{kind}.{action}", ids)
        return {"ok": True, "count": len(ids)}

    @router.get("/site.webmanifest", include_in_schema=False)
    async def site_manifest():
        value = branding.get()
        icon = value.get("icon_url")
        icons = [{"src": icon, "sizes": "any"}] if icon else [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]
        return JSONResponse({"name": value["name"] + " · " + value["subtitle"], "short_name": value["name"], "lang": "zh-CN", "start_url": "/", "display": "standalone", "background_color": "#101b19", "theme_color": "#087f69", "icons": icons}, media_type="application/manifest+json")

    @router.get("/favicon.ico", include_in_schema=False)
    async def site_favicon():
        value = branding.get().get("favicon_url", "")
        path = branding.asset_path(value.rsplit("/", 1)[-1]) if value.startswith("/api/branding/assets/") else store.ROOT / "frontend" / "dist" / "favicon.ico"
        if not path.is_file():
            raise HTTPException(404, "网站图标不存在")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @router.get("/api/branding")
    async def get_branding():
        return branding.get()

    @router.get("/api/branding/assets/{name}")
    async def get_asset(name: str):
        path = branding.asset_path(name)
        if not path.is_file():
            raise HTTPException(404, "品牌图片不存在")
        return FileResponse(path)

    @router.patch("/api/admin/branding")
    async def update_branding(request: Request, user=Depends(current_admin)):
        value = branding.save(await request.json())
        admin_catalog.audit(user, "branding.update", ["branding"])
        return value

    @router.post("/api/admin/branding/assets")
    async def upload_branding(file: UploadFile = File(...), user=Depends(current_admin)):
        content = await file.read(2 * 1024 * 1024 + 1)
        value = branding.save_asset(content)
        admin_catalog.audit(user, "branding.upload", [value["url"]])
        return value

    @router.get("/api/admin/overview")
    async def get_overview(user=Depends(current_admin)):
        return admin.overview()

    @router.get("/api/admin/audit")
    async def get_audit(start: str | None = None, end: str | None = None, user=Depends(current_admin)):
        return admin_catalog.all_audit(start, end)

    @router.get("/api/admin/users")
    async def get_users(user=Depends(current_admin)):
        return admin.users()

    @router.post("/api/admin/users")
    async def create_user(request: Request, user=Depends(current_admin)):
        value = admin.create_user(await request.json())
        admin_catalog.audit(user, "users.create", [value["id"]])
        return value

    @router.post("/api/admin/users/batch")
    async def batch_users(request: Request, user=Depends(current_admin)):
        ids, action, changes = admin_catalog.validate_batch(await request.json())
        result = await admin.change_users(user, ids, action, changes)
        admin_catalog.audit(user, "users." + action, ids)
        return result

    @router.patch("/api/admin/users/{id_}")
    async def patch_user(id_: str, request: Request, user=Depends(current_admin)):
        result = await admin.change_users(user, [id_], "update", await request.json())
        admin_catalog.audit(user, "users.update", [id_])
        return next((item for item in admin.users() if item["id"] == id_), result)

    @router.delete("/api/admin/users/{id_}")
    async def delete_user(id_: str, user=Depends(current_admin)):
        result = await admin.change_users(user, [id_], "delete")
        admin_catalog.audit(user, "users.delete", [id_])
        return result

    @router.get("/api/admin/alerts")
    async def get_alerts(user=Depends(current_admin)):
        return admin.all_alerts()

    @router.post("/api/admin/alerts/batch")
    async def batch_alerts(request: Request, user=Depends(current_admin)):
        ids, action, changes = admin_catalog.validate_batch(await request.json())
        result = admin.update_alerts(ids, action, changes)
        admin_catalog.audit(user, "alerts." + action, ids)
        return result

    @router.patch("/api/admin/alerts/{id_}")
    async def patch_alert(id_: str, request: Request, user=Depends(current_admin)):
        admin.update_alerts([id_], "update", await request.json())
        admin_catalog.audit(user, "alerts.update", [id_])
        return next(item for item in admin.all_alerts() if item["id"] == id_)

    @router.delete("/api/admin/alerts/{id_}")
    async def delete_alert(id_: str, user=Depends(current_admin)):
        result = admin.update_alerts([id_], "delete", {})
        admin_catalog.audit(user, "alerts.delete", [id_])
        return result

    @router.post("/api/admin/defaults/agents/reorder")
    async def reorder_default_agents(request: Request, user=Depends(current_admin)):
        body = await request.json()
        ids = body.get("agent_ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not all(isinstance(id_, str) for id_ in ids) or len(ids) != len(set(ids)):
            raise ValueError("智能体排序必须为无重复的 ID 数组")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,data FROM default_templates WHERE kind='agents'").fetchall()
            if set(ids) != {row["id"] for row in rows}:
                raise ValueError("默认智能体列表已变化或包含无权限资源，请刷新后重新排序")
            values = {row["id"]: store.loads(row["data"], {}) for row in rows}
            stamp = store.now()
            changed = False
            for position, id_ in enumerate(ids):
                value = values[id_]
                if value.get("sort_order") != position:
                    value["sort_order"] = position
                    db.execute("UPDATE default_templates SET data=?,updated_at=? WHERE id=?", (store.dumps(value), stamp, id_))
                    changed = True
            if changed:
                defaults.sync_all(db)
        admin_catalog.audit(user, "defaults.agents.reorder", ids)
        return {"ok": True, "count": len(ids)}

    @router.get("/api/admin/defaults/{kind}")
    async def get_defaults(kind: str, user=Depends(current_admin)):
        if kind not in defaults.KINDS:
            raise HTTPException(404, "默认资源类型无效")
        with store.connect() as db:
            usage_counts = usage.counts(kind, db) if kind in usage.KINDS else None
            knowledge_counts = {row["template_id"]: {"document_count": row["n"], "chunk_count": row["chunks"]} for row in db.execute("SELECT template_id,count(*) n,coalesce(sum((length(content)+1149)/1150),0) chunks FROM template_documents GROUP BY template_id")} if kind == "knowledge" else None
        return [public_template(kind, item, knowledge_counts, usage_counts) for item in defaults.list_templates(kind)]

    @router.post("/api/admin/defaults/{kind}/batch")
    async def batch_defaults(kind: str, request: Request, user=Depends(current_admin)):
        ids, action, changes = admin_catalog.validate_batch(await request.json())
        return apply(kind, ids, action, changes, user)

    @router.post("/api/admin/defaults/{kind}/import")
    async def import_defaults(kind: str, request: Request, user=Depends(current_admin)):
        body = await request.json()
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 200 or not all(isinstance(item, dict) for item in items):
            raise ValueError("批量导入需为1–200个资源对象")
        values = [validate(kind, item, user) for item in items]
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = [defaults.save(kind, value, db=db) for value in values]
            defaults.sync_all(db)
        admin_catalog.audit(user, f"defaults.{kind}.import", [item["id"] for item in result])
        if kind == "providers":
            result = [await provider_sync.sync(user["id"], item, template=True, first=True) for item in result]
        warnings = [item["model_sync"]["message"] for item in result if item.get("model_sync", {}).get("status") not in {None, "ok"}]
        return {"ok": True, "count": len(result), **({"warnings": warnings} if warnings else {})}

    @router.post("/api/admin/defaults/{kind}")
    async def create_default(kind: str, request: Request, user=Depends(current_admin)):
        value = defaults.save(kind, validate(kind, await request.json(), user))
        admin_catalog.audit(user, f"defaults.{kind}.create", [value["id"]])
        if kind == "providers":
            value = await provider_sync.sync(user["id"], value, template=True, first=True)
        return public_template(kind, value)

    @router.post("/api/admin/defaults/providers/{id_}/sync-models")
    async def sync_default_models(id_: str, user=Depends(current_admin)):
        provider = admin_catalog.ensure_template("providers", id_)
        defaults.assert_not_running([id_])
        return public_template("providers", await provider_sync.sync(user["id"], provider, template=True))

    @router.get("/api/admin/defaults/{kind}/{id_}")
    async def get_default(kind: str, id_: str, user=Depends(current_admin)):
        return public_template(kind, admin_catalog.ensure_template(kind, id_))

    @router.patch("/api/admin/defaults/{kind}/{id_}")
    async def patch_default(kind: str, id_: str, request: Request, user=Depends(current_admin)):
        apply(kind, [id_], "update", await request.json(), user)
        return public_template(kind, defaults.get_template(kind, id_))

    @router.delete("/api/admin/defaults/{kind}/{id_}")
    async def delete_default(kind: str, id_: str, user=Depends(current_admin)):
        return apply(kind, [id_], "delete", {}, user)

    @router.get("/api/admin/defaults/knowledge/{id_}/documents")
    async def get_documents(id_: str, user=Depends(current_admin)):
        admin_catalog.ensure_template("knowledge", id_)
        return admin_catalog.document_details(id_)

    async def write_document(id_, request, user, doc_id=None):
        admin_catalog.ensure_template("knowledge", id_)
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {"name", "content"}:
            raise ValueError("文档字段仅支持名称与内容")
        name, content = body.get("name"), body.get("content")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200 or not isinstance(content, str) or not 1 <= len(content.strip()) <= 2_000_000:
            raise ValueError("请填写有效文档名称与正文")
        result = admin_catalog.save_document(id_, name.strip(), content, doc_id)
        admin_catalog.audit(user, "documents.save", [id_, result["id"]])
        return result

    @router.post("/api/admin/defaults/knowledge/{id_}/documents")
    async def create_document(id_: str, request: Request, user=Depends(current_admin)):
        return await write_document(id_, request, user)

    @router.patch("/api/admin/defaults/knowledge/{id_}/documents/{doc_id}")
    async def patch_document(id_: str, doc_id: str, request: Request, user=Depends(current_admin)):
        return await write_document(id_, request, user, doc_id)

    @router.post("/api/admin/defaults/knowledge/{id_}/documents/batch")
    async def batch_documents(id_: str, request: Request, user=Depends(current_admin)):
        admin_catalog.ensure_template("knowledge", id_)
        ids, action, changes = admin_catalog.validate_batch(await request.json())
        if action != "delete":
            raise ValueError("文档批量操作仅支持删除")
        result = admin_catalog.delete_documents(id_, ids)
        admin_catalog.audit(user, "documents.delete", ids)
        return result

    @router.delete("/api/admin/defaults/knowledge/{id_}/documents/{doc_id}")
    async def delete_document(id_: str, doc_id: str, user=Depends(current_admin)):
        admin_catalog.ensure_template("knowledge", id_)
        result = admin_catalog.delete_documents(id_, [doc_id])
        admin_catalog.audit(user, "documents.delete", [doc_id])
        return result

    return router
