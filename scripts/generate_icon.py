"""
One-off generator for the PWA app icon(s) - a simple yellow rounded-square
with a bold dark-green "TT" monogram, matching the site's jersey color
scheme (--geel #FFD700 / --groen #2E8B3D). Run once; output is checked in
under docs/icons/, no need to re-run unless the design changes.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "icons"

GEEL = (255, 215, 0)
GROEN = (46, 139, 61)
FONT_PATH = r"C:\Windows\Fonts\segoeuib.ttf"

SIZES = [192, 512]


def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=GEEL)

    font = ImageFont.truetype(FONT_PATH, int(size * 0.46))
    text = "TT"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pos = ((size - text_w) / 2 - bbox[0], (size - text_h) / 2 - bbox[1])
    draw.text(pos, text, font=font, fill=GROEN)

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        icon = make_icon(size)
        path = OUT_DIR / f"icon-{size}.png"
        icon.save(path)
        print(f"Wrote {path}")

    favicon = make_icon(64)
    favicon_path = ROOT / "docs" / "favicon.ico"
    favicon.save(favicon_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print(f"Wrote {favicon_path}")


if __name__ == "__main__":
    main()
