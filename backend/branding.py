from __future__ import annotations

import re
from pathlib import Path

from . import store

FONTS = ("DM Sans", "Noto Sans SC", "system-ui", "serif", "monospace")
DEFAULT = {
    "name": "EarthAI", "subtitle": "WORKSPACE", "tagline": "智能运维 · 可靠执行",
    "icon_url": "", "favicon_url": "/favicon.ico",
    "title_font_family": "DM Sans", "title_font_size": 23, "title_color": "#253c34",
    "subtitle_font_family": "DM Sans", "subtitle_font_size": 8, "subtitle_color": "#76837b",
}


def get():
    with store.connect() as db:
        row = db.execute("SELECT value FROM platform_settings WHERE key='branding'").fetchone()
    return {**DEFAULT, **(store.loads(row["value"], {}) if row else {})}


def save(values):
    if not isinstance(values, dict) or set(values) - DEFAULT.keys():
        raise ValueError("界面配置字段无效")
    data = {**get(), **values}
    for key, maximum in (("name", 40), ("subtitle", 40), ("tagline", 120)):
        if not isinstance(data[key], str) or not 1 <= len(data[key].strip()) <= maximum:
            raise ValueError(f"{key} 不能为空且长度需小于{maximum}字符")
        data[key] = data[key].strip()
    for key in ("title_font_family", "subtitle_font_family"):
        if data[key] not in FONTS:
            raise ValueError("只能使用内置本地字体或系统字体")
    for key, minimum, maximum in (("title_font_size", 14, 40), ("subtitle_font_size", 6, 24)):
        if type(data[key]) is not int or not minimum <= data[key] <= maximum:
            raise ValueError(f"{key} 字号超出范围")
    for key in ("title_color", "subtitle_color"):
        if not isinstance(data[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", data[key]):
            raise ValueError("颜色需为六位十六进制值")
    for key in ("icon_url", "favicon_url"):
        value = data[key]
        if not isinstance(value, str) or (value not in {"", "/favicon.ico"} and not re.fullmatch(r"/api/branding/assets/[a-f0-9-]+\.(png|ico|webp|jpg)", value)):
            raise ValueError("图标只能选择已上传到本机的品牌图片")
    with store.connect() as db:
        db.execute("INSERT INTO platform_settings VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", ("branding", store.dumps(data), store.now()))
    return data


def save_asset(content):
    if not content or len(content) > 2 * 1024 * 1024:
        raise ValueError("品牌图片需小于2MB")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif content.startswith(b"\x00\x00\x01\x00"):
        extension = "ico"
    elif content.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        extension = "webp"
    else:
        raise ValueError("仅支持 PNG、ICO、JPEG、WebP，不允许脚本或SVG")
    directory = store.DATA / "branding"
    directory.mkdir(exist_ok=True)
    name = store.uid() + "." + extension
    (directory / name).write_bytes(content)
    return {"url": "/api/branding/assets/" + name}


def asset_path(name):
    if not re.fullmatch(r"[a-f0-9-]+\.(png|ico|webp|jpg)", name):
        raise ValueError("图片路径无效")
    return store.DATA / "branding" / Path(name).name
