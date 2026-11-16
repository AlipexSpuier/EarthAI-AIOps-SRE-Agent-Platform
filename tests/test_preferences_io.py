import asyncio
from contextlib import contextmanager

import pytest
from fastapi import HTTPException, Response

from backend import main, store


OWNER = "preferences-io-owner"
STAMP = "2030-01-01T00:00:00+00:00"
EMPTY = {"server_id": None, "provider_id": None, "model": "", "agent_id": None, "project_id": None, "control_level": "approve"}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "earthai.db")
    monkeypatch.setattr(store, "UPLOADS", tmp_path / "uploads")
    store.init_db()
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            OWNER, "preferences-io@example.test", "unused", store.dumps({"theme": "dark", "chat_preferences": EMPTY}), STAMP,
        ))
    return OWNER


def _user(owner, connect=None):
    with (connect or store.connect)() as db:
        return store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()["data"])


def _save_user(owner, data, connect=None):
    with (connect or store.connect)() as db:
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), owner))


@contextmanager
def _trace(monkeypatch):
    statements = []
    original = store.connect

    @contextmanager
    def connect():
        with original() as db:
            db.set_trace_callback(lambda sql: statements.append(" ".join(sql.lower().split())))
            yield db

    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", connect)
        yield statements


def _user_reads(statements):
    return [index for index, sql in enumerate(statements) if sql.startswith("select data from users where id=")]


def _writes(statements):
    return [sql for sql in statements if sql.startswith(("insert ", "update ", "delete ", "replace "))]


def _resources(owner):
    server = store.save_entity(owner, "servers", {"name": "chosen-server"})
    provider = store.save_entity(owner, "providers", {"name": "chosen-provider", "models": ["catalog-model"], "default_model": "catalog-model"})
    agent = store.save_entity(owner, "agents", {"name": "chosen-agent", "kind": "local"})
    project = store.save_entity(owner, "projects", {"name": "chosen-project"})
    return {**EMPTY, "server_id": server["id"], "provider_id": provider["id"], "agent_id": agent["id"],
            "project_id": project["id"], "model": "custom/not-in-catalog", "control_level": "observe"}


@pytest.mark.parametrize("initial", ["legacy", "stale"])
def test_second_get_is_select_only_after_migration_or_repair(owner, monkeypatch, initial):
    expected = _resources(owner)
    data = _user(owner)
    if initial == "legacy":
        data.pop("chat_preferences")
        store.save_entity(owner, "conversations", {"title": "latest", **expected})
    else:
        data["chat_preferences"] = {**expected, "server_id": "deleted-server"}
        expected["server_id"] = None
    _save_user(owner, data)

    with _trace(monkeypatch) as statements:
        preferences, cleared = main.chat_preferences(owner)
    assert preferences == expected
    assert cleared == (["server_id"] if initial == "stale" else [])
    begin = statements.index("begin immediate")
    first, second = _user_reads(statements)
    assert first < begin < second
    assert len(_writes(statements)) == 1
    assert statements[-1] == "commit"

    with _trace(monkeypatch) as statements:
        assert main.chat_preferences(owner) == (expected, [])
    assert statements
    assert all(sql.startswith("select ") for sql in statements)
    assert len(_user_reads(statements)) == 1
    assert not any(sql.startswith(("begin", "update")) for sql in statements)


@pytest.mark.parametrize("initial", ["legacy", "stale"])
def test_get_reloads_profile_and_other_preferences_under_write_lock(owner, monkeypatch, initial):
    data = _user(owner)
    if initial == "legacy":
        data.pop("chat_preferences")
    else:
        data["chat_preferences"] = {**EMPTY, "server_id": "deleted-server", "model": "old-model"}
    _save_user(owner, data)
    original_compute = main._chat_preferences
    original_connect = store.connect
    read_transactions = []

    def compute(db, current_owner, changes):
        read_transactions.append(db.in_transaction)
        result = original_compute(db, current_owner, changes)
        if len(read_transactions) == 1:
            latest = _user(owner, original_connect)
            latest.update(theme="light", display_name="latest-profile", control_level="autonomous")
            if initial == "stale":
                latest["chat_preferences"].update(model="peer-patch-model", control_level="observe")
            _save_user(owner, latest, original_connect)
        return result

    monkeypatch.setattr(main, "_chat_preferences", compute)
    with _trace(monkeypatch) as statements:
        preferences, cleared = main.chat_preferences(owner)
    assert read_transactions == [False, True]
    assert preferences["model"] == ("peer-patch-model" if initial == "stale" else "")
    assert preferences["control_level"] == ("observe" if initial == "stale" else "autonomous")
    assert preferences["server_id"] is None
    assert cleared == (["server_id"] if initial == "stale" else [])
    first, second = _user_reads(statements)
    assert first < statements.index("begin immediate") < second
    assert len(_writes(statements)) == 1
    saved = _user(owner)
    assert saved["theme"] == "light"
    assert saved["display_name"] == "latest-profile"
    assert saved["chat_preferences"] == preferences


def test_completed_peer_repair_is_not_overwritten_and_keeps_cleared_header(owner, monkeypatch):
    data = _user(owner)
    data["chat_preferences"] = {**EMPTY, "server_id": "deleted-server"}
    _save_user(owner, data)
    expected = {**EMPTY, "model": "peer-custom-model", "control_level": "observe"}
    original_compute = main._chat_preferences
    original_connect = store.connect
    read_transactions = []

    def compute(db, current_owner, changes):
        read_transactions.append(db.in_transaction)
        result = original_compute(db, current_owner, changes)
        if len(read_transactions) == 1:
            latest = _user(owner, original_connect)
            latest.update(theme="light", chat_preferences=expected)
            _save_user(owner, latest, original_connect)
        return result

    monkeypatch.setattr(main, "_chat_preferences", compute)
    response = Response()
    with _trace(monkeypatch) as statements:
        actual = asyncio.run(main.get_chat_preferences(response, user={"id": owner}))
    assert actual == expected
    assert response.headers["X-EarthAI-Preferences-Cleared"] == "server_id"
    assert read_transactions == [False, True]
    assert not _writes(statements)
    assert _user(owner)["chat_preferences"] == expected
    assert _user(owner)["theme"] == "light"


def test_get_revalidates_resources_after_acquiring_write_lock(owner, monkeypatch):
    previous = _resources(owner)
    store.save_entity(owner, "conversations", {"title": "legacy-selection", **previous})
    data = _user(owner)
    data.pop("chat_preferences")
    _save_user(owner, data)
    original_compute = main._chat_preferences
    original_connect = store.connect
    reads = []

    def compute(db, current_owner, changes):
        reads.append(db.in_transaction)
        result = original_compute(db, current_owner, changes)
        if len(reads) == 1:
            with original_connect() as writer:
                writer.execute("UPDATE entities SET data=? WHERE id=?", (store.dumps({"enabled": False}), previous["provider_id"]))
                writer.execute("UPDATE entities SET data=? WHERE id=?", (store.dumps({"kind": "remote"}), previous["agent_id"]))
                writer.execute("DELETE FROM entities WHERE id IN (?,?)", (previous["server_id"], previous["project_id"]))
        return result

    monkeypatch.setattr(main, "_chat_preferences", compute)
    response = Response()
    with _trace(monkeypatch) as statements:
        preferences = asyncio.run(main.get_chat_preferences(response, user={"id": owner}))
    assert reads == [False, True]
    assert preferences == {**EMPTY, "control_level": "observe"}
    assert set(response.headers["X-EarthAI-Preferences-Cleared"].split(",")) == set(main.CHAT_REFERENCES)
    assert len(_writes(statements)) == 1
    assert _user(owner)["chat_preferences"] == preferences


def test_patch_reads_latest_user_only_after_begin_immediate(owner, monkeypatch):
    original_connect = store.connect
    original_compute = main._chat_preferences
    read_transactions = []

    @contextmanager
    def connect():
        with original_connect() as db:
            latest = _user(owner, original_connect)
            latest.update(theme="light", display_name="concurrent-profile")
            latest["chat_preferences"]["control_level"] = "observe"
            _save_user(owner, latest, original_connect)
            yield db

    def compute(db, current_owner, changes):
        read_transactions.append(db.in_transaction)
        return original_compute(db, current_owner, changes)

    monkeypatch.setattr(main, "_chat_preferences", compute)
    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", connect)
        with _trace(patch) as statements:
            preferences, cleared = main.chat_preferences(owner, {"model": "patch/custom-model"})
    assert read_transactions == [True]
    assert statements[0] == "begin immediate"
    assert len(_user_reads(statements)) == 1
    assert len(_writes(statements)) == 1
    assert statements[-1] == "commit"
    assert cleared == []
    assert preferences == {**EMPTY, "model": "patch/custom-model", "control_level": "observe"}
    saved = _user(owner)
    assert saved["theme"] == "light"
    assert saved["display_name"] == "concurrent-profile"
    assert saved["chat_preferences"] == preferences


def test_empty_patch_is_transactional_without_unnecessary_update(owner, monkeypatch):
    with _trace(monkeypatch) as statements:
        assert main.chat_preferences(owner, {}) == (EMPTY, [])
    assert statements[0] == "begin immediate"
    assert len(_user_reads(statements)) == 1
    assert not _writes(statements)
    assert statements[-1] == "commit"


def test_remote_agent_patch_is_rejected_and_rolls_back(owner, monkeypatch):
    remote = store.save_entity(owner, "agents", {"name": "remote", "kind": "remote"})
    with _trace(monkeypatch) as statements:
        with pytest.raises(HTTPException) as error:
            main.chat_preferences(owner, {"agent_id": remote["id"]})
    assert error.value.status_code == 422
    assert statements[0] == "begin immediate"
    assert statements[-1] == "rollback"
    assert not _writes(statements)
    assert _user(owner)["chat_preferences"] == EMPTY
