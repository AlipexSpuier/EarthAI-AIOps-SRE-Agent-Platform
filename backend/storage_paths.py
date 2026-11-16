from __future__ import annotations

import os
from pathlib import Path


def paths():
    root = Path(__file__).resolve().parents[1]
    data = Path(os.getenv("EARTHAI_DATA_DIR", str(root / "data"))).resolve()
    state = Path(os.getenv("EARTHAI_STATE_DIR", str(data))).resolve()
    uploads = Path(os.getenv("EARTHAI_UPLOADS_DIR", str(data / "uploads"))).resolve()
    return data, state, uploads
