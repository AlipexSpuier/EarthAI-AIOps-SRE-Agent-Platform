from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="在隔离数据目录比较知识库列表原逐项查询与批量查询；延迟为模拟值，不是实际NAS测量。")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "nas-performance-verification.json")
    args = parser.parse_args()
    os.environ["EARTHAI_DATA_DIR"] = tempfile.mkdtemp(prefix="earthai-performance-")
    os.environ.pop("EARTHAI_STATE_DIR", None)
    os.environ.pop("EARTHAI_UPLOADS_DIR", None)
    from fastapi.testclient import TestClient
    from backend import defaults, main as application, store

    delay = 0.005
    with TestClient(application.app) as client:
        response = client.post("/api/auth/register", json={"email": "benchmark@earthai.local", "password": "Benchmark-2026!", "name": "隔离基准"})
        assert response.status_code == 200
        owner = response.json()["id"]
        rows = store.list_entities(owner, "knowledge")
        assert len(rows) == 50
        original_connect = store.connect

        def evaluate(batch):
            counts = {"checkouts": 0, "statements": 0}

            def trace(sql):
                if sql.lstrip().upper().startswith("SELECT"):
                    counts["statements"] += 1
                    time.sleep(delay)

            @contextmanager
            def measured_connect():
                counts["checkouts"] += 1
                with original_connect() as db:
                    db.set_trace_callback(trace)
                    yield db
                    db.set_trace_callback(None)

            start = time.perf_counter()
            with patch.object(store, "connect", measured_connect):
                if batch:
                    result = client.get("/api/knowledge")
                    assert result.status_code == 200
                    values = result.json()
                else:
                    application.current_user(type("Request", (), {"cookies": {"earthai_session": client.cookies.get("earthai_session")}, "url": type("URL", (), {"path": "/api/knowledge"})()})())
                    values = [application.public_entity("knowledge", value) for value in store.list_entities(owner, "knowledge")]
            elapsed = time.perf_counter() - start
            assert len(values) == 50 and sum(value["document_count"] for value in values) == 100
            return {**counts, "elapsed_ms": round(elapsed * 1000, 2)}

        baseline = [evaluate(False) for _ in range(3)]
        optimized = [evaluate(True) for _ in range(3)]
        store.close_connections()
        created = 0
        actual_connect = sqlite3.connect

        def track_connection(*values, **options):
            nonlocal created
            created += 1
            return actual_connect(*values, **options)

        with patch.object(sqlite3, "connect", track_connection):
            for _ in range(20):
                with store.connect() as db:
                    assert db.execute("SELECT 1").fetchone()[0] == 1
        assert created == 1
        traces = []

        @contextmanager
        def traced_connect():
            with original_connect() as db:
                db.set_trace_callback(traces.append)
                yield db
                db.set_trace_callback(None)

        with patch.object(store, "connect", traced_connect):
            assert defaults.sync_all_if_needed() is True
            traces.clear()
            assert defaults.sync_all_if_needed() is False
        stable_sync_writes = [sql for sql in traces if sql.lstrip().upper().startswith(("BEGIN IMMEDIATE", "INSERT", "UPDATE", "DELETE"))]
        assert not stable_sync_writes
        report = {
            "ok": True,
            "scope": "isolated TestClient, 50 knowledge bases / 100 documents; equivalent previous per-item counter vs current API; simulated SELECT latency only, not real NAS measurements",
            "simulated_select_delay_ms": delay * 1000,
            "previous_equivalent": {"samples": baseline, "median_ms": statistics.median(value["elapsed_ms"] for value in baseline)},
            "optimized_api": {"samples": optimized, "median_ms": statistics.median(value["elapsed_ms"] for value in optimized)},
            "pooled_connections_created_for_20_reads": created,
            "unchanged_startup_sync_statements": traces,
            "unchanged_startup_sync_write_count": len(stable_sync_writes),
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
