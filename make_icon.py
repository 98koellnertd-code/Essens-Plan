"""Erzeugt res/icon.ico (Programmsymbol) aus dem Teller-Emoji auf blauem Verlauf.

Aufruf:  py -3 make_icon.py
Braucht Pillow; wird nur beim Entwickeln/Bauen gebraucht, nicht zur Laufzeit.
"""
import os
import sys

from PIL import Image, ImageDraw

import icons
from utils import _BUNDLE_DIR

OUT = os.path.join(_BUNDLE_DIR, "res", "icon.ico")
SIZES = (16, 24, 32, 48, 64, 128, 256)
TOP, BOTTOM = (61, 134, 232), (26, 77, 158)   # Blau wie im Kopfbereich der App


def tile(size):
    """Abgerundetes Quadrat mit Farbverlauf und Teller-Emoji."""
    ss = 4 if size < 64 else 2                       # überabtasten → glatte Kanten
    w = size * ss
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    grad = Image.new("RGBA", (w, w))
    d = ImageDraw.Draw(grad)
    for y in range(w):
        t = y / max(1, w - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, w - 1], radius=round(w * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    # feine Lichtkante oben
    ImageDraw.Draw(img).arc([round(w * 0.06), round(w * 0.06), round(w * 0.94), round(w * 0.94)],
                            200, 340, fill=(255, 255, 255, 90), width=max(1, round(w * 0.012)))
    glyph = icons.emoji("🍽️", round(w * 0.62))
    if glyph is None:
        raise SystemExit("Emoji-Schrift nicht gefunden (seguiemj.ttf) – Icon nicht erzeugt.")
    img.alpha_composite(glyph, ((w - glyph.width) // 2, (w - glyph.height) // 2))
    return img.resize((size, size), Image.LANCZOS)


def main():
    if not icons.HAS_PIL:
        raise SystemExit("Pillow fehlt: py -3 -m pip install pillow")
    imgs = [tile(s) for s in SIZES]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    big = imgs[-1]
    try:
        big.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    except TypeError:                                 # ältere Pillow-Version
        big.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"geschrieben: {OUT}  ({os.path.getsize(OUT)} Bytes, {len(SIZES)} Größen)")
    png = OUT.replace(".ico", ".png")
    big.save(png)
    print(f"geschrieben: {png}")


if __name__ == "__main__":
    sys.exit(main())
