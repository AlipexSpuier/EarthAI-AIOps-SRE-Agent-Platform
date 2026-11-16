from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def migrate(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if source == destination or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("原目录与本地状态目录必须分离，不能互相包含")
    database = source / "earthai.db"
    if not database.is_file():
        raise ValueError("原目录没有 earthai.db")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("本地状态目录必须为空，拒绝覆盖任何文件")
    key = source / "master.key"
    if not key.is_file() and not os.getenv("EARTHAI_MASTER_KEY"):
        raise ValueError("未找到原 master.key，也未提供 EARTHAI_MASTER_KEY。请安全保留原密钥，不能生成替代密钥。")
    with sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("原数据库检查未通过，请先从备份恢复")
        active = db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running','waiting_approval')").fetchone()[0]
        if active:
            raise ValueError("仍有活动任务，请先停止或完成并关闭平台后迁移")
        destination.mkdir(parents=True, exist_ok=True)
        destination.chmod(0o700)
        target = destination / "earthai.db"
        with sqlite3.connect(target) as output:
            db.backup(output)
            if output.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("复制后的数据库检查失败，不应启用新配置")
    target.chmod(0o600)
    if key.is_file():
        shutil.copy2(key, destination / "master.key")
        (destination / "master.key").chmod(0o600)
    if (source / "branding").is_dir():
        shutil.copytree(source / "branding", destination / "branding")
    return {"ok": True, "database": str(target), "key_file_preserved": key.is_file(), "branding_preserved": (destination / "branding").is_dir(), "uploads_left_at": str(source / "uploads"), "source_untouched": True}


def main():
    parser = argparse.ArgumentParser(description="停机后将 EarthAI 数据库、主密钥、品牌图片复制到本地盘；上传文件继续留在NAS。")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--confirm-stopped", action="store_true")
    args = parser.parse_args()
    if not args.confirm_stopped:
        parser.error("必须先停止平台容器并备份，再传 --confirm-stopped；程序无法替代你确认远端容器已停止")
    try:
        print(json.dumps(migrate(args.source, args.destination), ensure_ascii=False, indent=2))
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
