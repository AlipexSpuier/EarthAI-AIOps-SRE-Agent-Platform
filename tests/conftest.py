import os
import tempfile

import pytest

os.environ["EARTHAI_DATA_DIR"] = tempfile.mkdtemp(prefix="earthai-tests-")


@pytest.fixture(autouse=True)
def local_provider_catalog(monkeypatch):
    from backend import engine

    async def catalog(provider):
        return list(provider.get("models", []))

    monkeypatch.setattr(engine, "provider_models", catalog)
