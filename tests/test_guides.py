import json

import pytest
from fastapi.testclient import TestClient

from backend import guides, main, store


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "guides.db")
    main.login_attempts.clear()
    with TestClient(main.app) as client:
        yield client


def admin(client):
    assert client.post("/api/auth/login", json={"email": "admin", "password": "admin"}).status_code == 200
    assert client.post("/api/auth/password", json={"current_password": "admin", "new_password": "Guide-Admin-2026!"}).status_code == 200
    return client.cookies.get("earthai_session")


def session(client, token):
    client.cookies.clear()
    client.cookies.set("earthai_session", token)


def body(**changes):
    return {"id": "new-guide", "title": "新指南", "summary": "适用范围", "content": "## 实际操作\n\n1. 核对目标。\n2. 验证结果。", "icon": "BookOpen", "sort_order": 100, **changes}


def test_guides_seed_complete_once_and_scope_by_role(client):
    assert client.get("/api/guides").status_code == 401
    token = admin(client)
    assert len(client.get("/api/guides").json()) == 11
    assert all(item["audience"] == "admin" for item in client.get("/api/guides").json())
    user = client.post("/api/auth/register", json={"email": "guides@example.com", "password": "Guides-User-2026!"})
    assert user.status_code == 200
    values = client.get("/api/guides?audience=admin").json()
    assert len(values) == 12 and all(item["audience"] == "user" and len(item["content"]) > 500 for item in values)
    assert client.get("/api/admin/guides?audience=admin").status_code == 403
    for method, endpoint, data in (("POST", "/api/admin/guides/user", body()), ("PATCH", "/api/admin/guides/user/chat", {"title": "不允许"}), ("DELETE", "/api/admin/guides/user/chat", None), ("POST", "/api/admin/guides/user/batch-delete", {"ids": ["chat"]})):
        assert client.request(method, endpoint, json=data).status_code == 403
    session(client, token)
    assert client.get("/api/admin/guides?audience=invalid").status_code == 422
    sources = json.loads((store.ROOT / "backend" / "guide_presets.json").read_text())
    for role in ("admin", "user"):
        values = client.get("/api/admin/guides?audience=" + role).json()
        assert len(values) == len(sources[role])
        assert {value["id"]: value["content"] for value in values} == {value["id"]: value["content"] for value in sources[role]}


@pytest.mark.parametrize("role", ["admin", "user"])
def test_admin_guide_crud_persists_restarts_and_does_not_resurrect(client, role):
    admin(client)
    endpoint = "/api/admin/guides/" + role
    response = client.post(endpoint, json=body())
    assert response.status_code == 200, response.text
    original = response.json()
    assert original["audience"] == role
    assert client.post(endpoint, json=body()).status_code == 409
    updated = client.patch(endpoint + "/new-guide", json={"title": "修订指南", "content": "# 新正文\n\n明确可用步骤。", "sort_order": 1}).json()
    assert updated["id"] == original["id"] and updated["created_at"] == original["created_at"]
    guides.initialize()
    values = guides.entries(role)
    assert next(value for value in values if value["id"] == "new-guide")["content"] == "# 新正文\n\n明确可用步骤。"
    assert client.delete(endpoint + "/new-guide").status_code == 200
    assert client.patch(endpoint + "/new-guide", json={"title": "不能复活"}).status_code == 404
    assert client.delete(endpoint + "/new-guide").status_code == 404
    guides.initialize()
    assert not any(value["id"] == "new-guide" for value in guides.entries(role))
    with store.connect() as db:
        actions = [row["action"] for row in db.execute("SELECT action FROM audit")]
    assert {"admin.guides.create", "admin.guides.update", "admin.guides.delete"} <= set(actions)


@pytest.mark.parametrize("changes", [
    {"id": "../etc"}, {"id": "Upper Case"}, {"title": ""}, {"content": ""},
    {"title": "x" * 121}, {"summary": "x" * 1001}, {"sort_order": -1}, {"sort_order": True},
    {"icon": "https://evil/icon.svg"}, {"icon": []}, {"content": ["not a string"]}, {"audience": "admin"},
])
def test_guide_validation_and_failed_write_preserves_catalog(client, changes):
    admin(client)
    before = guides.entries("user")
    response = client.post("/api/admin/guides/user", json=body(**changes))
    assert response.status_code == 422, response.text
    assert guides.entries("user") == before
    assert client.patch("/api/admin/guides/user/chat", json={"id": "rename"}).status_code == 422
    assert client.post("/api/admin/guides/root", json=body()).status_code == 422


def test_batch_deletion_is_atomic_and_clearing_all_guides_is_stable(client):
    admin(client)
    before = guides.entries("user")
    for ids in (["chat", "missing"], ["chat", "chat"], [], "chat"):
        response = client.post("/api/admin/guides/user/batch-delete", json={"ids": ids})
        assert response.status_code in {404, 422}
        assert guides.entries("user") == before
    ids = [value["id"] for value in before]
    assert client.post("/api/admin/guides/user/batch-delete", json={"ids": ids}).json() == {"ok": True, "count": 12}
    assert guides.entries("user") == []
    guides.initialize()
    assert guides.entries("user") == [] and len(guides.entries("admin")) == 11


def test_role_change_guides_and_forced_password_rules_are_server_enforced(client):
    response = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert response.status_code == 200
    assert client.get("/api/guides").status_code == 403
    assert client.get("/api/admin/guides").status_code == 403
    assert client.post("/api/auth/password", json={"current_password": "admin", "new_password": "Guides-Admin-2026!"}).status_code == 200
    assert client.get("/api/guides").status_code == 200
    assert client.get("/api/conversations").status_code == 403
