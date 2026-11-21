"""Farbige Emoji-Icons (rund) und kleine Grafiken (Checkbox, Pfeil) mit Pillow – für
Oberfläche und PDF. Ohne Pillow bzw. Emoji-Schrift liefern die Funktionen None und die
Aufrufer fallen auf einfache Text-Emojis zurück."""
import io
import os
from functools import lru_cache

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:          # App läuft auch ohne Pillow (dann schlichtere Icons)
    Image = None

_EMOJI_FONTS = (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguiemj.ttf"),
                "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
EMOJI_FONT = next((p for p in _EMOJI_FONTS if os.path.exists(p)), None)
HAS_PIL = Image is not None
HAS_EMOJI = HAS_PIL and EMOJI_FONT is not None
SS = 4  # Supersampling → glatte Kanten


@lru_cache(maxsize=64)
def _font(size):
    return ImageFont.truetype(EMOJI_FONT, size)


@lru_cache(maxsize=512)
def emoji(ch, size, circle=None, ring=None):
    """RGBA-Bild size×size mit farbigem Emoji, optional auf rundem Hintergrund (Hex-Farbe)."""
    if not HAS_EMOJI or size < 4:
        return None
    big = size * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if circle:
        d.ellipse((0, 0, big - 1, big - 1), fill=circle, outline=ring,
                  width=max(SS, big // 20) if ring else 0)
    # Zusammengesetzte Emojis (z. B. Köchin = Frau + Pfanne) kann Pillow ohne Raqm nicht setzen –
    # es malte beide Zeichen nebeneinander über den Rand. Dann nur das letzte, das Sachzeichen.
    ch = ch.split("\u200d")[-1]
    try:
        d.text((big / 2, big / 2), ch.replace("\ufe0f", ""), font=_font(int(big * (0.56 if circle else 0.9))),
               embedded_color=True, anchor="mm")
    except Exception:
        return None
    return im.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=32)
def checkbox(size, fill, border, mark=None):
    """Eckige Checkbox; mark = Farbe des Hakens (None = leer)."""
    if not HAS_PIL:
        return None
    big = size * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, big - 1, big - 1), fill=fill, outline=border, width=max(SS, round(big * 0.1)))
    if mark:
        d.line([(big * 0.24, big * 0.52), (big * 0.43, big * 0.71), (big * 0.77, big * 0.31)],
               fill=mark, width=round(big * 0.13), joint="curve")
    return im.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=16)
def chevron(size, color, up=False):
    """Kleiner Pfeil (Combobox/Spinbox)."""
    if not HAS_PIL:
        return None
    big = size * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ys = (0.68, 0.34) if up else (0.34, 0.68)
    ImageDraw.Draw(im).line([(big * 0.14, big * ys[0]), (big * 0.5, big * ys[1]), (big * 0.86, big * ys[0])],
                            fill=color, width=round(big * 0.17), joint="curve")
    return im.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=32)
def field(size, fill, border, width, height=None):
    """Eckiges Eingabefeld (9-Slice-Vorlage für ttk-Elemente); ohne height quadratisch."""
    if not HAS_PIL:
        return None
    h = height or size
    im = Image.new("RGBA", (size, h), fill)
    ImageDraw.Draw(im).rectangle((0, 0, size - 1, h - 1), outline=border, width=width)
    return im


@lru_cache(maxsize=8)
def heading(w, h, fill, line, sep, lw, inset):
    """Tabellenkopf: Fläche, Linie unten (lw) und kurzer Trenner rechts (9-Slice-Vorlage)."""
    if not HAS_PIL:
        return None
    im = Image.new("RGBA", (w, h), fill)
    d = ImageDraw.Draw(im)
    d.rectangle((0, h - lw, w - 1, h - 1), fill=line)
    d.line((w - 1, inset, w - 1, h - lw - inset - 1), fill=sep)
    return im


def png(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()
