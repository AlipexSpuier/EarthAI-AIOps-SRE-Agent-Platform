import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import main, store


FIELDS = {"server_id", "provider_id", "model", "agent_id", "project_id", "control_level"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "earthai.db")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(main, "seed_user", lambda owner: None)
    main.login_attempts.clear()
    with TestClient(main.app) as client:
        yield client


def register(client, email="preferences@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "isolated-test-password"})
    assert response.status_code == 200, response.text
    return response.json()


def provider(client, name="provider-one", enabled=True):
    response = client.post("/api/providers", json={"name": name, "base_url": "https://example.com/v1", "api_key": "fake-preferences-key", "models": [name + "-default"], "default_model": name + "-default", "enabled": enabled})
    assert response.status_code == 200, response.text
    return response.json()


def preferences(client, **changes):
    response = client.patch("/api/preferences/chat", json=changes)
    assert response.status_code == 200, response.text
    return response.json()


def user_data(owner):
    with store.connect() as db:
        return store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])


def request(body):
    async def receive():
        return {"type": "http.request", "body": store.dumps(body).encode(), "more_body": False}
    return Request({"type": "http", "method": "PATCH", "path": "/api/auth/me", "headers": []}, receive)


def test_new_user_has_exact_six_fields_and_no_automatic_resource_selection(client):
    user = register(client)
    expected = {"server_id": None, "provider_id": None, "model": "", "agent_id": None, "project_id": None, "control_level": "observe"}
    assert user["allowed_control_levels"] == ["observe"]
    assert user["control_level"] == "observe"
    assert user["chat_preferences"] == expected
    assert client.get("/api/preferences/chat").json() == expected
    provider(client)
    assert client.get("/api/preferences/chat").json() == expected
    assert client.patch("/api/preferences/chat", json={"password": "must-not-save"}).status_code == 422
    assert set(user_data(user["id"])["chat_preferences"]) == FIELDS


def test_full_preferences_restore_after_logout_and_new_conversations_do_not_reset(client):
    user = register(client)
    p = provider(client)
    server = store.save_entity(user["id"], "servers", {"name": "chosen-server"})
    agent = store.save_entity(user["id"], "agents", {"name": "chosen-agent"})
    project = store.save_entity(user["id"], "projects", {"name": "chosen-project"})
    chosen = preferences(client, server_id=server["id"], provider_id=p["id"], model="custom/not-in-catalog", agent_id=agent["id"], project_id=project["id"], control_level="observe")
    assert set(chosen) == FIELDS
    for _ in range(3):
        response = client.post("/api/conversations", json={"title": "new conversation"})
        assert response.status_code == 200, response.text
        assert {key: response.json()[key] for key in FIELDS} == chosen
    client.post("/api/auth/logout")
    assert client.get("/api/preferences/chat").status_code == 401
    client.post("/api/auth/login", json={"email": user["email"], "password": "isolated-test-password"})
    assert client.get("/api/preferences/chat").json() == chosen
    assert "fake-preferences-key" not in store.dumps(chosen)


def test_explicit_empty_fields_and_creation_override_without_rewriting_preferences(client):
    user = register(client)
    p = provider(client)
    server = store.save_entity(user["id"], "servers", {"name": "saved-server"})
    saved = preferences(client, server_id=server["id"], provider_id=p["id"], model="private-model", control_level="observe")
    explicit = {"server_id": None, "provider_id": None, "model": "", "agent_id": None, "project_id": None, "control_level": "observe"}
    response = client.post("/api/conversations", json=explicit)
    assert response.status_code == 200, response.text
    assert {key: response.json()[key] for key in FIELDS} == explicit
    assert client.get("/api/preferences/chat").json() == saved
    cleared = preferences(client, server_id="", provider_id=None, model=None, agent_id="", project_id=None)
    assert cleared == explicit
    assert {key: client.post("/api/conversations", json={}).json()[key] for key in FIELDS} == explicit


def test_owner_isolation_and_strict_patch_validation(client):
    owner = register(client)
    p = provider(client)
    server = store.save_entity(owner["id"], "servers", {"name": "private-server"})
    saved = preferences(client, provider_id=p["id"], model="owner-only", server_id=server["id"])
    register(client, "other-preferences@example.com")
    for changes in [{"provider_id": p["id"]}, {"server_id": server["id"]}, {"agent_id": "missing-agent"}, {"project_id": "missing-project"}]:
        assert client.patch("/api/preferences/chat", json=changes).status_code == 404
    for body in [[], None, {"server_id": 1}, {"agent_id": False}, {"project_id": []}, {"provider_id": {}}, {"model": True}, {"model": "x" * 201}, {"control_level": []}, {"control_level": None}, {"control_level": "superuser"}]:
        assert client.patch("/api/preferences/chat", content=store.dumps(body), headers={"Content-Type": "application/json"}).status_code == 422
    assert client.get("/api/preferences/chat").json()["provider_id"] is None
    assert client.post("/api/conversations", json={"provider_id": {}}).status_code == 422
    assert client.post("/api/conversations", json={"provider_id": False}).status_code == 422
    client.post("/api/auth/login", json={"email": owner["email"], "password": "isolated-test-password"})
    assert client.get("/api/preferences/chat").json() == saved


def test_deleted_disabled_resources_are_cleared_without_choosing_other_resources(client):
    owner = register(client)
    p = provider(client)
    backup = provider(client, "backup")
    server = store.save_entity(owner["id"], "servers", {"name": "deleted-server"})
    agent = store.save_entity(owner["id"], "agents", {"name": "deleted-agent"})
    project = store.save_entity(owner["id"], "projects", {"name": "deleted-project"})
    preferences(client, server_id=server["id"], provider_id=p["id"], model="custom-model", agent_id=agent["id"], project_id=project["id"], control_level="observe")
    client.patch(f"/api/providers/{p['id']}", json={"enabled": False})
    assert client.patch("/api/preferences/chat", json={"provider_id": p["id"]}).status_code == 422
    for kind, item in [("servers", server), ("agents", agent), ("projects", project)]:
        store.delete_entity(owner["id"], kind, item["id"])
    response = client.get("/api/preferences/chat")
    assert response.json() == {"server_id": None, "provider_id": None, "model": "", "agent_id": None, "project_id": None, "control_level": "observe"}
    assert set(response.headers["X-EarthAI-Preferences-Cleared"].split(",")) == {"server_id", "provider_id", "agent_id", "project_id"}
    preferences(client, provider_id=backup["id"], model="keep-custom")
    client.patch(f"/api/providers/{backup['id']}", json={"models": ["new-default"], "default_model": "new-default"})
    assert client.get("/api/preferences/chat").json()["model"] == "keep-custom"
    client.delete(f"/api/providers/{backup['id']}")
    assert client.get("/api/preferences/chat").json()["provider_id"] is None
    assert client.get("/api/preferences/chat").json()["model"] == ""


def test_provider_changes_reset_default_only_when_model_not_explicit(client):
    register(client)
    first = provider(client)
    second = provider(client, "provider-two")
    preferences(client, provider_id=first["id"], model="my-custom-model")
    assert preferences(client, project_id=None)["model"] == "my-custom-model"
    assert preferences(client, provider_id=first["id"])["model"] == "my-custom-model"
    assert preferences(client, provider_id=second["id"])["model"] == second["default_model"]
    assert preferences(client, provider_id=first["id"], model="")["model"] == ""
    created = client.post("/api/conversations", json={"provider_id": second["id"]}).json()
    assert created["model"] == second["default_model"]
    assert preferences(client, provider_id=None)["model"] == ""


def test_existing_users_initialize_once_from_most_recent_conversation(client):
    user = register(client)
    with store.connect() as db:
        db.execute("UPDATE users SET data=json_set(data,'$.allowed_control_levels',json(?)) WHERE id=?", (
            store.dumps(["observe", "approve", "autonomous"]), user["id"],
        ))
    p = provider(client)
    server = store.save_entity(user["id"], "servers", {"name": "previously-selected"})
    store.save_entity(user["id"], "conversations", {"title": "older", "provider_id": p["id"], "control_level": "approve"})
    newest = {"server_id": server["id"], "provider_id": p["id"], "model": "last-custom", "agent_id": None, "project_id": None, "control_level": "observe"}
    old_conversation = store.save_entity(user["id"], "conversations", {"title": "newest", **newest})
    with store.connect() as db:
        data = user_data(user["id"])
        data.pop("chat_preferences")
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), user["id"]))
    assert client.get("/api/preferences/chat").json() == newest
    response = client.patch(f"/api/conversations/{old_conversation['id']}", json={"model": "history-change", "control_level": "autonomous"})
    assert response.status_code == 200, response.text
    client.get(f"/api/conversations/{old_conversation['id']}")
    assert client.get("/api/preferences/chat").json() == newest
    response = client.post("/api/conversations", json={"model": "different-new-chat", "control_level": "approve"})
    assert response.status_code == 200, response.text
    assert client.get("/api/preferences/chat").json() == newest


def test_legacy_no_history_uses_enabled_provider_without_agent_or_server(client):
    user = register(client)
    enabled = provider(client)
    provider(client, "disabled", enabled=False)
    store.save_entity(user["id"], "agents", {"name": "must-not-auto-select"})
    store.save_entity(user["id"], "servers", {"name": "must-not-auto-select"})
    with store.connect() as db:
        data = user_data(user["id"])
        data.pop("chat_preferences")
        data["control_level"] = "observe"
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), user["id"]))
    assert client.get("/api/preferences/chat").json() == {"server_id": None, "provider_id": enabled["id"], "model": enabled["default_model"], "agent_id": None, "project_id": None, "control_level": "observe"}


def test_theme_and_preferences_merge_latest_data_even_with_stale_auth_snapshot(client):
    stale_user = register(client)
    preferences(client, control_level="observe", model="saved-after-auth")
    result = asyncio.run(main.update_me(request({"theme": "light"}), user=stale_user))
    assert result["chat_preferences"]["model"] == "saved-after-auth"
    assert result["chat_preferences"]["control_level"] == "observe"
    asyncio.run(main.update_me(request({"theme": "dark"}), user=stale_user))
    preferences(client, model="newest-model")
    assert user_data(stale_user["id"])["theme"] == "dark"
    with ThreadPoolExecutor(max_workers=2) as pool:
        theme = pool.submit(lambda: asyncio.run(main.update_me(request({"theme": "light"}), user=stale_user)))
        prefs = pool.submit(main.chat_preferences, stale_user["id"], {"model": "concurrent-model"})
        theme.result()
        prefs.result()
    latest = user_data(stale_user["id"])
    assert latest["theme"] == "light"
    assert latest["chat_preferences"]["model"] == "concurrent-model"
    assert latest["chat_preferences"]["control_level"] == "observe"


def test_saving_preferences_does_not_touch_historical_or_running_conversation(client):
    user = register(client)
    conversation = client.post("/api/conversations", json={"model": "historical-model", "control_level": "observe"}).json()
    run_id, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (run_id, user["id"], conversation["id"], "running", store.dumps({"model": "historical-model", "control_level": "observe", "goal": "not actually executing"}), stamp, stamp))
        db.execute("UPDATE users SET data=json_set(data,'$.allowed_control_levels',json(?)) WHERE id=?", (
            store.dumps(["observe", "approve", "autonomous"]), user["id"],
        ))
    preferences(client, model="next-session", control_level="approve")
    assert store.get_entity(user["id"], "conversations", conversation["id"])["model"] == "historical-model"
    assert store.get_run(user["id"], run_id)["model"] == "historical-model"
    assert client.patch(f"/api/conversations/{conversation['id']}", json={"model": "must-be-blocked"}).status_code == 409
    assert client.post("/api/conversations", json={}).json()["model"] == "next-session"
