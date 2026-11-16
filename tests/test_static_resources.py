from html.parser import HTMLParser
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from backend.main import app

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "public"


class ResourceLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "script" and attributes.get("src"):
            self.links.append(attributes["src"])
        if tag == "link" and attributes.get("href"):
            self.links.append(attributes["href"])


@pytest.mark.parametrize("path,script", [
    ("/api/docs", "/vendor/docs/swagger-ui/swagger-ui-bundle.js"),
    ("/redoc", "/vendor/docs/redoc/redoc.standalone.js"),
])
def test_api_documentation_only_uses_local_resources(path, script):
    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        parser = ResourceLinks()
        parser.feed(response.text)
        assert script in parser.links
        assert "/favicon.ico" in parser.links
        assert "/api/openapi.json" in response.text
        assert all(link.startswith("/") and not link.startswith("//") for link in parser.links)
        assert "fonts.googleapis.com" not in response.text
        for resource in parser.links:
            asset = client.get(resource)
            assert asset.status_code == 200
            assert "text/html" not in asset.headers["content-type"]
            assert len(asset.content) > 100
        if path == "/api/docs":
            assert '"validatorUrl": null' in response.text


def test_documentation_openapi_and_oauth_routes():
    with TestClient(app) as client:
        schema = client.get("/api/openapi.json").json()
        assert schema["info"]["title"] == "EarthAI"
        assert "/api/health" in schema["paths"]
        assert not {"/api/docs", "/redoc", "/api/docs/oauth2-redirect"} & schema["paths"].keys()
        response = client.get("/api/docs/oauth2-redirect")
        assert response.status_code == 200
        assert "swaggerUIRedirectOauth2" in response.text


def test_documentation_honors_proxy_root_path():
    with TestClient(app, root_path="/earthai") as client:
        for path in ["/api/docs", "/redoc"]:
            response = client.get(path)
            parser = ResourceLinks()
            parser.feed(response.text)
            assert all(link.startswith("/earthai/") for link in parser.links)
            assert "/earthai/api/openapi.json" in response.text


def test_fonts_are_local_woff2_with_complete_subsets():
    source = (ROOT / "frontend" / "src" / "styles.css").read_text()
    assert "fonts.googleapis.com" not in source
    assert "fonts.gstatic.com" not in source
    css = (PUBLIC / "fonts" / "fonts.css").read_text()
    assert not re.search(r"(?:https?:)?//", css)
    assert "font-family: 'DM Sans'" in css
    assert "font-family: 'Noto Sans SC'" in css
    assert "font-weight: 400 700" in css
    assert "unicode-range:" in css
    fonts = re.findall(r"url\(([^)]+)\)", css)
    assert len(fonts) >= 100
    for font in fonts:
        assert font.startswith("/fonts/")
        assert (PUBLIC / font.lstrip("/")).read_bytes().startswith(b"wOF2")
    assert (PUBLIC / "fonts" / "DM-Sans-OFL.txt").is_file()
    assert (PUBLIC / "fonts" / "Noto-Sans-SC-OFL.txt").is_file()


def test_frontend_css_has_no_external_imports_or_resource_urls():
    redoc = (PUBLIC / "vendor" / "docs" / "redoc" / "redoc.standalone.js").read_text()
    assert "https://cdn.redoc.ly/redoc/logo-mini.svg" not in redoc
    assert "/vendor/docs/redoc/logo-mini.svg" in redoc
    assert b"<svg" in (PUBLIC / "vendor" / "docs" / "redoc" / "logo-mini.svg").read_bytes()[:1000]
    index = (ROOT / "frontend" / "index.html").read_text()
    assert 'href="/fonts/fonts.css"' in index
    for file in (ROOT / "frontend" / "src").rglob("*.css"):
        css = file.read_text()
        assert not re.search(r"@import\s+(?:url\()?\s*['\"]?(?:https?:)?//", css), file
        assert not re.search(r"url\(\s*['\"]?(?:https?:)?//", css), file
