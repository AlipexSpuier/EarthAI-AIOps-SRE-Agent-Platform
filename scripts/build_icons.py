from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
source = root.parent / "images" / "earthai-favicon.png"
public = root / "frontend" / "public"
public.mkdir(exist_ok=True)
with Image.open(source) as original:
    image = original.convert("RGBA")
    image.resize((512, 512), Image.Resampling.LANCZOS).save(public / "icon-512.png")
    image.resize((192, 192), Image.Resampling.LANCZOS).save(public / "icon-192.png")
    image.resize((180, 180), Image.Resampling.LANCZOS).save(public / "apple-touch-icon.png")
    image.resize((32, 32), Image.Resampling.LANCZOS).save(public / "favicon-32.png")
    image.resize((256, 256), Image.Resampling.LANCZOS).save(public / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
print("Created favicon.ico, favicon-32.png and application icons")
