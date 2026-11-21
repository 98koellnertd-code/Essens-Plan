"""A4-PDF im grauen Design: Seite 1 Wochenplan, danach die Einkaufsliste.
Die Schrift (Segoe UI) wird eingebettet – das PDF sieht auf jedem PC gleich aus."""
import datetime as dt
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepInFrame, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

import icons
from planner import (TAGE, _terms, dish_icon, eff_price, eur, fmt_amount, geschaetzt, recipe_offers,
                     sum_hint, totals, treue_text, vorher)
from recipes import TAG_LABEL, tags

HEAD1, HEAD2 = "#2b2f36", "#434a56"
BLUE, INK, SUB = "#374151", "#1f2430", "#6b7280"      # BLUE = Akzentfarbe (Überschriften, Balken), jetzt Grau
SOFT, LINE, BORDER, STRIPE = "#f3f4f6", "#e8ebef", "#dde1e7", "#f9fafb"
GREEN, GREEN_SOFT, SHADOW = "#16935f", "#e0f4ea", "#111827"
EXTRA_GRUPPE = "Extras & Notizen"
GROUP_ICONS = {"Vorrat prüfen": "🧂", "Ohne Angebot": "🛍️", EXTRA_GRUPPE: "✏️"}

W, H = A4
M = 14 * mm          # Seitenrand
BANNER = 30 * mm     # dunkles Kopfband
SM = 1.8 * mm        # Platz für den Schatten rund um Boxen
DY = 0.6 * mm        # Schatten-Versatz nach unten
hx = colors.HexColor

# ─── Schriften ────────────────────────────────────────────────────────────────
_FONTS = {"EP": ("segoeui.ttf", "Helvetica"), "EP-Bold": ("segoeuib.ttf", "Helvetica-Bold"),
          "EP-Semi": ("seguisb.ttf", "Helvetica-Bold"), "EP-Black": ("seguibl.ttf", "Helvetica-Bold")}
FONT = {}


def _register_fonts():
    """Segoe UI einbetten; fehlt sie (anderes System), auf Helvetica ausweichen."""
    if FONT:
        return FONT
    dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    for name, (file, fallback) in _FONTS.items():
        FONT[name] = fallback
        path = next((os.path.join(d, file) for d in dirs if os.path.exists(os.path.join(d, file))), None)
        if path:
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                FONT[name] = name
            except Exception:
                pass
    if FONT["EP"] == "EP":
        pdfmetrics.registerFontFamily("EP", normal="EP", bold=FONT["EP-Bold"],
                                      italic="EP", boldItalic=FONT["EP-Bold"])
    return FONT


def _styles():
    f = _register_fonts()
    base = ParagraphStyle("base", fontName=f["EP"], fontSize=9, leading=12, textColor=hx(INK))

    def st(name, **kw):
        return ParagraphStyle(name, parent=base, **kw)
    return {
        "small": st("small", fontSize=7.5, leading=9.8, textColor=hx(SUB)),
        "day": st("day", fontName=f["EP-Black"], fontSize=11.5, leading=13.5, textColor=hx(BLUE)),
        "date": st("date", fontName=f["EP-Semi"], fontSize=8, leading=10, textColor=hx(SUB)),
        "dish": st("dish", fontName=f["EP-Bold"], fontSize=12, leading=15),
        "meta": st("meta", fontName=f["EP-Semi"], fontSize=7.5, leading=10, textColor=hx(SUB), alignment=2),
        "cost": st("cost", fontName=f["EP-Black"], fontSize=11, leading=13.5, alignment=2),
        "label": st("label", fontName=f["EP-Semi"], fontSize=6.8, leading=9, textColor=hx(SUB)),
        "value": st("value", fontName=f["EP-Black"], fontSize=13, leading=16),
        "group": st("group", fontName=f["EP-Black"], fontSize=11, leading=13),
        "gmeta": st("gmeta", fontName=f["EP-Semi"], fontSize=8.5, leading=11, textColor=hx(BLUE), alignment=2),
        "qty": st("qty", fontSize=8.5, leading=11, textColor=hx(SUB)),
        "name": st("name", fontName=f["EP-Bold"], fontSize=9.5, leading=12),
        "price": st("price", fontName=f["EP-Bold"], fontSize=9.5, leading=12, alignment=2),
        "old": st("old", fontSize=8, leading=10, textColor=hx(SUB), alignment=2),
        "note": st("note", fontSize=7.5, leading=11, textColor=hx(SUB), leftIndent=SM, rightIndent=SM),
        "step": st("step", fontSize=8.5, leading=11.5, leftIndent=6.5 * mm, firstLineIndent=-6.5 * mm),
    }


# ─── Zeichen-Helfer ───────────────────────────────────────────────────────────
def _shadow(c, x, y, w, h, blur=SM, dy=DY, alpha=0.03, steps=7):
    """Weicher Schatten: gestapelte, halbtransparente abgerundete Flächen."""
    c.saveState()
    c.setFillColor(hx(SHADOW))
    c.setFillAlpha(alpha)
    for i in range(steps, 0, -1):
        g = blur * i / steps
        c.roundRect(x - g, y - dy - g, w + 2 * g, h + 2 * g, g, stroke=0, fill=1)
    c.restoreState()


def _rect(c, x, y, w, h, fill=None, stroke=None, width=0.6):
    c.saveState()
    if fill:
        c.setFillColor(hx(fill))
    if stroke:
        c.setStrokeColor(hx(stroke))
        c.setLineWidth(width)
    c.rect(x, y, w, h, stroke=1 if stroke else 0, fill=1 if fill else 0)
    c.restoreState()


_READERS = {}


def _icon(c, ch, x, y, size, circle=None):
    """Farbiges, rundes Emoji-Icon (ohne Emoji-Schrift nur der Kreis)."""
    key = (ch, circle)
    if key not in _READERS:
        im = icons.emoji(ch, 160, circle)
        _READERS[key] = ImageReader(im) if im is not None else None
    if _READERS[key]:
        c.drawImage(_READERS[key], x, y, size, size, mask="auto")
    elif circle:
        c.saveState()
        c.setFillColor(hx(circle))
        c.circle(x + size / 2, y + size / 2, size / 2, stroke=0, fill=1)
        c.restoreState()


def _fit(text, font, size, width):
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


# ─── Flowables ────────────────────────────────────────────────────────────────
class Card(Flowable):
    """Weiße, eckige Box mit weichem Schatten, optional farbiger Balken links."""
    ACCENT_W = 1.3 * mm
    MIN_PART = 28 * mm     # kleinere Reste nicht allein am Seitenende stehen lassen

    def __init__(self, inner, pad=3 * mm, accent=None, after=0.8 * mm):
        super().__init__()
        self.inner, self.pad, self.accent = inner, pad, accent
        self.spaceAfter = after

    def _left(self):
        return SM + (self.ACCENT_W if self.accent else 0) + self.pad

    def _avail(self, aw, ah):
        return aw - self._left() - SM - self.pad, ah - 2 * (SM + self.pad)

    def wrap(self, aw, ah):
        _, ih = self.inner.wrapOn(getattr(self, "canv", None), *self._avail(aw, ah))
        self.width, self.height = aw, ih + 2 * (SM + self.pad)
        return self.width, self.height

    def split(self, aw, ah):
        canv, avail = getattr(self, "canv", None), self._avail(aw, ah)
        parts = self.inner.splitOn(canv, *avail)
        if len(parts) < 2 or parts[0].wrapOn(canv, *avail)[1] < self.MIN_PART:
            return []
        return [Card(p, self.pad, self.accent, self.spaceAfter) for p in parts]

    def draw(self):
        c, w, h = self.canv, self.width - 2 * SM, self.height - 2 * SM
        _shadow(c, SM, SM, w, h)
        _rect(c, SM, SM, w, h, fill="#ffffff")
        if self.accent:
            _rect(c, SM, SM, self.ACCENT_W, h, fill=self.accent)
        self.inner.drawOn(c, self._left(), SM + self.pad)
        _rect(c, SM, SM, w, h, stroke=BORDER)


class Icon(Flowable):
    def __init__(self, ch, size, circle=None):
        super().__init__()
        self.ch, self.size, self.circle = ch, size, circle

    def wrap(self, aw, ah):
        return self.size, self.size

    def draw(self):
        _icon(self.canv, self.ch, 0, 0, self.size, self.circle)


class Box(Flowable):
    """Eckiges Kästchen zum Abhaken."""
    def __init__(self, size=3.6 * mm):
        super().__init__()
        self.size = size

    def wrap(self, aw, ah):
        return self.size, self.size

    def draw(self):
        _rect(self.canv, 0, 0, self.size, self.size, fill="#ffffff", stroke=BLUE, width=0.9)


class Chips(Flowable):
    """Eckige Zutaten-Chips, fließend umbrechend: [(text, alter_preis|None)].
    Standardfarbe grün (Angebot); für die Rezeptseiten wird auf Blau umgestellt."""
    FS, OLD_FS, CH = 7.4, 6.8, 4.4 * mm
    PX, BAR, GX, GY, OLD_GAP = 1.5 * mm, 0.6 * mm, 1.5 * mm, 1.2 * mm, 1.2 * mm

    def __init__(self, chips, fill=GREEN_SOFT, bar=GREEN, fg=GREEN):
        super().__init__()
        self.chips = chips
        self.fill, self.bar, self.fg = fill, bar, fg

    def _widths(self, text, old):
        tw = pdfmetrics.stringWidth(text, FONT["EP-Bold"], self.FS)
        ow = pdfmetrics.stringWidth(old, FONT["EP"], self.OLD_FS) + self.OLD_GAP if old else 0
        return tw, ow

    def wrap(self, aw, ah):
        self.layout, x, y = [], 0, 0
        for text, old in self.chips:
            tw, ow = self._widths(text, old)
            w = self.BAR + 2 * self.PX + tw + ow
            if w > aw:                                  # passt nie in eine Zeile → kürzen
                text, old = _fit(text, FONT["EP-Bold"], self.FS, aw - self.BAR - 2 * self.PX), None
                tw, ow = self._widths(text, old)
                w = self.BAR + 2 * self.PX + tw
            if x and x + w > aw:
                x, y = 0, y + self.CH + self.GY
            self.layout.append((x, y, w, tw, text, old))
            x += w + self.GX
        self.width, self.height = aw, (y + self.CH) if self.chips else 0
        return self.width, self.height

    def draw(self):
        c, f = self.canv, FONT
        for x, y, w, tw, text, old in self.layout:
            by = self.height - y - self.CH
            _rect(c, x, by, w, self.CH, fill=self.fill)
            _rect(c, x, by, self.BAR, self.CH, fill=self.bar)
            base = by + (self.CH - self.FS * 0.68) / 2
            tx = x + self.BAR + self.PX
            c.saveState()
            c.setFillColor(hx(self.fg))
            c.setFont(f["EP-Bold"], self.FS)
            c.drawString(tx, base, text)
            if old:
                ox = tx + tw + self.OLD_GAP
                c.setFillColor(hx(SUB))
                c.setFont(f["EP"], self.OLD_FS)
                c.drawString(ox, base, old)
                c.setStrokeColor(hx(SUB))
                c.setLineWidth(0.5)
                sy = base + self.OLD_FS * 0.3
                c.line(ox, sy, ox + pdfmetrics.stringWidth(old, f["EP"], self.OLD_FS), sy)
            c.restoreState()


class Tiles(Flowable):
    """Gleich hohe Kennzahl-Kacheln nebeneinander: [(emoji, titel, wert_markup, kreisfarbe)]."""
    ICON, PAD, GAP = 10 * mm, 3 * mm, 2 * SM

    def __init__(self, tiles, weights, st, after=1.6 * mm):
        super().__init__()
        self.tiles, self.weights, self.st = tiles, weights, st
        self.spaceAfter = after

    def wrap(self, aw, ah):
        boxes = aw - 2 * SM - self.GAP * (len(self.tiles) - 1)
        self.cols = [boxes * wt / sum(self.weights) for wt in self.weights]
        self.paras, inner = [], self.ICON
        for (_, title, value, _), cw in zip(self.tiles, self.cols):
            tw = cw - 2 * self.PAD - self.ICON - 2.8 * mm
            p1, p2 = Paragraph(escape(title.upper()), self.st["label"]), Paragraph(value, self.st["value"])
            h1, h2 = p1.wrap(tw, ah)[1], p2.wrap(tw, ah)[1]
            self.paras.append((p1, h1, p2, h2))
            inner = max(inner, h1 + h2)
        self.width, self.height = aw, inner + 2 * (self.PAD + SM)
        return self.width, self.height

    def draw(self):
        c, x, h = self.canv, SM, self.height - 2 * SM
        for (ch, _, _, circle), cw, (p1, h1, p2, h2) in zip(self.tiles, self.cols, self.paras):
            _shadow(c, x, SM, cw, h)
            _rect(c, x, SM, cw, h, fill="#ffffff")
            _icon(c, ch, x + self.PAD, SM + (h - self.ICON) / 2, self.ICON, circle)
            tx, ty = x + self.PAD + self.ICON + 2.8 * mm, SM + (h - h1 - h2) / 2
            p2.drawOn(c, tx, ty)
            p1.drawOn(c, tx, ty + h2)
            _rect(c, x, SM, cw, h, stroke=BORDER)
            x += cw + self.GAP


# ─── Seitenrahmen ─────────────────────────────────────────────────────────────
def _page(title, week, info, created):
    f = _register_fonts()

    def draw(c, doc):
        top = H - BANNER
        c.saveState()                                   # Schatten unter dem Kopfband
        c.setFillColor(hx(SHADOW))
        c.setFillAlpha(0.045)
        for i in range(1, 7):
            c.rect(0, top - i * 0.55 * mm, W, i * 0.55 * mm, stroke=0, fill=1)
        c.restoreState()

        c.saveState()                                   # Verlauf + dezente Ringe
        p = c.beginPath()
        p.rect(0, top, W, BANNER)
        c.clipPath(p, stroke=0, fill=0)
        c.linearGradient(0, H, W, top, (hx(HEAD1), hx(HEAD2)), extend=True)
        c.setStrokeColor(colors.white)
        c.setStrokeAlpha(0.09)
        for cx, cy, r, lw in ((W - 46 * mm, top - 6 * mm, 26 * mm, 9), (W - 8 * mm, H + 2 * mm, 17 * mm, 5),
                              (W * 0.56, H + 11 * mm, 17 * mm, 3)):
            c.setLineWidth(lw)
            c.circle(cx, cy, r, stroke=1, fill=0)
        c.restoreState()

        lg = 16 * mm                                    # rundes Logo mit Schatten
        ly = top + (BANNER - lg) / 2
        c.saveState()
        c.setFillColor(hx(SHADOW))
        c.setFillAlpha(0.07)
        for i in range(1, 5):
            c.circle(M + lg / 2, ly + lg / 2 - 0.5 * mm, lg / 2 + i * 0.35 * mm, stroke=0, fill=1)
        c.restoreState()
        _icon(c, "🍽️", M, ly, lg, "#ffffff")

        c.saveState()
        tx = M + lg + 5 * mm
        c.setFillColor(colors.white)
        c.setFont(f["EP-Black"], 22)
        c.drawString(tx, top + BANNER / 2 + 0.6 * mm, title)
        c.setFillColor(hx("#e5e7eb"))
        c.setFont(f["EP-Semi"], 10)
        c.drawString(tx, top + BANNER / 2 - 5.4 * mm, week)
        c.setFillColor(colors.white)
        c.setFont(f["EP-Semi"], 9)
        y = top + BANNER / 2 + (len(info) - 1) * 2.4 * mm - 1.2 * mm
        for line in info:
            c.drawRightString(W - M, y, _fit(line, f["EP-Semi"], 9, 80 * mm))
            y -= 4.8 * mm

        c.setStrokeColor(hx(LINE))                      # Fußzeile
        c.setLineWidth(0.6)
        c.line(M, 11 * mm, W - M, 11 * mm)
        c.setFont(f["EP"], 7.5)
        c.setFillColor(hx(SUB))
        c.drawString(M, 7 * mm, f"Essens-Plan  ·  erstellt am {created}")
        c.drawRightString(W - M, 7 * mm, f"Seite {doc.page}")
        c.restoreState()
    return draw


# ─── Rezeptseiten ─────────────────────────────────────────────────────────────
def _plain(rows, cw, extra=()):
    """Tabelle ohne Rahmen und Abstände – nur zum Anordnen."""
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0), *extra]))
    return t


def _lead(label, first, st, iw):
    """Überschrift und erste Zeile darunter in einer Tabellenzeile. Muss eine Karte doch
    einmal umbrechen, bleibt so kein „ZUBEREITUNG“ allein am Seitenende stehen."""
    return _plain([[Paragraph(label, st["label"])], [first]], [iw],
                  [("BOTTOMPADDING", (0, 0), (0, 0), 1.8 * mm)])


def _recipe_cards(plan, monday, by_name, factor, cfg, st, iw, tage_aktiv=range(7)):
    """Für jedes geplante Gericht eine Karte mit Zutaten und Zubereitung."""
    f, order, tage = FONT, [], {}
    for i in tage_aktiv:
        name = plan.get((monday + dt.timedelta(days=i)).isoformat(), "")
        if name in by_name:
            if name not in tage:
                order.append(name)
                tage[name] = []
            tage[name].append(TAGE[i])
    cards = []
    for name in order:
        r = by_name[name]
        kopf = [", ".join(tage[name])]
        if r.get("d"):
            kopf.append(f"ca. {r['d']} Min")
        kopf.append(f"{cfg.get('personen', 2)} Personen")
        if r.get("t"):
            kopf.append(escape(", ".join(TAG_LABEL.get(t, t) for t in tags(r))))
        head = _plain([[Icon(dish_icon(r), 11 * mm, SOFT),
                        [Paragraph(escape(name), st["dish"]),
                         Paragraph("  ·  ".join(kopf), st["small"])]]],
                      [14 * mm, iw - 14 * mm])
        rows = [[head]]
        zut = [(f"{fmt_amount(z[1] * factor, z[2])} {z[0]}".strip(), None) for z in r.get("z", [])]
        if zut:
            rows.append([_lead("ZUTATEN", Chips(zut, fill=SOFT, bar=BLUE, fg=INK), st, iw)])
        if r.get("a"):
            steps = [Paragraph(f'<font name="{f["EP-Black"]}" color="{BLUE}">{i}</font>   ' + escape(s),
                               st["step"]) for i, s in enumerate(r["a"], 1)]
            rows.append([_lead("ZUBEREITUNG", steps[0], st, iw)])
            rows += [[p] for p in steps[1:]]
        t = Table(rows, colWidths=[iw])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("TOPPADDING", (0, 1), (-1, -1), 1.8 * mm)]))
        # KeepTogether schiebt eine Karte lieber auf die nächste Seite, als sie zu zerreißen –
        # beim Kochen will niemand die Hälfte eines Rezepts umblättern.
        cards.append(KeepTogether(Card(t, accent=BLUE, after=1.6 * mm)))
    return cards


# ─── Export ───────────────────────────────────────────────────────────────────
def export(path, title, monday, plan, recipes, offers, cfg, items, tage=None, extras=None):
    """items: nur die angehakten Artikel der Einkaufsliste; extras: angehakte Extra-Produkte und Notizen;
    tage: aktive Wochentage (0 = Montag), None = alle sieben."""
    tage = list(range(7)) if tage is None else sorted(set(tage))
    extras = list(extras or [])
    st, f = _styles(), FONT
    by_name = {r["n"]: r for r in recipes}
    factor = max(1, int(cfg.get("personen", 2))) / 2
    fw, fh = W - 2 * M + 2 * SM, H - BANNER - 6 * mm - 15 * mm

    # ── Seite 1: Wochenplan ───────────────────────────────────────────────────
    days, total, before, hits, need, used = [], 0.0, 0.0, 0, 0, set()
    iw = fw - 2 * SM - Card.ACCENT_W - 6 * mm
    for i in tage:
        d = monday + dt.timedelta(days=i)
        name = plan.get(d.isoformat(), "")
        r = by_name.get(name)
        chips, other, d_hits, d_need, d_cost = [], [], 0, 0, 0.0
        for z, o in (recipe_offers(r, offers, cfg) if r else []):
            if _terms(z):
                d_need += 1
            amount = f"{fmt_amount(z[1] * factor, z[2])} {z[0]}".strip()
            if not o:
                other.append(escape(amount))
                continue
            p, v = eff_price(o, cfg), vorher(o, cfg)
            chips.append((f"{amount} · {o['haendler']} {eur(p)}", eur(v, geschaetzt(o, cfg)) if v else None))
            total, before, d_cost, d_hits = total + p, before + (v or p), d_cost + p, d_hits + 1
            used.add(o["haendler"])
        hits, need = hits + d_hits, need + d_need
        body = [Paragraph(escape(name) or "–", st["dish"]), Spacer(0, 1 * mm)]
        if not r:
            body.append(Paragraph("Noch kein Gericht geplant" if not name
                                  else f"Rezept „{escape(name)}“ nicht gefunden", st["small"]))
        else:
            body.append(Chips(chips) if chips else Paragraph("Keine Zutat im Angebot", st["small"]))
            if other:
                body += [Spacer(0, 1.1 * mm),
                         Paragraph(f'<font name="{f["EP-Semi"]}" color="{INK}">Sonst:</font> '
                                   + ", ".join(other), st["small"])]
        meta = [Paragraph(f"{d_hits}/{d_need} im Angebot", st["meta"]),
                Paragraph(eur(d_cost), st["cost"])] if d_hits else ""
        row = Table([[Icon(dish_icon(r), 11 * mm, SOFT),
                      [Paragraph(TAGE[i], st["day"]), Paragraph(f"{d:%d.%m.%Y}", st["date"])],
                      body, meta]],
                    colWidths=[14 * mm, 25 * mm, iw - 66 * mm, 27 * mm])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (2, 0), (2, 0), 1 * mm), ("LEFTPADDING", (3, 0), (3, 0), 2 * mm),
        ]))
        days.append(Card(row, accent=BLUE))

    tiles = Tiles([("🏪", "Einkauf bei", escape(" + ".join(sorted(used))) or "–", SOFT),
                   ("🏷️", "Zutaten im Angebot", f"{hits} von {need}" if need else "–", SOFT),
                   ("💶", "ca. Kosten", eur(total) if hits else "–", SOFT),
                   ("💰", "Gespart", f'<font color="{GREEN}">{eur(before - total)}</font>' if hits else "–",
                    GREEN_SOFT)], [1.45, 1.25, 1, 1], st)
    legend = Paragraph(f'<font name="{f["EP-Bold"]}" color="{GREEN}">Grün</font> = Zutat ist diese Woche im '
                       f"Angebot (Menge · Händler · Preis)  ·  <strike>1,99 €</strike> = Normalpreis  ·  "
                       f"~ = geschätzt aus dem Ø der Kategorie", st["note"])
    plan_page = KeepInFrame(fw, fh - 2, [tiles, *days, Spacer(0, 1.2 * mm), legend], mode="shrink")

    # ── Einkaufsliste ─────────────────────────────────────────────────────────
    ex_preise = []
    for x in extras:
        a = x.get("angebot")
        if a and a.get("preis") is not None:
            ex_preise.append({"preis": a["preis"], "vorher": a.get("vorher"),
                              "geschaetzt": bool(a.get("geschaetzt"))})
    now, bef, saved, est, unknown = totals(list(items) + ex_preise)
    story = [Tiles([("💶", "Summe Angebote", eur(now) if now else f"{len(items) + len(extras)} Artikel", SOFT),
                    ("🧾", "Normalpreis", eur(bef, est) if now else "–", SOFT),
                    ("💰", "Gespart", (f'<font color="{GREEN}">{eur(saved, est)}</font>'
                                      f'<font size="9" color="{GREEN}">  ({saved / bef * 100:.0f} %)</font>')
                     if now and bef else "–", GREEN_SOFT)], [1, 1, 1], st, after=2.4 * mm)]
    groups = {}
    for it in items:
        key = ("Vorrat prüfen" if it["vorrat"] else
               it["angebot"]["haendler"] if it["angebot"] else "Ohne Angebot")
        groups.setdefault(key, []).append(it)
    cw = [12 * mm, 18 * mm, 40 * mm, 0, 17 * mm, 17 * mm]
    cw[3] = W - 2 * M - sum(cw)
    if extras:
        groups[EXTRA_GRUPPE] = extras
    for g, its in groups.items():
        ist_extra = g == EXTRA_GRUPPE
        notizen = []                 # Zeilen, in denen der Notiztext über zwei Spalten läuft
        sub = totals(ex_preise if ist_extra else its)[0]
        rows = [[Icon(GROUP_ICONS.get(g, "🏪"), 6.5 * mm, "#ffffff"), Paragraph(escape(g), st["group"]), "", "",
                 Paragraph(f"{len(its)} " + ("Einträge" if ist_extra else "Artikel")
                           + (f"  ·  {eur(sub)}" if sub else ""), st["gmeta"]), ""]]
        for it in its:
            if ist_extra:
                a = it.get("angebot")
                if it["typ"] == "notiz":
                    notizen.append(len(rows))
                    rows.append([Box(), Paragraph("Notiz", st["qty"]), Paragraph(escape(it["text"]), st["name"]),
                                 "", "", ""])
                    continue
                info = (escape(f"{a['haendler']}: {a['produkt']}" + (f" {a['info']}" if a.get("info") else ""))
                        if a else "")
                p, v = (a.get("preis"), a.get("vorher")) if a else (None, None)
                rows.append([Box(), Paragraph("Extra", st["qty"]), Paragraph(escape(it["text"]), st["name"]),
                             Paragraph(info, st["small"]),
                             Paragraph(eur(p) if p is not None else "", st["price"]),
                             Paragraph(f"<strike>{eur(v, a.get('geschaetzt'))}</strike>" if v else "", st["old"])])
                continue
            o = it["angebot"]
            if o:
                info = f"{escape(o['produkt'])} {escape(o['info'])}".strip()
                tt = treue_text(o, cfg).replace("✔ ", "")
                if tt:
                    info += f' <font name="{f["EP-Bold"]}" color="{BLUE}">{escape(tt)}</font>'
            else:
                info = "für " + escape(", ".join(sorted(set(it["gerichte"]))))
            rows.append([Box(), Paragraph(escape(it["menge"]), st["qty"]),
                         Paragraph(escape(it["name"]), st["name"]), Paragraph(info, st["small"]),
                         Paragraph(eur(it["preis"]) if o else "", st["price"]),
                         Paragraph(f"<strike>{eur(it['vorher'], it['geschaetzt'])}</strike>"
                                   if it["vorher"] else "", st["old"])])
        t = Table(rows, colWidths=cw, repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("SPAN", (1, 0), (3, 0)), ("SPAN", (4, 0), (5, 0)),
            *[("SPAN", (2, r), (3, r)) for r in notizen],
            ("BACKGROUND", (0, 0), (-1, 0), hx(SOFT)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, hx(STRIPE)]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, hx(BORDER)),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, hx(LINE)),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
            ("TOPPADDING", (0, 0), (-1, 0), 4.5), ("BOTTOMPADDING", (0, 0), (-1, 0), 4.5),
            ("LEFTPADDING", (0, 0), (0, -1), 3.2 * mm),
            ("RIGHTPADDING", (4, 0), (4, 0), 3.5 * mm), ("RIGHTPADDING", (-1, 1), (-1, -1), 3.5 * mm),
        ]))
        story.append(Card(t, pad=0, after=1.6 * mm))
    if not items and not extras:
        story.append(Paragraph("Noch keine Einkaufsliste – zuerst einen Plan generieren.", st["note"]))
    hint = sum_hint(est, unknown)
    story.append(Paragraph("Je 1 Packung pro Artikel  ·  Preise inkl. deiner Treue-Programme  ·  "
                           "~ = geschätzt aus dem Ø-Grundpreis der Kategorie"
                           + (f"  ·  {escape(hint)}" if hint else ""), st["note"]))

    # ── Dokument ──────────────────────────────────────────────────────────────
    stores = sorted({it["angebot"]["haendler"] for it in items if it["angebot"]}
                    | {x["angebot"]["haendler"] for x in extras if x.get("angebot")})
    info = [f"{cfg.get('personen', 2)} Personen" + (f"  ·  PLZ {cfg['plz']}" if cfg.get("plz") else "")]
    if stores:
        info.append("Einkauf bei " + " + ".join(stores))
    created = f"{dt.date.today():%d.%m.%Y}"

    def frame(fid):
        return Frame(M - SM, 15 * mm, fw, fh, leftPadding=0, rightPadding=0,
                     topPadding=0, bottomPadding=0, id=fid)
    doc = BaseDocTemplate(path, pagesize=A4, title=f"Essensplan {title}", author="Essens-Plan",
                          leftMargin=M, rightMargin=M, topMargin=BANNER + 6 * mm, bottomMargin=15 * mm)
    doc.addPageTemplates([
        PageTemplate("plan", [frame("plan")], onPage=_page("Essensplan", title, info, created)),
        PageTemplate("list", [frame("list")], onPage=_page("Einkaufsliste", title, info, created)),
        PageTemplate("rezepte", [frame("rezepte")],
                     onPage=_page("Rezepte der Woche", title, info, created))])
    rez = _recipe_cards(plan, monday, by_name, factor, cfg, _styles(),
                        fw - 2 * SM - Card.ACCENT_W - 6 * mm, tage) if cfg.get("pdf_rezepte", True) else []
    doc.build([plan_page, NextPageTemplate("list"), PageBreak(), *story]
              + ([NextPageTemplate("rezepte"), PageBreak(), *rez] if rez else []))
