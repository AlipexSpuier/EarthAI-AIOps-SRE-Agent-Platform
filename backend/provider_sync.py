from __future__ import annotations

import httpx

from . import defaults, engine, store


async def discover(provider, *, first=False):
    try:
        result = await engine.provider_models(provider)
        models = list(dict.fromkeys(value.strip() for value in result if isinstance(value, str) and value.strip() and len(value.strip()) <= 250))[:200]
        if not models:
            return {"model_sync": {"status": "empty", "message": "供应商已保存，但接口未返回可用模型；请稍后同步或手动填写。", "count": 0, "synced_at": store.now()}}
        current = provider.get("default_model", "")
        return {"models": models, "default_model": models[0] if first or current not in models else current, "model_sync": {"status": "ok", "message": f"已同步 {len(models)} 个模型。", "count": len(models), "synced_at": store.now()}}
    except httpx.HTTPStatusError as exc:
        reason = f"模型目录接口返回 HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        reason = "模型目录接口请求超时"
    except httpx.RequestError:
        reason = "无法连接模型目录接口"
    except (ValueError, TypeError, KeyError):
        reason = "模型目录响应格式无效"
    return {"model_sync": {"status": "error", "message": f"供应商配置已保存，但自动同步失败：{reason}。可重试同步或手动填写模型。", "synced_at": store.now()}}


async def sync(owner, provider, *, template=False, first=False):
    changes = await discover(provider, first=first)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if template:
            row = db.execute("SELECT * FROM default_templates WHERE kind='providers' AND id=?", (provider["id"],)).fetchone()
            latest = defaults.template(row) if row else None
        else:
            row = db.execute("SELECT * FROM entities WHERE kind='providers' AND owner=? AND id=?", (owner, provider["id"])).fetchone()
            latest = store.entity(row)
        if latest is None or latest["updated_at"] != provider["updated_at"]:
            state = {"status": "stale", "message": "同步期间配置已变更或删除，未使用旧结果覆盖新配置。"}
            return {**(latest or provider), "model_sync": state}
        data = {key: value for key, value in latest.items() if key not in {"id", "created_at", "updated_at"}}
        data.update(changes)
        if template:
            value = defaults.save("providers", data, provider["id"], db)
            defaults.sync_all(db)
        else:
            stamp = store.now()
            db.execute("UPDATE entities SET data=?,updated_at=? WHERE owner=? AND kind='providers' AND id=?", (store.dumps(data), stamp, owner, provider["id"]))
            value = {**data, "id": provider["id"], "created_at": provider["created_at"], "updated_at": stamp}
    store.audit(owner, "provider.models.sync", provider["id"], changes["model_sync"]["status"])
    return value
