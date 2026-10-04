"""Draw the Budget app icon and build macos/Budget.icns (needs Pillow + macOS iconutil).

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
TOP, BOTTOM = (51, 65, 85), (15, 23, 42)       # slate-700 -> slate-900
ACCENT = (52, 211, 153)                          # emerald-400


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    off = (SIZE - BODY) // 2

    # Soft drop shadow.
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((off, off + 12, off + BODY, off + BODY + 12), RADIUS, fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))

    # Vertical gradient body.
    grad = Image.new("RGBA", (BODY, BODY))
    gd = ImageDraw.Draw(grad)
    for y in range(BODY):
        t = y / (BODY - 1)
        gd.line([(0, y), (BODY, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (BODY, BODY), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, BODY - 1, BODY - 1), RADIUS, fill=255)
    img.paste(grad, (off, off), mask)

    d = ImageDraw.Draw(img)
    # Three rising bars along the bottom: a tiny budget chart.
    bar_w, gap, base = 70, 32, off + BODY - 130
    left = SIZE // 2 - (3 * bar_w + 2 * gap) // 2
    for i, h in enumerate((70, 115, 165)):
        x = left + i * (bar_w + gap)
        color = ACCENT if i == 2 else (148, 163, 184)
        d.rounded_rectangle((x, base - h, x + bar_w, base), 18, fill=color)

    # The euro sign.
    font = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 380, index=1)
    d.text((SIZE // 2, off + 250), "€", font=font, fill="white", anchor="mm")
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
    print("wrote", HERE / "icon.png", "and", HERE / "Budget.icns")


if __name__ == "__main__":
    main()
