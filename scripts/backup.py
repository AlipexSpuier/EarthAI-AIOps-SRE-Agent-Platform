from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

def storage_paths():
    from backend.storage_paths import paths
    return paths()


_, data, uploads = storage_paths()
if not (data / "earthai.db").is_file():
    raise SystemExit("找不到数据库，请在启动平台后再执行备份")
output_dir = Path(os.getenv("EARTHAI_BACKUP_DIR", str(root / "backups"))).resolve()
output_dir.mkdir(exist_ok=True)
os.chmod(output_dir, 0o700)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
database_copy = output_dir / f"snapshot-{stamp}.db"
with sqlite3.connect(data / "earthai.db") as source, sqlite3.connect(database_copy) as target:
    source.backup(target)
output = output_dir / f"EarthAI-backup-{stamp}.zip"
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(database_copy, "data/earthai.db")
    if (data / "master.key").is_file():
        archive.write(data / "master.key", "data/master.key")
    for directory, target in ((uploads, "uploads"), (data / "branding", "branding")):
        for path in directory.glob("*"):
            if path.is_file():
                archive.write(path, "data/" + target + "/" + path.name)
os.chmod(output, 0o600)
database_copy.unlink()
print(f"备份完成：{output}")
print("此备份包含用户文件和主密钥，必须按敏感数据保护；环境变量主密钥需另行安全备份。")
