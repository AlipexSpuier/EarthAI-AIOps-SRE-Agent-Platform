from __future__ import annotations

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = [
    "live-baseline.json",
    "live-enhanced.json",
    "live-json-protocol.json",
    "live-gpt-json-recheck.json",
    "live-gpt-final-diagnostic.json",
    "live-gpt-planner.json",
    "live-final-validated.json",
]
rows = []
for name in paths:
    path = root / "docs" / name
    if path.is_file():
        body = json.loads(path.read_text())
        rows.append(
            {
                "file": name,
                "label": body["label"],
                "episodes": len(body["results"]),
                "successes": sum(bool(item["success"]) for item in body["results"]),
                "verified_ssh": sum(
                    step.get("name") == "ssh_exec" and step.get("exit_code") == 0 for item in body["results"] for step in item["tools"]
                ),
            }
        )
print(json.dumps(rows, ensure_ascii=False, indent=2))
