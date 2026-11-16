from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import defaults, engine, main, store

REAL_CATALOG = engine.provider_models


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "sync.db")
    main.login_attempts.clear()
    with TestClient(main.app) as client:
        yield client


def login(client, administrator):
    if administrator:
        assert client.post("/api/auth/login", json={"email": "admin", "password": "admin"}).status_code == 200
        assert client.post("/api/auth/password", json={"current_password": "admin", "new_password": "Sync-Admin-2026!"}).status_code == 200
        return "/api/admin/defaults/providers"
    response = client.post("/api/auth/register", json={"email": "sync@example.com", "password": "Sync-User-2026!", "name": "同步验收"})
    assert response.status_code == 200
    return "/api/providers"


def install_catalog(monkeypatch, handler):
    calls = Mock(side_effect=handler)
    original = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(calls)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(engine, "provider_models", REAL_CATALOG)
    return calls


def payload(**changes):
    return {"name": "目录供应商", "base_url": "http://models.example.test/v1", "api_key": "test-sync-key", **changes}


@pytest.mark.parametrize("administrator", [False, True])
def test_new_provider_discovers_once_and_chooses_remote_first(client, monkeypatch, administrator):
    endpoint = login(client, administrator)

    def handler(request):
        assert request.method == "GET" and str(request.url) == "http://models.example.test/v1/models"
        assert request.headers["authorization"] == "Bearer test-sync-key"
        return httpx.Response(200, json={"data": [{"id": "remote-first"}, {"id": "remote-second"}, {"id": "remote-first"}]})

    calls = install_catalog(monkeypatch, handler)
    response = client.post(endpoint, json=payload(models=["manual"], default_model="manual"))
    assert response.status_code == 200, response.text
    provider = response.json()
    assert provider["models"] == ["remote-first", "remote-second"]
    assert provider["default_model"] == "remote-first"
    assert provider["model_sync"]["status"] == "ok" and calls.call_count == 1
    assert "api_key" not in provider and "test-sync-key" not in response.text
    response = client.patch(endpoint + "/" + provider["id"], json={"name": "只改名字"})
    assert response.status_code == 200 and calls.call_count == 1
    assert client.get(endpoint).json()[0]["default_model"] == "remote-first"
    if administrator:
        user = client.post("/api/auth/register", json={"email": "inherits@example.com", "password": "Sync-User-2026!"}).json()
        inherited = client.get("/api/providers").json()[0]
        assert inherited["read_only"] and inherited["default_model"] == "remote-first"
        assert client.post(f"/api/providers/{inherited['id']}/sync-models").status_code == 403
        assert store.get_entity(user["id"], "providers", inherited["id"])["default_model"] == "remote-first"


@pytest.mark.parametrize("administrator", [False, True])
@pytest.mark.parametrize("response", [
    (401, {"error": "credential failure test-sync-key"}, "error"),
    (200, {"data": []}, "empty"),
    (200, {"models": []}, "error"),
])
def test_sync_failure_keeps_saved_provider_and_does_not_claim_success(client, monkeypatch, administrator, response):
    endpoint = login(client, administrator)
    status, body, outcome = response
    calls = install_catalog(monkeypatch, lambda request: httpx.Response(status, json=body))
    result = client.post(endpoint, json=payload())
    assert result.status_code == 200, result.text
    provider = result.json()
    assert provider["model_sync"]["status"] == outcome
    assert provider["models"] == [] and provider["default_model"] == ""
    assert provider["id"] in {value["id"] for value in client.get(endpoint).json()}
    assert calls.call_count == 1 and "test-sync-key" not in result.text


@pytest.mark.parametrize("administrator", [False, True])
def test_manual_resync_preserves_valid_default_and_recovers_empty_provider(client, monkeypatch, administrator):
    endpoint = login(client, administrator)
    calls = install_catalog(monkeypatch, lambda request: httpx.Response(404, json={"error": "no catalog"}))
    provider = client.post(endpoint, json=payload()).json()
    assert provider["model_sync"]["status"] == "error" and calls.call_count == 1
    calls.side_effect = lambda request: httpx.Response(200, json={"data": [{"id": "one"}, {"id": "two"}]})
    recovered = client.post(endpoint + "/" + provider["id"] + "/sync-models").json()
    assert recovered["default_model"] == "one" and recovered["model_sync"]["status"] == "ok"
    assert client.patch(endpoint + "/" + provider["id"], json={"default_model": "two"}).status_code == 200
    result = client.post(endpoint + "/" + provider["id"] + "/sync-models").json()
    assert result["default_model"] == "two"
    calls.side_effect = lambda request: httpx.Response(500, json={"error": "temporary"})
    result = client.post(endpoint + "/" + provider["id"] + "/sync-models").json()
    assert result["model_sync"]["status"] == "error" and result["models"] == ["one", "two"] and result["default_model"] == "two"
    assert calls.call_count == 4


@pytest.mark.parametrize("administrator", [False, True])
def test_concurrent_edit_during_auto_sync_is_not_overwritten(client, monkeypatch, administrator):
    endpoint = login(client, administrator)
    owner = client.get("/api/auth/me").json()["id"]

    async def catalog(provider):
        if administrator:
            latest = defaults.get_template("providers", provider["id"])
            data = {key: value for key, value in latest.items() if key not in {"id", "created_at", "updated_at"}}
            defaults.save("providers", {**data, "name": "并发更新", "models": ["new"], "default_model": "new"}, provider["id"])
        else:
            latest = store.get_entity(owner, "providers", provider["id"])
            store.save_entity(owner, "providers", {**latest, "name": "并发更新", "models": ["new"], "default_model": "new"}, provider["id"])
        return ["stale"]

    monkeypatch.setattr(engine, "provider_models", catalog)
    response = client.post(endpoint, json=payload())
    assert response.status_code == 200, response.text
    assert response.json()["model_sync"]["status"] == "stale"
    stored = client.get(endpoint).json()[0]
    assert stored["name"] == "并发更新" and stored["default_model"] == "new"


def test_models_directory_is_not_a_chat_completion(client, monkeypatch):
    endpoint = login(client, False)
    calls = install_catalog(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "first"}]}))
    client.post(endpoint, json=payload())
    assert calls.call_count == 1
    assert all(call.args[0].method == "GET" and call.args[0].url.path.endswith("/models") for call in calls.call_args_list)
