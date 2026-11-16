from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT.parent / ".tools" / "earthai-deployment"
CONTAINER = "earthai-earthai-1"
OVERRIDE = PRIVATE / "runtime.override.json"


def run(*args, input=None):
    result = subprocess.run(list(args), input=input, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): " + result.stderr[-3000:])
    return result.stdout


def state():
    code = (ROOT / "scripts" / "container_data_check.py").read_text()
    return json.loads(run("docker", "exec", "-i", CONTAINER, "python", "-", input=code))


def deploy():
    current = json.loads(run("docker", "inspect", CONTAINER))[0]
    if any(item["Destination"] != "/app/data" or item["Type"] != "volume" for item in current["Mounts"]) or any(item.startswith("EARTHAI_STATE_DIR=") or item.startswith("EARTHAI_UPLOADS_DIR=") for item in current["Config"]["Env"]):
        raise RuntimeError("Legacy helper only supports its original named volume; preserve the existing NAS mount at /app/data through the deployment platform")
    before = state()
    if before["active_runs"]:
        raise RuntimeError("Active tasks exist; deployment stopped")
    config = json.loads(OVERRIDE.read_text())
    config["services"]["earthai"]["image"] = "earthai:latest"
    OVERRIDE.write_text(json.dumps(config))
    previous = json.loads((PRIVATE / "previous-container.json").read_text())
    command = ["docker", "compose", "-p", "earthai", "-f", str(OVERRIDE), "up", "-d", "--no-build", "--wait", "--wait-timeout", "120"]
    try:
        result = run(*command)
        after = state()
        if before != after:
            raise RuntimeError("Persisted account/resource data changed unexpectedly during upgrade")
        actual = json.loads(run("docker", "inspect", CONTAINER))[0]
        old_volume = next(mount["Name"] for mount in previous["Mounts"] if mount["Destination"] == "/app/data")
        new_volume = next(mount["Name"] for mount in actual["Mounts"] if mount["Destination"] == "/app/data")
        if old_volume != new_volume or previous["HostConfig"]["PortBindings"] != actual["HostConfig"]["PortBindings"]:
            raise RuntimeError("Deployment volume or port changed unexpectedly")
        old_env = {item for item in previous["Config"]["Env"] if item.startswith("EARTHAI_")}
        new_env = {item for item in actual["Config"]["Env"] if item.startswith("EARTHAI_")}
        if not old_env <= new_env:
            raise RuntimeError("Application environment was not preserved")
        report = {"ok": True, "container": CONTAINER, "image": config["services"]["earthai"]["image"], "volume_preserved": True, "ports_preserved": True, "environment_preserved": True, "data_digest_unchanged": True, "users": after["users"], "entities": after["entities"], "runs": after["runs"], "messages": after["messages"], "documents": after["documents"], "health": actual["State"].get("Health", {}).get("Status"), "output": result.strip()}
        (ROOT / "docs" / "container-management-deployment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
    except Exception:
        config["services"]["earthai"]["image"] = previous["Image"]
        OVERRIDE.write_text(json.dumps(config))
        run(*command)
        raise


if __name__ == "__main__":
    deploy()
