from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from . import access, store

AUDIENCES = {"admin", "user"}
ICONS = {"Activity", "ArrowUpRight", "Bell", "Blocks", "BookOpen", "Bot", "CalendarClock", "FileText", "FolderKanban", "HardDrive", "KeyRound", "LifeBuoy", "MessageSquare", "Palette", "Server", "Settings", "ShieldCheck", "Sparkles", "Users"}


def audience(value):
    if value not in AUDIENCES:
        raise ValueError("指南受众必须为 admin 或 user")
    return value


def initialize():
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS help_guides (id TEXT NOT NULL, audience TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(audience,id))")
        if db.execute("SELECT 1 FROM platform_settings WHERE key='help_guides_v1'").fetchone():
            return
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM platform_settings WHERE key='help_guides_v1'").fetchone():
            return
        presets = json.loads((Path(__file__).parent / "guide_presets.json").read_text())
        stamp = store.now()
        for role, values in presets.items():
            for value in values:
                id_ = value["id"]
                data = {key: item for key, item in value.items() if key != "id"}
                db.execute("INSERT OR IGNORE INTO help_guides VALUES (?,?,?,?,?)", (id_, role, store.dumps(data), stamp, stamp))
        db.execute("INSERT INTO platform_settings VALUES (?,?,?)", ("help_guides_v1", "true", stamp))


def from_row(row):
    return {**store.loads(row["data"], {}), "id": row["id"], "audience": row["audience"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def entries(role):
    audience(role)
    with store.connect() as db:
        values = [from_row(row) for row in db.execute("SELECT * FROM help_guides WHERE audience=?", (role,))]
    return sorted(values, key=lambda item: (item.get("sort_order", 0), item["created_at"], item["id"]))


def validate(body, current=None):
    allowed = {"id", "title", "summary", "content", "icon", "sort_order"}
    if not isinstance(body, dict) or set(body) - allowed or (current and "id" in body and body["id"] != current["id"]):
        raise ValueError("指南字段无效，已创建章节的地址标识不可更改")
    value = {"summary": "", "icon": "BookOpen", "sort_order": 0, **(current or {}), **body}
    if not isinstance(value.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,79}", value["id"]):
        raise ValueError("章节地址需为1–80位小写字母、数字和连字符，且以字母开头")
    for key, minimum, maximum in (("title", 1, 120), ("summary", 0, 1000), ("content", 1, 200000)):
        if not isinstance(value.get(key), str) or not minimum <= len(value[key].strip()) <= maximum:
            raise ValueError(f"{key} 需为{minimum}–{maximum}个字符")
        value[key] = value[key].strip()
    if not isinstance(value["icon"], str) or value["icon"] not in ICONS:
        raise ValueError("请选择内置指南图标")
    if type(value["sort_order"]) is not int or not 0 <= value["sort_order"] <= 100000:
        raise ValueError("章节排序需为0–100000的整数")
    return {key: value[key] for key in allowed}


def create_router(current_user, current_admin):
    router = APIRouter()

    def find(db, role, id_):
        row = db.execute("SELECT * FROM help_guides WHERE audience=? AND id=?", (audience(role), id_)).fetchone()
        if row is None:
            raise HTTPException(404, "指南章节不存在")
        return from_row(row)

    @router.get("/api/guides")
    async def read_guides(user=Depends(current_user)):
        return entries(access.role(user))

    @router.get("/api/admin/guides")
    async def manage_guides(audience: str = "admin", user=Depends(current_admin)):
        return entries(audience)

    @router.post("/api/admin/guides/{role}")
    async def create_guide(role: str, request: Request, user=Depends(current_admin)):
        audience(role)
        value = validate(await request.json())
        stamp = store.now()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM help_guides WHERE audience=? AND id=?", (role, value["id"])).fetchone():
                raise HTTPException(409, "该角色下章节地址已存在")
            data = {key: item for key, item in value.items() if key != "id"}
            db.execute("INSERT INTO help_guides VALUES (?,?,?,?,?)", (value["id"], role, store.dumps(data), stamp, stamp))
            saved = find(db, role, value["id"])
        store.audit(user["id"], "admin.guides.create", role + "/" + value["id"])
        return saved

    @router.patch("/api/admin/guides/{role}/{id_}")
    async def update_guide(role: str, id_: str, request: Request, user=Depends(current_admin)):
        body = await request.json()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = find(db, role, id_)
            value = validate(body, current)
            data = {key: item for key, item in value.items() if key != "id"}
            db.execute("UPDATE help_guides SET data=?,updated_at=? WHERE audience=? AND id=?", (store.dumps(data), store.now(), role, id_))
            saved = find(db, role, id_)
        store.audit(user["id"], "admin.guides.update", role + "/" + id_)
        return saved

    @router.delete("/api/admin/guides/{role}/{id_}")
    async def delete_guide(role: str, id_: str, user=Depends(current_admin)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            find(db, role, id_)
            db.execute("DELETE FROM help_guides WHERE audience=? AND id=?", (role, id_))
        store.audit(user["id"], "admin.guides.delete", role + "/" + id_)
        return {"ok": True}

    @router.post("/api/admin/guides/{role}/batch-delete")
    async def batch_delete(role: str, request: Request, user=Depends(current_admin)):
        audience(role)
        body = await request.json()
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or not all(isinstance(id_, str) for id_ in ids) or len(ids) != len(set(ids)):
            raise ValueError("请选择1–500个不重复章节")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for id_ in ids:
                find(db, role, id_)
            for id_ in ids:
                db.execute("DELETE FROM help_guides WHERE audience=? AND id=?", (role, id_))
        store.audit(user["id"], "admin.guides.batch_delete", role, store.dumps({"ids": ids}))
        return {"ok": True, "count": len(ids)}

    return router
