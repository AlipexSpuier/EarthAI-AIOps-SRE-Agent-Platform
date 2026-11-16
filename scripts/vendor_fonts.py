from __future__ import annotations

import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "frontend" / "public" / "fonts"
SOURCE = "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400..700&family=Noto+Sans+SC:wght@400..700&display=swap"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
LICENSES = {
    "DM-Sans-OFL.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/dmsans/OFL.txt",
    "Noto-Sans-SC-OFL.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt",
}


def download(url):
    return subprocess.run(
        ["curl", "-fsSL", "--retry", "2", "--retry-all-errors", "--max-time", "120", "-A", USER_AGENT, url],
        check=True, capture_output=True,
    ).stdout


def main():
    css = download(SOURCE).decode("utf-8")
    urls = list(dict.fromkeys(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css)))
    if not urls or len(re.findall(r"@font-face\s*\{", css)) != len(urls):
        raise ValueError("Unexpected Google Fonts stylesheet")
    DESTINATION.mkdir(parents=True, exist_ok=True)

    def save(item):
        index, url = item
        content = download(url)
        if not content.startswith(b"wOF2"):
            raise ValueError("Expected WOFF2 font")
        name = f"font-{index:03d}.woff2"
        (DESTINATION / name).write_bytes(content)
        return {"source": url, "file": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    with ThreadPoolExecutor(max_workers=8) as pool:
        fonts = list(pool.map(save, enumerate(urls, 1)))
    for font in fonts:
        css = css.replace(font["source"], "/fonts/" + font["file"])
    if "https://" in css or "http://" in css:
        raise ValueError("External reference remains in fonts stylesheet")
    (DESTINATION / "fonts.css").write_text(css)
    for name, url in LICENSES.items():
        (DESTINATION / name).write_bytes(download(url))
    manifest = {"source": SOURCE, "families": ["DM Sans", "Noto Sans SC"], "weights": "400 700", "license": "SIL Open Font License 1.1", "files": fonts}
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved {len(fonts)} WOFF2 subsets ({sum(font['bytes'] for font in fonts):,} bytes), stylesheet and licenses")


if __name__ == "__main__":
    main()
