from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from collections import defaultdict, deque
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import access, defaults, engine, main, presets, store, tools

MARKER = "catalog_expansion_20261029_v1"
PASSWORD = "Legacy-Account-2026!"
ADMIN_PASSWORD = "Existing-Admin-2026!"
STAMP = "2024-02-03T04:05:06+00:00"
REQUIRED_TABLES = {
    "users", "sessions", "entities", "messages", "runs", "events", "approvals", "documents", "chunks", "audit",
    "agent_orders", "default_templates", "template_documents", "platform_settings", "default_owner_states",
    "default_sync_revisions", "help_guides", "resource_usage", "remote_agent_clicks", "team_spaces", "team_members", "team_files",
}
REQUIRED_INDEXES = {
    "idx_entities_owner_kind", "idx_entities_kind", "idx_messages_conversation", "idx_runs_owner", "idx_single_active_run",
    "idx_events_run", "idx_documents_owner_knowledge", "idx_documents_knowledge", "idx_template_documents_template",
    "idx_usage_template", "idx_usage_owner", "idx_remote_clicks_template", "idx_remote_clicks_owner",
    "idx_team_spaces_owner", "idx_team_members_owner", "idx_team_members_user", "idx_team_files_space", "idx_team_files_uploader",
}


@pytest.fixture
def legacy_database(monkeypatch, tmp_path):
    data = tmp_path / "legacy-schema"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    store.close_connections()
    store._cipher.cache_clear()
    monkeypatch.setattr(store, "DATA_ROOT", data)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "earthai.db")
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data))
    monkeypatch.setenv("EARTHAI_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.delenv("EARTHAI_STATE_DIR", raising=False)
    monkeypatch.delenv("EARTHAI_MASTER_KEY", raising=False)
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "scheduler_loop", idle_scheduler)
    blocked = (
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected paid model request"))),
        (engine, "provider_models", AsyncMock(side_effect=AssertionError("unexpected provider request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
        (tools, "ssh_connect", Mock(side_effect=AssertionError("unexpected SSH connection"))),
        (httpx.HTTPTransport, "handle_request", Mock(side_effect=AssertionError("unexpected network request"))),
        (httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("unexpected network request"))),
    )
    for target, name, replacement in blocked:
        monkeypatch.setattr(target, name, replacement)
    key = Fernet.generate_key()
    key_file = data / "master.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    result = _build_legacy_database(key)
    result.update(data=data, key=key, key_file=key_file)
    yield result
    store.close_connections()
    store._cipher.cache_clear()
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


def _build_legacy_database(key):
    db = sqlite3.connect(store.DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            data TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE default_templates (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL,
            builtin_key TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE template_documents (
            id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES default_templates(id) ON DELETE CASCADE,
            name TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
    users = {}
    for index, (control, preferred) in enumerate((("approve", "autonomous"), ("autonomous", "approve"))):
        id_ = f"legacy-user-{index}"
        data = {
            "name": f"升级前用户{index}", "avatar": "L", "theme": "light", "role": "user", "control_level": control,
            "chat_preferences": {
                "server_id": None, "provider_id": None, "model": "", "agent_id": None, "project_id": None,
                "control_level": preferred,
            },
        }
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (id_, f"legacy-{index}@example.test", store.password_hash(PASSWORD), store.dumps(data), STAMP))
        users[id_] = data
    restricted = {
        "name": "已配置授权用户", "role": "user", "allowed_control_levels": ["observe", "approve"], "control_level": "approve",
        "chat_preferences": {
            "server_id": None, "provider_id": None, "model": "", "agent_id": None, "project_id": None, "control_level": "approve",
        },
    }
    db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
        "restricted-user", "restricted@example.test", store.password_hash(PASSWORD), store.dumps(restricted), STAMP,
    ))
    admin = {
        "name": "原有管理员", "role": "admin", "control_level": "observe", "allowed_control_levels": ["observe"],
        "must_change_password": False, "disabled": False,
    }
    db.execute("INSERT INTO users VALUES (?,?,?,?,?)", ("legacy-admin", "admin", store.password_hash(ADMIN_PASSWORD), store.dumps(admin), STAMP))
    cipher = Fernet(key)
    secrets = {
        "server-password": "old-ssh-password-do-not-connect", "server-private-key": "old-private-key-do-not-connect",
        "server-kubeconfig": "old-kubeconfig-do-not-connect", "provider-api-key": "old-api-key-do-not-call",
    }
    encrypted = {name: cipher.encrypt(value.encode()).decode() for name, value in secrets.items()}
    private = {
        "legacy-server": ("servers", {
            "name": "原有服务器", "host": "192.0.2.19", "port": 22, "username": "offline",
            "auth_type": "password", "password": encrypted["server-password"], "private_key": encrypted["server-private-key"],
            "kubeconfig": encrypted["server-kubeconfig"], "status": "unknown",
        }),
        "legacy-provider": ("providers", {
            "name": "原有供应商", "base_url": "https://offline.example.invalid/v1", "api_key": encrypted["provider-api-key"],
            "models": ["offline-model"], "default_model": "offline-model", "enabled": False,
        }),
        "legacy-private-skill": ("skills", {"name": "原有私人技能", "content": "不得被新默认目录覆盖的个人正文", "enabled": False}),
    }
    for id_, (kind, value) in private.items():
        db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (id_, "legacy-user-0", kind, store.dumps(value), STAMP, STAMP))
    for position, preset in enumerate(presets.PRESETS):
        knowledge_id, skill_id, agent_id = [f"legacy-{kind}-{preset['key']}" for kind in ("knowledge", "skill", "agent")]
        resources = (
            (knowledge_id, "knowledge", {"name": preset["knowledge_name"], "description": preset["description"]}),
            (skill_id, "skills", {"name": preset["skill_name"], "description": preset["skill_description"], "content": preset["skill_content"], "enabled": True}),
            (agent_id, "agents", {
                "name": preset["agent_name"], "description": preset["agent_role"], "system_prompt": preset["agent_role"] + presets.AGENT_BOUNDARIES,
                "kind": "local", "url": "", "icon": "Bot", "color": preset["color"], "skill_ids": [skill_id],
                "knowledge_ids": [knowledge_id], "provider_id": None, "model": "", "control_level": preset["control_level"], "sort_order": position,
            }),
        )
        for id_, kind, value in resources:
            builtin_key = f"earthai.{kind}.{preset['key']}"
            value.update(builtin_domain=preset["key"], builtin_key=builtin_key, builtin_version=presets.PRESET_VERSION)
            if position == 1:
                if kind == "skills":
                    value.update(name="管理员早已修改的原技能", content="原有管理员正文须完整保留", enabled=False)
                elif kind == "knowledge":
                    value["description"] = "原有管理员知识库说明"
            db.execute("INSERT INTO default_templates VALUES (?,?,?,?,?,?)", (id_, kind, store.dumps(value), builtin_key, STAMP, STAMP))
        for document in preset["documents"]:
            content = f"# {document['name'].removesuffix('.md')}\n\n{presets.REFERENCE_NOTICE}{document['content']}"
            if position == 1 and document == preset["documents"][0]:
                content = "legacyadmineditedtoken 管理员在升级前维护的独立正文。"
            db.execute("INSERT INTO template_documents VALUES (?,?,?,?,?)", (
                f"legacy-document-{preset['key']}-{document['key']}", knowledge_id, document["name"], content, STAMP,
            ))
    deleted_knowledge = f"legacy-knowledge-{presets.PRESETS[0]['key']}"
    deleted_skill = f"legacy-skill-{presets.PRESETS[0]['key']}"
    db.execute("DELETE FROM default_templates WHERE id IN (?,?)", (deleted_knowledge, deleted_skill))
    db.executemany("INSERT INTO platform_settings VALUES (?,?,?)", (
        ("default_catalog_v1", store.dumps({"version": presets.PRESET_VERSION}), STAMP),
        ("legacy_defaults_migrated", "true", STAMP),
        ("branding", store.dumps({"name": "原有品牌", "tagline": "保留管理员配置"}), STAMP),
        ("legacy-custom-setting", store.dumps({"enabled": False, "value": "不改动"}), STAMP),
    ))
    db.commit()
    snapshot = {
        table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("users", "entities", "default_templates", "template_documents", "platform_settings")
    }
    schema = {table: [tuple(row) for row in db.execute(f"PRAGMA table_info({table})")] for table in snapshot}
    db.close()
    return {
        "snapshot": snapshot, "schema": schema, "legacy_users": users, "restricted": restricted,
        "encrypted": encrypted, "secrets": secrets, "deleted_knowledge": deleted_knowledge, "deleted_skill": deleted_skill,
    }


def _rows(table, clause="", parameters=()):
    with store.connect() as db:
        return [dict(row) for row in db.execute(f"SELECT * FROM {table} {clause} ORDER BY rowid", parameters)]


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _stable_database():
    return {table: _rows(table) for table in REQUIRED_TABLES}


def _assert_legacy_preserved(legacy):
    assert legacy["key_file"].read_bytes() == legacy["key"]
    assert legacy["key_file"].stat().st_mode & 0o777 == 0o600
    with store.connect() as db:
        for table, schema in legacy["schema"].items():
            assert [tuple(row) for row in db.execute(f"PRAGMA table_info({table})")] == schema
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    current_users = {row["id"]: row for row in _rows("users")}
    assert len(current_users) == len(legacy["snapshot"]["users"])
    for previous in legacy["snapshot"]["users"]:
        current = current_users[previous["id"]]
        for field in ("id", "email", "password", "created_at"):
            assert current[field] == previous[field]
        original_data, current_data = store.loads(previous["data"]), store.loads(current["data"])
        for field, value in original_data.items():
            assert current_data[field] == value
        assert set(current_data) - set(original_data) <= {"allowed_control_levels", "space_modules"}
        if "allowed_control_levels" not in original_data:
            assert current_data["allowed_control_levels"] == list(access.CONTROL_LEVELS)
        if "space_modules" not in original_data:
            assert current_data["space_modules"] == ["personal"]
        else:
            assert current_data["space_modules"] == original_data["space_modules"]
        assert store.password_matches(ADMIN_PASSWORD if previous["email"] == "admin" else PASSWORD, current["password"])
    current_entities = {row["id"]: row for row in _rows("entities")}
    for previous in legacy["snapshot"]["entities"]:
        assert current_entities[previous["id"]] == previous
    server = store.get_entity("legacy-user-0", "servers", "legacy-server")
    provider = store.get_entity("legacy-user-0", "providers", "legacy-provider")
    assert server is not None and provider is not None
    for field, key in (("password", "server-password"), ("private_key", "server-private-key"), ("kubeconfig", "server-kubeconfig")):
        assert server[field] == legacy["encrypted"][key]
        assert store.unseal(server[field]) == legacy["secrets"][key]
    assert provider["api_key"] == legacy["encrypted"]["provider-api-key"]
    assert store.unseal(provider["api_key"]) == legacy["secrets"]["provider-api-key"]
    templates = {row["id"]: row for row in _rows("default_templates")}
    documents = {row["id"]: row for row in _rows("template_documents")}
    for previous in legacy["snapshot"]["default_templates"]:
        current = templates[previous["id"]]
        assert {key: value for key, value in current.items() if key != "updated_at"} == {
            key: value for key, value in previous.items() if key != "updated_at"
        }
        if previous["kind"] != "knowledge":
            assert current == previous
    for previous in legacy["snapshot"]["template_documents"]:
        assert documents[previous["id"]] == previous
    settings = {row["key"]: row for row in _rows("platform_settings")}
    for previous in legacy["snapshot"]["platform_settings"]:
        assert settings[previous["key"]] == previous
    assert legacy["deleted_knowledge"] not in templates and legacy["deleted_skill"] not in templates
    assert not any(row["template_id"] == legacy["deleted_knowledge"] for row in documents.values())
    assert len(defaults.list_templates("knowledge")) == 49
    assert len(defaults.list_templates("skills")) == 99
    assert len(_rows("platform_settings", "WHERE key=?", (MARKER,))) == 1


def test_legacy_schema_full_lifespan_adds_missing_tables_indexes_without_losing_data(legacy_database, monkeypatch):
    with sqlite3.connect(store.DB_PATH) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"users", "entities", "default_templates", "template_documents", "platform_settings"}
    assert not os.getenv("EARTHAI_MASTER_KEY")
    original_recover = engine.recover_interrupted
    startup_checks = []

    def recover_after_schema_and_catalog():
        assert len(_rows("platform_settings", "WHERE key=?", (MARKER,))) == 1
        assert len(defaults.list_templates("skills")) == 99
        for owner in legacy_database["legacy_users"]:
            assert len([item for item in store.list_entities(owner, "skills") if item.get("default_template_id")]) == 99
        startup_checks.append(True)
        original_recover()

    monkeypatch.setattr(engine, "recover_interrupted", recover_after_schema_and_catalog)
    with TestClient(main.app) as client:
        _ok(client.get("/api/health"))
        assert startup_checks == [True]
        with store.connect() as db:
            tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            indexes = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            assert REQUIRED_TABLES <= tables
            assert REQUIRED_INDEXES <= indexes
            assert "WHERE status IN ('queued','running','waiting_approval')" in db.execute(
                "SELECT sql FROM sqlite_master WHERE name='idx_single_active_run'",
            ).fetchone()["sql"]
        _assert_legacy_preserved(legacy_database)
        for owner, old in legacy_database["legacy_users"].items():
            client.cookies.clear()
            client.cookies.set("earthai_session", store.new_session(owner))
            me = _ok(client.get("/api/auth/me"))
            assert me["allowed_control_levels"] == list(access.CONTROL_LEVELS)
            assert me["control_level"] == old["control_level"]
            preferences = _ok(client.get("/api/preferences/chat"))
            assert preferences == old["chat_preferences"]
        client.cookies.clear()
        client.cookies.set("earthai_session", store.new_session("restricted-user"))
        assert _ok(client.get("/api/auth/me"))["allowed_control_levels"] == ["observe", "approve"]
        assert _ok(client.get("/api/preferences/chat")) == legacy_database["restricted"]["chat_preferences"]
        client.cookies.clear()
        logged_in = _ok(client.post("/api/auth/login", json={"email": "admin", "password": ADMIN_PASSWORD}))
        assert logged_in["id"] == "legacy-admin" and logged_in["must_change_password"] is False
        assert client.get("/api/admin/defaults/skills").status_code == 200
        frozen = _stable_database()
        marker = _rows("platform_settings", "WHERE key=?", (MARKER,))
    store._cipher.cache_clear()
    with TestClient(main.app) as restarted:
        _ok(restarted.get("/api/health"))
        assert startup_checks == [True, True]
        _assert_legacy_preserved(legacy_database)
        assert _stable_database() == frozen
        assert _rows("platform_settings", "WHERE key=?", (MARKER,)) == marker
        assert list(store.UPLOADS.iterdir()) == []
