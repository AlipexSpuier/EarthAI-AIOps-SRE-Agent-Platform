from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "frontend" / "public" / "vendor" / "docs"
PACKAGES = {
    "swagger-ui-dist": {
        "version": "5.34.0",
        "directory": "swagger-ui",
        "files": ["swagger-ui-bundle.js", "swagger-ui.css", "LICENSE", "NOTICE"],
    },
    "redoc": {
        "version": "2.5.4",
        "directory": "redoc",
        "files": ["bundles/redoc.standalone.js", "LICENSE"],
    },
}


def download(url):
    return subprocess.run(
        ["curl", "-fsSL", "--retry", "2", "--retry-all-errors", "--max-time", "120", url],
        check=True, capture_output=True,
    ).stdout


def main():
    manifest = []
    for name, package in PACKAGES.items():
        version = package["version"]
        metadata = json.loads(download(f"https://registry.npmjs.org/{name}/{version}"))
        source = metadata["dist"]["tarball"]
        data = download(source)
        algorithm, expected = metadata["dist"]["integrity"].split("-", 1)
        actual = base64.b64encode(hashlib.new(algorithm, data).digest()).decode()
        if actual != expected:
            raise ValueError(f"Package integrity mismatch: {name}")
        directory = DESTINATION / package["directory"]
        directory.mkdir(parents=True, exist_ok=True)
        files = []
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for relative in package["files"]:
                content = archive.extractfile("package/" + relative).read()
                if name == "redoc" and relative.endswith("redoc.standalone.js"):
                    old_url = b"https://cdn.redoc.ly/redoc/logo-mini.svg"
                    if content.count(old_url) != 1:
                        raise ValueError("Unexpected ReDoc logo reference")
                    content = content.replace(old_url, b"/vendor/docs/redoc/logo-mini.svg")
                target = directory / Path(relative).name
                target.write_bytes(content)
                files.append({"path": target.relative_to(ROOT).as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        if name == "redoc":
            logo_source = "https://cdn.redoc.ly/redoc/logo-mini.svg"
            logo = download(logo_source)
            if b"<svg" not in logo[:1000]:
                raise ValueError("Expected ReDoc SVG logo")
            target = directory / "logo-mini.svg"
            target.write_bytes(logo)
            files.append({"path": target.relative_to(ROOT).as_posix(), "source": logo_source, "bytes": len(logo), "sha256": hashlib.sha256(logo).hexdigest()})
        manifest.append({"package": name, "version": version, "license": metadata["license"], "source": source, "integrity": metadata["dist"]["integrity"], "files": files})
        print(f"Saved {name}@{version}: {len(files)} files")
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
