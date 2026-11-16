from __future__ import annotations

from . import store

KINDS = {"agents", "knowledge", "skills"}


def initialize():
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS resource_usage (
            owner TEXT NOT NULL, run_id TEXT NOT NULL, kind TEXT NOT NULL,
            resource_id TEXT NOT NULL, template_id TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY(run_id,kind,resource_id)
        );
        CREATE INDEX IF NOT EXISTS idx_usage_template ON resource_usage(kind,template_id);
        CREATE INDEX IF NOT EXISTS idx_usage_owner ON resource_usage(owner);
        CREATE TABLE IF NOT EXISTS remote_agent_clicks (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, resource_id TEXT NOT NULL,
            template_id TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_remote_clicks_template ON remote_agent_clicks(template_id);
        CREATE INDEX IF NOT EXISTS idx_remote_clicks_owner ON remote_agent_clicks(owner);
        """)
        db.execute("INSERT OR IGNORE INTO platform_settings VALUES (?,?,?)", ("usage_started_at", store.dumps(store.now()), store.now()))


def record(owner, run_id, resources):
    values = {(kind, resource["id"]): resource for kind, resource in resources if kind in KINDS and resource and resource.get("id")}
    if not values:
        return
    with store.connect() as db:
        stamp = store.now()
        db.executemany("INSERT OR IGNORE INTO resource_usage VALUES (?,?,?,?,?,?)", [(owner, run_id, kind, id_, resource.get("default_template_id"), stamp) for (kind, id_), resource in values.items()])


def record_remote_open(owner, agent):
    with store.connect() as db:
        db.execute("INSERT INTO remote_agent_clicks VALUES (?,?,?,?,?)", (store.uid(), owner, agent["id"], agent.get("default_template_id"), store.now()))


def record_knowledge(owner, run_id, results):
    ids = list(dict.fromkeys(item["knowledge_id"] for item in results if isinstance(item, dict) and item.get("knowledge_id")))
    if not ids:
        return
    with store.connect() as db:
        rows = db.execute("SELECT * FROM entities WHERE owner=? AND kind='knowledge' AND id IN (" + ",".join("?" for _ in ids) + ")", (owner, *ids)).fetchall()
    record(owner, run_id, [("knowledge", store.entity(row)) for row in rows])


def counts(kind, db=None):
    if db is None:
        with store.connect() as connection:
            return counts(kind, connection)
    totals = {row["template_id"]: row["calls"] for row in db.execute("SELECT template_id,count(*) calls FROM resource_usage WHERE kind=? AND template_id IS NOT NULL GROUP BY template_id", (kind,))}
    if kind == "agents":
        for row in db.execute("SELECT template_id,count(*) calls FROM remote_agent_clicks WHERE template_id IS NOT NULL GROUP BY template_id"):
            totals[row["template_id"]] = totals.get(row["template_id"], 0) + row["calls"]
    return totals


def resource_counts(owner, kind):
    with store.connect() as db:
        totals = {row["resource_id"]: row["calls"] for row in db.execute("SELECT resource_id,count(*) calls FROM resource_usage WHERE owner=? AND kind=? GROUP BY resource_id", (owner, kind))}
        if kind == "agents":
            for row in db.execute("SELECT resource_id,count(*) calls FROM remote_agent_clicks WHERE owner=? GROUP BY resource_id", (owner,)):
                totals[row["resource_id"]] = totals.get(row["resource_id"], 0) + row["calls"]
    return totals


def summary(db=None):
    if db is None:
        with store.connect() as connection:
            return summary(connection)
    totals = dict.fromkeys(sorted(KINDS), 0)
    for row in db.execute("SELECT kind,count(*) calls FROM resource_usage GROUP BY kind"):
        totals[row["kind"]] = row["calls"]
    totals["agents"] += db.execute("SELECT count(*) FROM remote_agent_clicks").fetchone()[0]
    row = db.execute("SELECT value FROM platform_settings WHERE key='usage_started_at'").fetchone()
    return {"totals": totals, "started_at": store.loads(row["value"]) if row else None, "scope": "all_resources", "method": "per_run_resource_and_remote_click", "description": "统计所有用户的默认与自建资源；本地智能体、已注入技能和命中知识库在同一任务内对同一资源只计一次，远程智能体每次打开单独计一次。默认资源卡片汇总其用户副本；页面浏览和手动知识检索不计调用。"}
