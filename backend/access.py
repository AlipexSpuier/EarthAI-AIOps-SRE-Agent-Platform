from __future__ import annotations

from fastapi import HTTPException

from . import store

CONTROL_LEVELS = ("observe", "approve", "autonomous")
SPACE_MODULES = ("personal", "team")


def validate_space_modules(value):
    if not isinstance(value, list) or any(not isinstance(module, str) or module not in SPACE_MODULES for module in value):
        raise ValueError("可用空间必须为 personal / team 的字符串数组")
    if len(value) != len(set(value)):
        raise ValueError("可用空间不能重复")
    return [module for module in SPACE_MODULES if module in value]


def enabled_spaces(user):
    if "space_modules" not in user:
        return ["personal"]
    try:
        return validate_space_modules(user["space_modules"])
    except ValueError:
        return []


def initialize_spaces():
    with store.connect() as db:
        if db.execute("SELECT 1 FROM platform_settings WHERE key='space_modules_v1'").fetchone():
            return
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM platform_settings WHERE key='space_modules_v1'").fetchone():
            return
        db.execute("UPDATE users SET data=json_set(data,'$.space_modules',json(?)) WHERE json_type(data,'$.space_modules') IS NULL", (store.dumps(["personal"]),))
        db.execute("INSERT INTO platform_settings VALUES (?,?,?)", ("space_modules_v1", "true", store.now()))


def require_space(user, module):
    active_user(user)
    if role(user) != "user" or user.get("must_change_password"):
        raise HTTPException(403, "此账号不能访问普通用户空间")
    if not isinstance(module, str) or module not in enabled_spaces(user):
        raise HTTPException(403, "管理员未启用此空间，请联系管理员")
    return user


def require_space_owner(owner, module):
    db = store.current_connection()
    if db is None:
        with store.connect() as db:
            row = db.execute("SELECT id,email,data FROM users WHERE id=?", (owner,)).fetchone()
    else:
        row = db.execute("SELECT id,email,data FROM users WHERE id=?", (owner,)).fetchone()
    if row is None:
        raise HTTPException(403, "账号不存在或没有空间访问权限")
    return require_space({**store.loads(row["data"], {}), "id": row["id"], "email": row["email"]}, module)


def validate_grants(value):
    if not isinstance(value, list) or not value or any(not isinstance(level, str) or level not in CONTROL_LEVELS for level in value):
        raise ValueError("可用控制等级必须为 observe / approve / autonomous 的非空字符串数组")
    if len(value) != len(set(value)):
        raise ValueError("可用控制等级不能重复")
    return [level for level in CONTROL_LEVELS if level in value]


def allowed_levels(user):
    if "allowed_control_levels" not in user:
        return list(CONTROL_LEVELS)
    try:
        return validate_grants(user["allowed_control_levels"])
    except ValueError:
        return []


def initialize_grants():
    with store.connect() as db:
        if db.execute("SELECT 1 FROM platform_settings WHERE key='control_grants_v1'").fetchone():
            return
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM platform_settings WHERE key='control_grants_v1'").fetchone():
            return
        db.execute("UPDATE users SET data=json_set(data,'$.allowed_control_levels',json(?)) WHERE json_type(data,'$.allowed_control_levels') IS NULL", (store.dumps(list(CONTROL_LEVELS)),))
        db.execute("INSERT INTO platform_settings VALUES (?,?,?)", ("control_grants_v1", "true", store.now()))


def require_control(user, level):
    active_user(user)
    if role(user) == "admin" or user.get("must_change_password"):
        raise HTTPException(403, "此账号不能执行运维任务")
    if not isinstance(level, str) or level not in allowed_levels(user):
        raise HTTPException(403, "管理员未授权此控制等级，请联系管理员")
    return user


def preferred_control(user, fallback="observe"):
    levels = allowed_levels(user)
    if fallback in levels:
        return fallback
    if "observe" in levels:
        return "observe"
    if levels:
        return levels[0]
    raise HTTPException(403, "账号没有可用控制等级，请联系管理员")


def role(user):
    return user.get("role", "user")


def active_user(user):
    if user.get("disabled"):
        raise HTTPException(403, "账号已停用，请联系管理员")
    return user


def require_admin(user):
    active_user(user)
    if role(user) != "admin":
        raise HTTPException(403, "仅管理员可访问此功能")
    return user


def read_only(kind, resource):
    if not resource.get("default_template_id"):
        return False
    return kind not in {"skills", "knowledge"} and not (
        kind == "agents" and resource.get("kind", "local") == "local"
    )


def writable(kind, resource):
    if read_only(kind, resource):
        raise HTTPException(403, "此系统默认资源仅可查看和使用，请联系管理员修改")
    return resource


def execution_allowed(owner, level=None):
    with store.connect() as db:
        row = db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()
    if row is None:
        raise ValueError("执行账号不存在")
    user = store.loads(row["data"], {})
    if role(user) == "admin" or user.get("disabled") or user.get("must_change_password"):
        raise ValueError("管理员、停用账号或尚未修改初始密码的账号不能执行运维任务")
    if level is not None:
        require_control(user, level)
