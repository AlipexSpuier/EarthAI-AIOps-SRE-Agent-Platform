from __future__ import annotations

import asyncio
import re

from fastapi import HTTPException

from . import access, defaults, engine, store, usage


def bootstrap_admin():
    with store.connect() as db:
        row = db.execute("SELECT id FROM users WHERE email='admin'").fetchone()
        if row:
            return
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users WHERE email='admin'").fetchone():
            return
        data = {"name": "系统管理员", "avatar": "AD", "theme": "light", "control_level": "observe", "allowed_control_levels": ["observe"], "role": "admin", "disabled": False, "must_change_password": True}
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (store.uid(), "admin", store.password_hash("admin"), store.dumps(data), store.now()))


def public_user(row):
    data = store.loads(row["data"], {})
    return {"id": row["id"], "email": row["email"], "created_at": row["created_at"], **data, "role": access.role(data), "disabled": bool(data.get("disabled")), "must_change_password": bool(data.get("must_change_password")), "allowed_control_levels": access.allowed_levels(data), "space_modules": access.enabled_spaces(data), "team_invites_blocked": bool(data.get("team_invites_blocked", False))}


def users():
    with store.connect() as db:
        return [public_user(row) for row in db.execute("SELECT id,email,data,created_at FROM users ORDER BY created_at,id")]


def validate_account(body, existing=None):
    allowed = {"email", "name", "password", "role", "disabled", "allowed_control_levels", "space_modules"}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError("用户字段仅支持账号、名称、密码、角色、停用状态、可用控制等级和可用空间")
    values = {**(existing or {}), **body}
    account = str(values.get("email", "")).strip().lower()
    if not 3 <= len(account) <= 254 or not re.fullmatch(r"[a-zA-Z0-9_.@+-]+", account):
        raise ValueError("账号需为3–254位邮箱或字母数字名称")
    if not str(values.get("name", "")).strip() or len(str(values["name"])) > 80:
        raise ValueError("显示名称需为1–80个字符")
    if values.get("role", "user") not in {"admin", "user"}:
        raise ValueError("角色必须为 user 或 admin")
    if "disabled" in body and not isinstance(body["disabled"], bool):
        raise ValueError("停用状态必须为布尔值")
    grants = access.validate_grants(body["allowed_control_levels"]) if "allowed_control_levels" in body else (
        access.allowed_levels(existing) if existing is not None else ["observe"]
    )
    spaces = access.validate_space_modules(body["space_modules"]) if "space_modules" in body else (
        access.enabled_spaces(existing) if existing is not None else ["personal"]
    )
    password = body.get("password", "")
    if (not existing or password) and (not isinstance(password, str) or not 8 <= len(password) <= 256):
        raise ValueError("新密码需为8–256个字符")
    return {"email": account, "name": str(values["name"]).strip(), "role": values.get("role", "user"),
        "disabled": values.get("disabled", False), "allowed_control_levels": grants, "space_modules": spaces}, password


def create_user(body):
    import sqlite3
    values, password = validate_account(body)
    id_ = store.uid()
    data = {"name": values["name"], "avatar": "U", "theme": "light", "control_level": access.preferred_control(values, "observe"),
        "allowed_control_levels": values["allowed_control_levels"], "space_modules": values["space_modules"], "team_invites_blocked": False,
        "role": values["role"], "disabled": values["disabled"], "must_change_password": False}
    try:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (id_, values["email"], store.password_hash(password), store.dumps(data), store.now()))
            defaults.sync_user(id_, db)
    except sqlite3.IntegrityError as exc:
        raise ValueError("账号已存在") from exc
    return next(user for user in users() if user["id"] == id_)


async def change_users(actor, ids, action, changes=None):
    if action not in {"update", "delete"}:
        raise ValueError("用户批量操作仅支持 update 或 delete")
    if not ids or len(ids) > 500 or len(ids) != len(set(ids)):
        raise ValueError("请选择1–500个无重复用户")
    cancellations = []
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        actor_row = db.execute("SELECT id,email,data FROM users WHERE id=?", (actor["id"],)).fetchone()
        if actor_row is None:
            raise HTTPException(403, "管理员身份已失效")
        actor = {**store.loads(actor_row["data"], {}), "id": actor_row["id"], "email": actor_row["email"]}
        access.require_admin(actor)
        if actor.get("must_change_password"):
            raise HTTPException(403, "首次登录必须修改初始密码")
        values = {row["id"]: public_user(row) for row in db.execute("SELECT id,email,data,created_at FROM users")}
        if set(ids) - values.keys():
            raise ValueError("所选用户已变化，请刷新")
        proposals = {id_: validate_account(changes or {}, values[id_]) for id_ in ids} if action == "update" else {}
        for id_ in ids:
            proposed = proposals.get(id_, ({}, ""))[0]
            if id_ == actor["id"] and (action == "delete" or proposed.get("role") != "admin" or proposed.get("disabled")):
                raise ValueError("不能删除、停用或降级当前登录管理员")
            if values[id_]["email"] == "admin" and (action == "delete" or proposed.get("email") != "admin" or proposed.get("role") != "admin" or proposed.get("disabled")):
                raise ValueError("初始 admin 管理员必须保留且不可停用或降级")
        active_admins = [user for user in values.values() if user["role"] == "admin" and not user["disabled"]]
        remaining = [user for user in active_admins if user["id"] not in ids or (action == "update" and proposals[user["id"]][0]["role"] == "admin" and not proposals[user["id"]][0]["disabled"])]
        if not remaining:
            raise ValueError("必须保留至少一个可用管理员")
        if action == "update":
            next_accounts = {id_: (proposals[id_][0]["email"] if id_ in proposals else value["email"]) for id_, value in values.items()}
            if len(set(next_accounts.values())) != len(next_accounts):
                raise ValueError("账号已存在，不能将多个用户改成同一账号")
        from . import teams
        teams.assert_account_changes(db, ids, action, changes or {})
        for id_ in ids:
            row = db.execute("SELECT data FROM users WHERE id=?", (id_,)).fetchone()
            data = store.loads(row["data"], {})
            if action == "delete":
                data["disabled"] = True
                db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), id_))
                db.execute("DELETE FROM sessions WHERE user_id=?", (id_,))
                restricted, tightened = True, False
            else:
                proposal, password = proposals[id_]
                tightened = bool(set(access.allowed_levels(data)) - set(proposal["allowed_control_levels"]))
                if changes and "space_modules" in changes:
                    if "team" in proposal["space_modules"]:
                        data["team_invites_blocked"] = False
                    elif "team" in access.enabled_spaces(data):
                        data["team_invites_blocked"] = True
                    data["space_modules"] = proposal["space_modules"]
                data.update({key: proposal[key] for key in ("name", "role", "disabled", "allowed_control_levels")})
                if proposal["allowed_control_levels"]:
                    data["control_level"] = access.preferred_control(data, data.get("control_level", "observe"))
                    if isinstance(data.get("chat_preferences"), dict):
                        preferences = dict(data["chat_preferences"])
                        preferences["control_level"] = access.preferred_control(data, preferences.get("control_level", data["control_level"]))
                        data["chat_preferences"] = preferences
                if password:
                    data["must_change_password"] = True
                    db.execute("UPDATE users SET password=? WHERE id=?", (store.password_hash(password), id_))
                db.execute("UPDATE users SET email=?,data=? WHERE id=?", (proposal["email"], store.dumps(data), id_))
                if password or proposal["disabled"] or proposal["role"] != values[id_]["role"]:
                    db.execute("DELETE FROM sessions WHERE user_id=?", (id_,))
                restricted = proposal["role"] == "admin" or proposal["disabled"] or bool(password)
                if proposal["role"] == "user":
                    defaults.sync_user(id_, db)
            levels = access.allowed_levels(data)
            for schedule in db.execute("SELECT id,data FROM entities WHERE owner=? AND kind='schedules'", (id_,)).fetchall():
                settings = store.loads(schedule["data"], {})
                if action == "delete" or access.role(data) == "admin" or settings.get("control_level", "observe") not in levels:
                    settings["enabled"] = False
                    db.execute("UPDATE entities SET data=?,updated_at=? WHERE id=? AND owner=?", (store.dumps(settings), store.now(), schedule["id"], id_))
            if restricted or tightened:
                active = db.execute("SELECT id,data FROM runs WHERE owner=? AND status IN ('queued','running','waiting_approval')", (id_,)).fetchall()
                for run in active:
                    run_data = store.loads(run["data"], {})
                    agent_row = db.execute("SELECT data FROM entities WHERE owner=? AND kind='agents' AND id=?", (id_, run_data.get("agent_id"))).fetchone()
                    agent = store.loads(agent_row["data"], {}) if agent_row else None
                    if restricted or run_data.get("control_level", "observe") not in levels or (agent is not None and agent.get("control_level", "observe") not in levels):
                        cancellations.append((id_, run["id"]))
    tasks = []
    for owner, run_id in cancellations:
        task = engine.TASKS.get(run_id)
        engine.cancel_run(owner, run_id)
        if task:
            tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    paths = []
    if action == "delete":
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for id_ in ids:
                paths.extend(store.UPLOADS / store.loads(row["data"], {}).get("storage_name", "") for row in db.execute("SELECT data FROM entities WHERE owner=? AND kind='files'", (id_,)))
                db.execute("DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE owner=?)", (id_,))
                for table in ("messages", "approvals", "runs", "chunks", "documents", "audit", "resource_usage", "remote_agent_clicks"):
                    db.execute(f"DELETE FROM {table} WHERE owner=?", (id_,))
                db.execute("DELETE FROM users WHERE id=?", (id_,))
    for path in paths:
        if path.is_file() and path.resolve().is_relative_to(store.UPLOADS.resolve()):
            path.unlink()
    return {"ok": True, "count": len(ids)}


def overview():
    with store.connect() as db:
        counts = {row["kind"]: row["total"] for row in db.execute("SELECT kind,count(*) total FROM default_templates GROUP BY kind")}
        counts["users"] = db.execute("SELECT count(*) FROM users").fetchone()[0]
        counts["admins"] = db.execute("SELECT count(*) FROM users WHERE json_extract(data,'$.role')='admin'").fetchone()[0]
        counts["alerts"] = db.execute("SELECT count(*) FROM entities WHERE kind='alerts'").fetchone()[0]
        counts["runs"] = db.execute("SELECT count(*) FROM runs").fetchone()[0]
        counts["active_runs"] = db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running','waiting_approval')").fetchone()[0]
        statistics = usage.summary(db)
    return {"counts": counts, "usage": statistics, "health": {"status": "ok", "database": "ok"}}


def all_alerts():
    with store.connect() as db:
        rows = db.execute("SELECT e.*,u.email FROM entities e JOIN users u ON u.id=e.owner WHERE e.kind='alerts' ORDER BY e.updated_at DESC").fetchall()
    return [{**store.entity(row), "owner_id": row["owner"], "owner_email": row["email"]} for row in rows]


def update_alerts(ids, action, changes):
    if action not in {"update", "delete"}:
        raise ValueError("告警批量操作仅支持 update 或 delete")
    values = {item["id"]: item for item in all_alerts()}
    if not ids or len(ids) != len(set(ids)) or set(ids) - values.keys() or len(ids) > 500:
        raise ValueError("请选择有效、无重复的告警")
    if not isinstance(changes, dict) or set(changes) - {"title", "description", "severity", "status"}:
        raise ValueError("只能更新告警标题、描述、严重度和状态")
    if "severity" in changes and changes["severity"] not in {"critical", "warning", "info"}:
        raise ValueError("严重度无效")
    if "status" in changes and changes["status"] not in {"open", "resolved"}:
        raise ValueError("告警状态无效")
    if any(not isinstance(value, str) or len(value) > 60000 for value in changes.values()):
        raise ValueError("告警字段必须为有效文本")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for id_ in ids:
            if action == "delete":
                db.execute("DELETE FROM entities WHERE id=? AND kind='alerts'", (id_,))
            else:
                item = values[id_]
                data = {key: value for key, value in item.items() if key not in {"id", "created_at", "updated_at", "owner_id", "owner_email"}}
                data.update(changes)
                if not data.get("title", "").strip():
                    raise HTTPException(422, "告警标题不能为空")
                db.execute("UPDATE entities SET data=?,updated_at=? WHERE id=? AND kind='alerts'", (store.dumps(data), store.now(), id_))
    return {"ok": True, "count": len(ids)}
