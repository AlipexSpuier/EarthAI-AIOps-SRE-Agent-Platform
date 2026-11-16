import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
output = root.parent / "EarthAI-source.zip"
excluded = {".venv", "node_modules", "data", "backups", "__pycache__", ".pytest_cache", ".ruff_cache", ".git"}
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in excluded]
        for name in sorted(files):
            if name == ".env" or name.endswith(".pyc"):
                continue
            path = Path(directory) / name
            archive.write(path, path.relative_to(root.parent))
print(f"Created {output} ({output.stat().st_size:,} bytes)")
