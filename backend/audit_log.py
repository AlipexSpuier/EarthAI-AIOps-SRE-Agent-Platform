from __future__ import annotations

from datetime import datetime, timezone

from . import store


def boundary(value, label):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label}必须为有效的 ISO 日期时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label}必须包含时区偏移")
    return parsed.astimezone(timezone.utc).isoformat()


def entries(owner, start=None, end=None, limit=100):
    start_at, end_at = boundary(start, "开始时间"), boundary(end, "结束时间")
    if start_at and end_at and end_at < start_at:
        raise ValueError("结束时间不能早于开始时间")
    if not 1 <= limit <= 100:
        raise ValueError("审计日志每次最多查询 100 条")
    clauses, params = ["owner=?"], [owner]
    if start_at:
        clauses.append("julianday(created_at)>=julianday(?)")
        params.append(start_at)
    if end_at:
        clauses.append("julianday(created_at)<=julianday(?)")
        params.append(end_at)
    with store.connect() as db:
        return [dict(row) for row in db.execute("SELECT id,action,resource,detail,created_at FROM audit WHERE " + " AND ".join(clauses) + " ORDER BY julianday(created_at) DESC,id DESC LIMIT ?", (*params, limit))]
