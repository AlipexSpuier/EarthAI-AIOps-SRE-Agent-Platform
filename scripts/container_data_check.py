from __future__ import annotations

import hashlib
import json

from backend import store


def digest(db, query):
    result = hashlib.sha256()
    for row in db.execute(query):
        result.update(json.dumps(tuple(row), ensure_ascii=False).encode())
    return result.hexdigest()


def main():
    with store.connect() as db:
        report = {
            "users": db.execute("SELECT count(*) FROM users").fetchone()[0],
            "entities": {row[0]: row[1] for row in db.execute("SELECT kind,count(*) FROM entities GROUP BY kind")},
            "messages": db.execute("SELECT count(*) FROM messages").fetchone()[0],
            "runs": db.execute("SELECT count(*) FROM runs").fetchone()[0],
            "documents": db.execute("SELECT count(*) FROM documents").fetchone()[0],
            "active_runs": db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running','waiting_approval')").fetchone()[0],
            "user_data_digest": digest(db, "SELECT id,email,password,data,created_at FROM users ORDER BY id"),
            "entity_data_digest": digest(db, "SELECT id,owner,kind,data,created_at,updated_at FROM entities ORDER BY id"),
        }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
