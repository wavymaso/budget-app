"""Draw the Budget app icon (Campo): macos/Budget.icns for the Mac app, the web app's icons in
static/, the iPhone app's icon and windows/Budget.ico (needs Pillow + macOS iconutil).

    .venv/bin/python macos/make_icon.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
SIZE = 1024
BODY = 824                      # Apple's icon grid: 824px rounded square on a 1024 canvas
RADIUS = 185
FIELD, DEEP = (29, 106, 72), (21, 82, 56)       # Campo: the Verde field and its deeper disc (static/theme.js)


def _font(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size)
    try:
        font.set_variation_by_name("Black")
    except (OSError, ValueError):
        pass
    return font


def draw_square(px: int = SIZE) -> Image.Image:
    """The icon as a full square: the field, the deeper disc off the corner, a white disc with the €."""
    img = Image.new("RGBA", (px, px), FIELD + (255,))
    d = ImageDraw.Draw(img)
    k = px / SIZE
    d.ellipse((900 * k - 560 * k, 80 * k - 560 * k, 900 * k + 560 * k, 80 * k + 560 * k), fill=DEEP)
    r = 300 * k
    d.ellipse((px / 2 - r, px / 2 - r, px / 2 + r, px / 2 + r), fill="white")
    d.text((px / 2, px / 2 + 8 * k), "€", font=_font(round(380 * k)), fill=FIELD, anchor="mm")
    return img


def draw() -> Image.Image:
    """The Mac icon: the square on Apple's icon grid, rounded, with a soft shadow."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    off = (SIZE - BODY) // 2
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((off, off + 12, off + BODY, off + BODY + 12), RADIUS, fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    mask = Image.new("L", (BODY, BODY), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, BODY - 1, BODY - 1), RADIUS, fill=255)
    img.paste(draw_square(BODY), (off, off), mask)
    return img


def main() -> None:
    icon = draw()
    icon.save(HERE / "icon.png")
    iconset = Path(tempfile.mkdtemp()) / "Budget.iconset"
    iconset.mkdir()
    for px in (16, 32, 128, 256, 512):
        icon.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
        icon.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "Budget.icns")], check=True)
    shutil.rmtree(iconset.parent)

    # Phones, the web app and the iPhone app round the corners themselves: full squares.
    square = draw_square().convert("RGB")
    static = HERE.parent / "static"
    square.resize((180, 180), Image.LANCZOS).save(static / "apple-touch-icon.png", optimize=True)
    square.resize((192, 192), Image.LANCZOS).save(static / "icon-192.png", optimize=True)
    square.resize((512, 512), Image.LANCZOS).save(static / "icon-512.png", optimize=True)
    ios = HERE.parent / "ios" / "Budget" / "Assets.xcassets" / "AppIcon.appiconset" / "icon-1024.png"
    square.save(ios, optimize=True)
    # Windows: the rounded icon at the sizes Explorer and the taskbar use.
    draw().save(HERE.parent / "windows" / "Budget.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", HERE / "icon.png", HERE / "Budget.icns", "the web and iPhone icons, and windows/Budget.ico")


if __name__ == "__main__":
    main()
