import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest

from backend import presets, store


ADDITIONS = {"agents": 50, "skills": 50, "knowledge": 50, "documents": 100}
NO_ADDITIONS = dict.fromkeys(ADDITIONS, 0)


@pytest.fixture
def users(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "presets.db")
    store.init_db()
    owners = (store.uid(), store.uid())
    with store.connect() as db:
        for owner in owners:
            db.execute("INSERT INTO users(id,email,password,data,created_at) VALUES (?,?,?,?,?)", (
                owner, f"{owner}@presets.example", "unused-test-password", store.dumps({"name": "预置测试用户"}), store.now(),
            ))
    return owners


def test_inventory_and_substantive_indexed_documents(users):
    owner, _ = users
    uploads_before = set(store.UPLOADS.iterdir())
    assert presets.install_user_presets(owner) == ADDITIONS
    assert set(store.UPLOADS.iterdir()) == uploads_before
    assert len(presets.PRESETS) == 50
    for kind in ("agents", "skills", "knowledge"):
        values = store.list_entities(owner, kind)
        assert len(values) == 50
        assert len({item["builtin_key"] for item in values}) == 50
        assert {item["builtin_domain"] for item in values} == {item["key"] for item in presets.PRESETS}
        assert all(item["builtin_version"] == presets.PRESET_VERSION for item in values)
    skills = store.list_entities(owner, "skills")
    assert len({item["content"] for item in skills}) == 50
    assert all(len(item["content"]) >= 180 and item["enabled"] for item in skills)
    agents = store.list_entities(owner, "agents")
    assert {item["control_level"] for item in agents} == {"observe", "approve"}
    assert all("后台审批" in item["system_prompt"] for item in agents)
    knowledge = {item["builtin_domain"]: item for item in store.list_entities(owner, "knowledge")}
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM documents WHERE owner=?", (owner,)).fetchone()[0] == 100
        for preset in presets.PRESETS:
            kb = knowledge[preset["key"]]
            rows = db.execute("SELECT * FROM documents WHERE owner=? AND knowledge_id=?", (owner, kb["id"])).fetchall()
            assert len(rows) == len(kb["builtin_documents"]) == 2
            metadata = {item["name"]: item for item in kb["builtin_documents"]}
            sources = {item["name"]: item for item in preset["documents"]}
            for document in rows:
                source = sources[document["name"]]
                assert len(source["content"]) >= 900
                assert all(term in source["content"] for term in ("1.", "2.", "证据", "风险", "审批", "验证"))
                expected = f"# {source['name'].removesuffix('.md')}\n\n{presets.REFERENCE_NOTICE}{source['content']}"
                chunks = db.execute(
                    "SELECT content FROM chunks WHERE owner=? AND knowledge_id=? AND document_id=? ORDER BY rowid",
                    (owner, kb["id"], document["id"]),
                ).fetchall()
                assert [row["content"] for row in chunks] == [
                    expected[index:index + 1400] for index in range(0, len(expected), 1150)
                ]
                assert len(chunks) == document["chunk_count"] == metadata[document["name"]]["chunk_count"]
                assert document["size"] == len(expected.encode("utf-8")) == metadata[document["name"]]["size"]
                assert document["id"] == metadata[document["name"]]["id"]
                assert metadata[document["name"]]["builtin_key"] == f"earthai.documents.{preset['key']}.{source['key']}"
                assert metadata[document["name"]]["mime"] == "text/markdown"
                assert document["created_at"] == metadata[document["name"]]["created_at"]


@pytest.mark.parametrize(("domain", "query"), [
    ("k8s-health", "NotReady"),
    ("pod-troubleshooting", "CrashLoopBackOff"),
    ("linux-resources", "vmstat"),
    ("network-dns", "NXDOMAIN"),
    ("release-rollback", "ProgressDeadlineExceeded"),
    ("capacity-cost", "millicore"),
    ("security-rbac", "Unauthorized"),
    ("storage-backup", "Multi-Attach"),
    ("observability-alerts", "histogram"),
    ("incident-response", "RPO"),
])
def test_real_knowledge_retrieval_for_every_domain(users, domain, query):
    owner, _ = users
    presets.install_user_presets(owner)
    kb = next(item for item in store.list_entities(owner, "knowledge") if item["builtin_domain"] == domain)
    results = store.search_knowledge(owner, query, [kb["id"]])
    assert results
    assert all(item["knowledge_id"] == kb["id"] and item["content"] for item in results)


@pytest.mark.parametrize("preset", presets.PRESETS, ids=lambda preset: preset["key"])
def test_each_domain_has_real_searchable_manual_content(users, preset):
    owner, _ = users
    presets.install_user_presets(owner)
    kb = next(item for item in store.list_entities(owner, "knowledge") if item["builtin_domain"] == preset["key"])
    query = preset["documents"][0]["name"].removesuffix(".md")
    results = store.search_knowledge(owner, query, [kb["id"]])
    assert results and all(item["knowledge_id"] == kb["id"] for item in results)
    assert any(query in item["content"] for item in results)


def test_fts_match_and_chinese_substring_search(users):
    owner, _ = users
    presets.install_user_presets(owner)
    knowledge = {item["builtin_domain"]: item for item in store.list_entities(owner, "knowledge")}
    with store.connect() as db:
        rows = db.execute(
            "SELECT content FROM chunks WHERE chunks MATCH ? AND owner=? AND knowledge_id=?",
            ('"CrashLoopBackOff"', owner, knowledge["pod-troubleshooting"]["id"]),
        ).fetchall()
    assert rows and any("退避" in row["content"] for row in rows)
    results = store.search_knowledge(owner, "不可逆", [knowledge["release-rollback"]["id"]])
    assert results and all("不可逆" in item["content"] for item in results)
    assert store.search_knowledge(owner, "不可逆", [knowledge["network-dns"]["id"]]) == []


def test_agents_link_matching_domains_and_owner_isolation(users):
    owner, other = users
    assert presets.install_user_presets(owner) == ADDITIONS
    assert presets.install_user_presets(other) == ADDITIONS
    ids_by_owner = []
    for user in users:
        ids = set()
        for kind in ("agents", "skills", "knowledge"):
            ids.update(item["id"] for item in store.list_entities(user, kind))
        ids_by_owner.append(ids)
        for agent in store.list_entities(user, "agents"):
            assert len(agent["skill_ids"]) == len(agent["knowledge_ids"]) == 1
            for field, kind in (("skill_ids", "skills"), ("knowledge_ids", "knowledge")):
                linked = store.get_entity(user, kind, agent[field][0])
                assert linked and linked["builtin_domain"] == agent["builtin_domain"]
                assert store.get_entity(other if user == owner else owner, kind, linked["id"]) is None
    assert not (ids_by_owner[0] & ids_by_owner[1])
    other_knowledge_ids = [item["id"] for item in store.list_entities(other, "knowledge")]
    assert store.search_knowledge(owner, "CrashLoopBackOff", other_knowledge_ids) == []
    with store.connect() as db:
        assert db.execute("""SELECT count(*) FROM documents d JOIN entities e ON d.knowledge_id=e.id
            WHERE d.owner<>e.owner OR e.kind<>'knowledge'""").fetchone()[0] == 0
        assert db.execute("""SELECT count(*) FROM chunks c JOIN documents d ON c.document_id=d.id
            WHERE c.owner<>d.owner OR c.knowledge_id<>d.knowledge_id""").fetchone()[0] == 0
        for user in users:
            assert db.execute("SELECT count(*) FROM documents WHERE owner=?", (user,)).fetchone()[0] == 100


def test_repeat_install_is_exact_noop(users):
    owner, _ = users
    assert presets.install_user_presets(owner) == ADDITIONS
    with store.connect() as db:
        before = {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                  for table in ("entities", "documents", "chunks", "preset_installations")}
    assert presets.install_user_presets(owner) == NO_ADDITIONS
    assert presets.install_user_presets(owner) == NO_ADDITIONS
    with store.connect() as db:
        after = {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                 for table in before}
    assert after == before
    assert len(after["preset_installations"]) == 1


def test_deleted_entities_and_documents_do_not_resurrect(users):
    owner, _ = users
    presets.install_user_presets(owner)
    for kind in ("agents", "skills"):
        store.delete_entity(owner, kind, store.list_entities(owner, kind)[0]["id"])
    knowledge_id = store.list_entities(owner, "knowledge")[0]["id"]
    with store.connect() as db:
        db.execute("DELETE FROM chunks WHERE owner=? AND knowledge_id=?", (owner, knowledge_id))
        db.execute("DELETE FROM documents WHERE owner=? AND knowledge_id=?", (owner, knowledge_id))
    store.delete_entity(owner, "knowledge", knowledge_id)
    with store.connect() as db:
        document_id = db.execute("SELECT id FROM documents WHERE owner=? LIMIT 1", (owner,)).fetchone()[0]
        db.execute("DELETE FROM chunks WHERE owner=? AND document_id=?", (owner, document_id))
        db.execute("DELETE FROM documents WHERE owner=? AND id=?", (owner, document_id))
        chunk_count = db.execute("SELECT count(*) FROM chunks WHERE owner=?", (owner,)).fetchone()[0]
    assert presets.install_user_presets(owner) == NO_ADDITIONS
    for kind in ("agents", "skills", "knowledge"):
        assert len(store.list_entities(owner, kind)) == 49
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM documents WHERE owner=?", (owner,)).fetchone()[0] == 97
        assert db.execute("SELECT count(*) FROM chunks WHERE owner=?", (owner,)).fetchone()[0] == chunk_count
        assert db.execute("SELECT 1 FROM documents WHERE id=?", (document_id,)).fetchone() is None


def test_existing_names_edits_and_seeded_sre_are_not_overwritten(users):
    owner, _ = users
    preset = presets.PRESETS[0]
    old_skill = store.save_entity(owner, "skills", {
        "name": preset["skill_name"], "description": "我的说明", "content": "用户修订的巡检流程", "enabled": False,
    })
    store.save_entity(owner, "skills", {
        "name": preset["skill_name"] + "（EarthAI 内置）", "content": "另一个用户同名流程", "enabled": True,
    })
    store.save_entity(owner, "agents", {
        "name": "Earth SRE", "system_prompt": "保留我的系统提示", "skill_ids": [old_skill["id"]],
        "knowledge_ids": [], "control_level": "approve",
    })
    store.save_entity(owner, "agents", {
        "name": preset["agent_name"], "system_prompt": "我的专员", "skill_ids": [], "knowledge_ids": [], "control_level": "observe",
    })
    kb = store.save_entity(owner, "knowledge", {"name": preset["knowledge_name"], "description": "用户自己的知识库"})
    document_id = store.uid()
    with store.connect() as db:
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", (document_id, owner, kb["id"], "我的文档.md", 99, 1, store.now()))
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (store.uid(), owner, kb["id"], document_id, "我的文档.md", "私人知识内容"))
        before = [tuple(row) for row in db.execute("SELECT * FROM entities WHERE owner=? ORDER BY id", (owner,))]
    assert presets.install_user_presets(owner) == ADDITIONS
    with store.connect() as db:
        for row in before:
            assert tuple(db.execute("SELECT * FROM entities WHERE id=?", (row[0],)).fetchone()) == row
        assert db.execute("SELECT count(*) FROM documents WHERE knowledge_id=?", (kb["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT content FROM chunks WHERE document_id=?", (document_id,)).fetchone()[0] == "私人知识内容"
    builtin_skill = next(item for item in store.list_entities(owner, "skills") if item.get("builtin_domain") == preset["key"])
    assert builtin_skill["name"] == preset["skill_name"] + "（EarthAI 内置 2）"
    builtin_agent = next(item for item in store.list_entities(owner, "agents") if item.get("builtin_domain") == preset["key"])
    assert builtin_agent["skill_ids"] == [builtin_skill["id"]]
    assert builtin_agent["knowledge_ids"] != [kb["id"]]
    assert builtin_agent["name"] == preset["agent_name"] + "（EarthAI 内置）"


def test_future_version_can_append_without_rewriting_edited_builtins(users, monkeypatch):
    owner, _ = users
    presets.install_user_presets(owner)
    edited = store.list_entities(owner, "skills")[0]
    edited.update(name="我的重命名技能", content="用户重新编写", enabled=False)
    store.save_entity(owner, "skills", edited, edited["id"])
    kb = store.list_entities(owner, "knowledge")[0]
    kb.update(name="我的重命名知识库", description="我的说明")
    store.save_entity(owner, "knowledge", kb, kb["id"])
    with store.connect() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM entities WHERE owner=? ORDER BY id", (owner,))]
        old_documents = [tuple(row) for row in db.execute("SELECT * FROM documents WHERE owner=? ORDER BY id", (owner,))]
    monkeypatch.setattr(presets, "PRESET_VERSION", "future-test-version")
    appended = {
        **presets.PRESETS[0], "key": "future-test-domain", "knowledge_name": "将来新增知识库",
        "skill_name": "将来新增技能", "agent_name": "将来新增专员",
    }
    monkeypatch.setattr(presets, "PRESETS", (*presets.PRESETS, appended))
    assert presets.install_user_presets(owner) == {"agents": 1, "skills": 1, "knowledge": 1, "documents": 2}
    assert presets.install_user_presets(owner) == NO_ADDITIONS
    with store.connect() as db:
        for row in before:
            assert tuple(db.execute("SELECT * FROM entities WHERE id=?", (row[0],)).fetchone()) == row
        for row in old_documents:
            assert tuple(db.execute("SELECT * FROM documents WHERE id=?", (row[0],)).fetchone()) == row
        assert db.execute("SELECT count(*) FROM preset_installations WHERE owner=?", (owner,)).fetchone()[0] == 2


@pytest.mark.parametrize("table", ["documents", "preset_installations"])
def test_failed_transaction_rolls_back_everything_and_can_retry(users, table):
    owner, other = users
    presets.install_user_presets(other)
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_preset BEFORE INSERT ON {table}
            WHEN NEW.owner='{owner}' BEGIN SELECT RAISE(ABORT, 'forced preset failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced preset failure"):
        presets.install_user_presets(owner)
    with store.connect() as db:
        for name in ("entities", "documents", "chunks", "preset_installations"):
            assert db.execute(f"SELECT count(*) FROM {name} WHERE owner=?", (owner,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM entities WHERE owner=?", (other,)).fetchone()[0] == 150
        db.execute("DROP TRIGGER reject_preset")
    assert presets.install_user_presets(owner) == ADDITIONS
    assert store.search_knowledge(owner, "CrashLoopBackOff")


def test_unknown_owner_foreign_key_failure_is_not_swallowed(users):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        presets.install_user_presets("missing-user")
    with store.connect() as db:
        for table in ("entities", "documents", "chunks"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='preset_installations'").fetchone()
        if exists:
            assert db.execute("SELECT count(*) FROM preset_installations").fetchone()[0] == 0


def test_concurrent_install_is_atomic_and_idempotent(users):
    owner, _ = users
    ready = Barrier(4)

    def install(_):
        ready.wait(timeout=10)
        return presets.install_user_presets(owner)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(install, range(4)))
    assert results.count(ADDITIONS) == 1
    assert results.count(NO_ADDITIONS) == 3
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM preset_installations WHERE owner=?", (owner,)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM entities WHERE owner=?", (owner,)).fetchone()[0] == 150
        assert db.execute("SELECT count(*) FROM documents WHERE owner=?", (owner,)).fetchone()[0] == 100


def test_install_all_counts_visited_users_and_never_reads_passwords(users, monkeypatch):
    owner, other = users
    presets.install_user_presets(owner)
    original_connect = store.connect

    def authorizer(action, table, column, database, source):
        if action == sqlite3.SQLITE_READ and table == "users" and column == "password":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @contextmanager
    def guarded_connect():
        with original_connect() as db:
            db.set_authorizer(authorizer)
            yield db

    monkeypatch.setattr(store, "connect", guarded_connect)
    assert presets.install_all_user_presets() == {"users": 2, **ADDITIONS}
    assert presets.install_all_user_presets() == {"users": 2, **NO_ADDITIONS}
    assert len(store.list_entities(other, "agents")) == 50


def test_install_all_handles_empty_user_table(users):
    with store.connect() as db:
        db.execute("DELETE FROM users")
    assert presets.install_all_user_presets() == {"users": 0, **NO_ADDITIONS}


def test_defaults_and_personal_resources_remain_editable(users):
    from fastapi.testclient import TestClient

    from backend import defaults
    from backend.main import app

    owner, _ = users
    presets.install_user_presets(owner)
    with TestClient(app) as client:
        client.cookies.set("earthai_session", store.new_session(owner))
        kb = next(item for item in client.get("/api/knowledge").json() if item.get("default_template_id"))
        assert kb["read_only"] is False
        assert 3 <= kb["document_count"] <= 12 and kb["chunk_count"] >= kb["document_count"]
        docs = client.get(f"/api/knowledge/{kb['id']}/documents").json()
        assert len(docs) == kb["document_count"] and all(item["size"] > 0 and item["chunk_count"] > 0 for item in docs)
        text = client.get(f"/api/knowledge/{kb['id']}/documents/{docs[0]['id']}")
        assert text.status_code == 200 and len(text.json()["text"]) > 900
        assert client.delete(f"/api/knowledge/{kb['id']}/documents/{docs[0]['id']}").status_code == 200
        uploaded = client.post(f"/api/knowledge/{kb['id']}/documents", files={
            "file": ("personal.md", b"personalpresetdocumenttoken evidence", "text/markdown"),
        })
        assert uploaded.status_code == 200, uploaded.text
        assert client.get(f"/api/knowledge/{kb['id']}/documents/{uploaded.json()['id']}").json()["text"] == "personalpresetdocumenttoken evidence"
        assert store.search_knowledge(owner, "personalpresetdocumenttoken", [kb["id"]])
        for kind in ("agents", "skills", "knowledge"):
            item = kb if kind == "knowledge" else next(
                value for value in client.get(f"/api/{kind}").json() if value.get("default_template_id")
            )
            assert item["read_only"] is False
            template_before = defaults.get_template(kind, item["default_template_id"])
            changed = client.patch(f"/api/{kind}/{item['id']}", json={"description": "我的默认副本更新"})
            assert changed.status_code == 200, changed.text
            assert changed.json()["description"] == "我的默认副本更新" and changed.json()["read_only"] is False
            assert changed.json()["id"] == item["id"] and changed.json()["default_template_id"] == item["default_template_id"]
            assert defaults.get_template(kind, item["default_template_id"]) == template_before
            assert client.delete(f"/api/{kind}/{item['id']}").status_code == 200
            assert store.get_entity(owner, kind, item["id"]) is None
            payload = {"name": "个人" + kind, "description": "我的配置"}
            if kind == "agents":
                payload["system_prompt"] = "先取证再分析"
            if kind == "skills":
                payload["content"] = "我的排查步骤"
            personal = client.post(f"/api/{kind}", json=payload)
            assert personal.status_code == 200, personal.text
            id_ = personal.json()["id"]
            assert not personal.json()["read_only"] and not personal.json().get("default_template_id")
            assert client.patch(f"/api/{kind}/{id_}", json={"description": "个人更新"}).status_code == 200
            assert client.delete(f"/api/{kind}/{id_}").status_code == 200
        defaults.sync_user(owner)
        for kind in ("agents", "skills", "knowledge"):
            inherited = [item for item in client.get(f"/api/{kind}").json() if item.get("default_template_id")]
            assert len(inherited) == (99 if kind == "skills" else 49) and all(item["read_only"] is False for item in inherited)
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM documents WHERE owner=? AND knowledge_id=?", (owner, kb["id"])).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM chunks WHERE owner=? AND knowledge_id=?", (owner, kb["id"])).fetchone()[0] == 0
