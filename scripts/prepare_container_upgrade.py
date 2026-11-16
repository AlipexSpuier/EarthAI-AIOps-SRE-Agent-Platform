from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT.parent / ".tools" / "earthai-deployment"
CONTAINER = "earthai-earthai-1"
IMAGE = "earthai:latest"


def docker(*args, binary=False):
    result = subprocess.run(["docker", *args], check=True, capture_output=True, text=not binary)
    return result.stdout


def main():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    PRIVATE.chmod(0o700)
    config = json.loads(docker("inspect", CONTAINER))[0]
    if any(item["Destination"] != "/app/data" for item in config["Mounts"]) or any(item.startswith("EARTHAI_STATE_DIR=") or item.startswith("EARTHAI_UPLOADS_DIR=") for item in config["Config"]["Env"]):
        raise RuntimeError("This legacy helper only supports its original named volume; platform-managed NAS deployments must preserve the existing /app/data mount in the deployment platform")
    mount = next(item for item in config["Mounts"] if item["Destination"] == "/app/data")
    if mount["Type"] != "volume":
        raise RuntimeError("Unexpected data mount; deployment stopped")
    ports = config["HostConfig"]["PortBindings"]["8000/tcp"]
    if len(ports) != 1:
        raise RuntimeError("Unexpected port configuration; deployment stopped")
    private_snapshot = PRIVATE / "previous-container.json"
    private_snapshot.write_text(json.dumps(config))
    private_snapshot.chmod(0o600)
    check = "import os,sqlite3,pathlib; p=pathlib.Path(os.environ.get('EARTHAI_DATA_DIR','/app/data'))/'earthai.db'; c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True); n=c.execute(\"select count(*) from runs where status in ('queued','running','waiting_approval')\").fetchone()[0]; print(n); assert n==0, 'Active user tasks: deployment stopped'"
    docker("exec", CONTAINER, "python", "-c", check)
    backup = """import os,sqlite3,tempfile,zipfile,pathlib
root=pathlib.Path(os.environ.get('EARTHAI_DATA_DIR','/app/data'))
copy=pathlib.Path('/tmp/earthai-upgrade-snapshot.db')
with sqlite3.connect(root/'earthai.db') as source, sqlite3.connect(copy) as target: source.backup(target)
with zipfile.ZipFile('/tmp/earthai-upgrade-backup.zip','w',zipfile.ZIP_DEFLATED) as archive:
 archive.write(copy,'data/earthai.db')
 if (root/'master.key').is_file(): archive.write(root/'master.key','data/master.key')
 for directory in (root/'uploads',root/'branding'):
  for file in directory.glob('*'):
   if file.is_file(): archive.write(file,'data/'+directory.name+'/'+file.name)
copy.unlink()
"""
    docker("exec", CONTAINER, "python", "-c", backup)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups = ROOT / "backups"
    backups.mkdir(exist_ok=True)
    backups.chmod(0o700)
    destination = backups / f"EarthAI-container-before-management-{stamp}.zip"
    docker("cp", CONTAINER + ":/tmp/earthai-upgrade-backup.zip", str(destination))
    destination.chmod(0o600)
    environments = dict(item.split("=", 1) for item in config["Config"]["Env"] if item.startswith("EARTHAI_"))
    runtime = {
        "services": {"earthai": {
            "image": IMAGE,
            "user": "0:0",
            "ports": [f"{ports[0].get('HostIp') or '0.0.0.0'}:{ports[0]['HostPort']}:8000"],
            "environment": environments,
            "volumes": ["earthai-data:/app/data"],
            "restart": config["HostConfig"]["RestartPolicy"]["Name"] or "unless-stopped",
            "init": True,
            "stop_grace_period": "150s",
            "security_opt": config["HostConfig"].get("SecurityOpt") or ["no-new-privileges:true"],
            "cap_drop": ["ALL"],
            "cap_add": ["DAC_OVERRIDE", "FOWNER"],
        }},
        "volumes": {"earthai-data": {"name": mount["Name"], "external": True}},
    }
    if config["HostConfig"].get("Privileged"):
        runtime["services"]["earthai"]["privileged"] = False
    override = PRIVATE / "runtime.override.json"
    override.write_text(json.dumps(runtime))
    override.chmod(0o600)
    print(json.dumps({"prepared": True, "container": CONTAINER, "data_volume": mount["Name"], "backup": str(destination), "override": str(override), "image": IMAGE, "rollback_image": config["Image"], "bind": ports[0]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
