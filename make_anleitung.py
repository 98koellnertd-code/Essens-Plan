"""Erzeugt Anleitung.pdf – die bebilderte Kurzanleitung, die mit der EXE verschickt wird.

Aufruf:   py -3 make_anleitung.py [Ausgabepfad]        (Standard: dist\\Anleitung.pdf)

Das Skript ist bewusst eigenständig: es importiert keine Programm-Module (die würden den
Datenordner anlegen), startet kein Tk und schreibt nur die eine PDF-Datei.
Gestaltung und Schrift (Segoe UI, eingebettet) passen zu pdf_export.py."""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, NextPageTemplate,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

VERSION = "1.6.0"
TITEL = "Essens-Plan"
UNTERTITEL = "Wochenplan aus den aktuellen Supermarkt-Angeboten"

# ─── Farben (wie pdf_export.py) ───────────────────────────────────────────────
HEAD1, HEAD2 = "#374151", "#6b7280"
BANNER_BG = "#2b2f36"
BLUE, INK, SUB = "#374151", "#1f2937", "#6b7280"
SOFT, LINE, BORDER, STRIPE = "#f3f4f6", "#e5e7eb", "#dde1e7", "#f9fafb"
GREEN, GREEN_SOFT = "#16935f", "#e0f4ea"
AMBER, AMBER_SOFT = "#b7791f", "#fdf3dc"
hx = colors.HexColor

W, H = A4
M = 18 * mm            # Seitenrand
BANNER = 50 * mm       # Höhe des Kopfbands auf Seite 1
CONTENT_W = W - 2 * M

# ─── Schriften (wie pdf_export._register_fonts) ───────────────────────────────
_FONTS = {"EP": ("segoeui.ttf", "Helvetica"), "EP-Bold": ("segoeuib.ttf", "Helvetica-Bold"),
          "EP-Semi": ("seguisb.ttf", "Helvetica-Bold"), "EP-Black": ("seguibl.ttf", "Helvetica-Bold")}
FONT = {}


def register_fonts():
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


def make_styles():
    f = register_fonts()
    base = ParagraphStyle("base", fontName=f["EP"], fontSize=10, leading=14.2, textColor=hx(INK))

    def st(name, **kw):
        return ParagraphStyle(name, parent=base, **kw)
    return {
        "body": st("body", spaceAfter=5),
        "lead": st("lead", fontSize=11, leading=15.6, textColor=hx(SUB), spaceAfter=6),
        "h2": st("h2", fontName=f["EP-Bold"], fontSize=11.2, leading=14, textColor=hx(HEAD1),
                 spaceBefore=6, spaceAfter=2, keepWithNext=1),
        "bullet": st("bullet", leftIndent=13, bulletIndent=2, spaceAfter=2.5, bulletFontName=f["EP-Bold"],
                     bulletColor=hx(BLUE)),
        "step_t": st("step_t", fontName=f["EP-Bold"], fontSize=11, leading=14, spaceAfter=1),
        "step": st("step", fontSize=9.8, leading=13.6, textColor=hx(INK)),
        "tip": st("tip", fontSize=9.6, leading=13.4),
        "th": st("th", fontName=f["EP-Bold"], fontSize=9.2, leading=12, textColor=colors.white),
        "td": st("td", fontSize=9.6, leading=13),
        "key": st("key", fontName=f["EP-Bold"], fontSize=9.4, leading=13, textColor=hx(HEAD1)),
        "cap": st("cap", fontSize=8.2, leading=11, textColor=hx(SUB), alignment=1),
        "small": st("small", fontSize=8.5, leading=11.5, textColor=hx(SUB)),
    }


S = None  # wird in build() gesetzt


# ─── Bausteine ────────────────────────────────────────────────────────────────
class Heading(Flowable):
    """Abschnittsüberschrift: dunkle Marke, großer Titel, feine Linie darunter."""

    def __init__(self, text, number=None):
        super().__init__()
        self.text, self.number = text, number
        self.keepWithNext = True
        self.height = 11 * mm

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.height + 3 * mm      # 3 mm Luft nach oben

    def draw(self):
        c, f = self.canv, FONT
        y0 = 0.5 * mm
        c.setStrokeColor(hx(BORDER))
        c.setLineWidth(1)
        c.line(0, y0, self.width, y0)
        c.setFillColor(hx(BLUE))
        c.roundRect(0, y0 + 2.2 * mm, 2.2 * mm, 6.4 * mm, 1 * mm, stroke=0, fill=1)
        c.setFillColor(hx(HEAD1))
        c.setFont(f["EP-Black"], 15.5)
        c.drawString(5 * mm, y0 + 3.4 * mm, self.text)


class NumBadge(Flowable):
    """Dunkler Kreis mit Schrittnummer."""

    def __init__(self, n, d=8.2 * mm):
        super().__init__()
        self.n, self.d = n, d

    def wrap(self, aw, ah):
        return self.d, self.d

    def draw(self):
        c, r = self.canv, self.d / 2
        c.setFillColor(hx(BLUE))
        c.circle(r, r, r, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT["EP-Black"], 12)
        c.drawCentredString(r, r - 4.2, str(self.n))


def steps(items):
    """Nummerierte Schritte: Liste aus (Titel, Text)."""
    rows = []
    for i, (title, text) in enumerate(items, 1):
        cell = [Paragraph(title, S["step_t"]), Paragraph(text, S["step"])]
        rows.append([NumBadge(i), cell])
    t = Table(rows, colWidths=[12 * mm, CONTENT_W - 12 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (1, 0), (1, -2), 0.6, hx(LINE)),
    ]))
    return t


def box(label, text, tone="tip"):
    """Farbiger Kasten mit Randstreifen links. tone: tip (grau), ok (grün), warn (gelb)."""
    bg, edge = {"tip": (SOFT, BLUE), "ok": (GREEN_SOFT, GREEN), "warn": (AMBER_SOFT, AMBER)}[tone]
    f = FONT
    lab = ParagraphStyle("lab", parent=S["tip"], fontName=f["EP-Black"], textColor=hx(edge), fontSize=8.6,
                         leading=11, spaceAfter=1)
    t = Table([[[Paragraph(label.upper(), lab), Paragraph(text, S["tip"])]]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), hx(bg)),
        ("LINEBEFORE", (0, 0), (0, -1), 3.2, hx(edge)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([Spacer(1, 3), t, Spacer(1, 6)])


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def table(head, rows, widths, key_col=True):
    data = [[Paragraph(h, S["th"]) for h in head]]
    for r in rows:
        data.append([Paragraph(r[0], S["key"] if key_col else S["td"])] + [Paragraph(x, S["td"]) for x in r[1:]])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), hx(HEAD1)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, hx(STRIPE)]),
        ("BOX", (0, 0), (-1, -1), 0.7, hx(BORDER)),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, hx(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return KeepTogether([t, Spacer(1, 6)])


def _tick(c, x, y, size, color):
    """Haken als zwei Linien (die Schrift hat kein ✓)."""
    c.setStrokeColor(color)
    c.setLineWidth(1.6)
    c.setLineCap(1)
    c.setLineJoin(1)
    p = c.beginPath()
    p.moveTo(x + size * 0.2, y + size * 0.52)
    p.lineTo(x + size * 0.42, y + size * 0.28)
    p.lineTo(x + size * 0.8, y + size * 0.74)
    c.drawPath(p, stroke=1, fill=0)


class ListMock(Flowable):
    """Nachgezeichnete Einkaufsliste: angehakt / nicht angehakt / Extras & Notizen."""
    ROW = 7.6 * mm

    def __init__(self, width=CONTENT_W):
        super().__init__()
        self.w = width
        # (Text, Händler, Preis, Zustand)  Zustand: on / off
        self.groups = [
            ("Lidl", [("Hackfleisch gemischt, 500 g", "Lidl", "3,49 €", "on"),
                      ("Spaghetti, 500 g", "Lidl", "0,99 €", "on"),
                      ("Pfeffer", "habe ich schon", "", "off")]),
            ("Extras & Notizen", [("Kaffee, 500 g  (Extra mit Rabatt)", "Kaufland", "4,99 €", "on"),
                                  ("Geburtstagskarte  (Notiz)", "", "", "on")]),
        ]
        n = sum(len(g[1]) + 1 for g in self.groups)
        self.h = n * self.ROW + 10 * mm + 2 * mm

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c, f, R = self.canv, FONT, self.ROW
        w, h = self.w, self.h
        c.setFillColor(hx(STRIPE))
        c.setStrokeColor(hx(BORDER))
        c.setLineWidth(0.8)
        c.roundRect(0, 0, w, h, 2.5 * mm, stroke=1, fill=1)
        # Kopfzeile
        top = h
        c.setFillColor(hx(SOFT))
        c.roundRect(0.6, top - 8 * mm, w - 1.2, 7.4 * mm, 2 * mm, stroke=0, fill=1)
        c.setFillColor(hx(HEAD1))
        c.setFont(f["EP-Bold"], 8.8)
        c.drawString(4 * mm, top - 5.6 * mm, "Einkaufsliste")
        c.setFont(f["EP-Semi"], 8.2)
        c.setFillColor(hx(SUB))
        c.drawRightString(w - 4 * mm, top - 5.6 * mm, "Summe nur für angehakte Zeilen:  9,47 €")
        y = top - 10 * mm
        for gname, rows in self.groups:
            y -= R
            c.setFillColor(hx(BLUE))
            c.setFont(f["EP-Black"], 9.4)
            c.drawString(4 * mm, y + 2.4 * mm, gname)
            for text, shop, price, state in rows:
                y -= R
                on = state == "on"
                bx, by, bs = 4 * mm, y + 1.6 * mm, 4.4 * mm
                if on:
                    c.setFillColor(hx(BLUE))
                    c.setStrokeColor(hx(BLUE))
                else:
                    c.setFillColor(colors.white)
                    c.setStrokeColor(hx("#9ca3af"))
                c.setLineWidth(1)
                c.roundRect(bx, by, bs, bs, 0.9 * mm, stroke=1, fill=1)
                if on:
                    _tick(c, bx, by, bs, colors.white)
                c.setFont(f["EP"], 9.4)
                c.setFillColor(hx(INK if on else "#a3aec2"))
                c.drawString(bx + bs + 3 * mm, y + 2.5 * mm, text)
                if not on:     # durchgestrichen = „nicht auf der Liste“
                    tw = pdfmetrics.stringWidth(text, f["EP"], 9.4)
                    c.setStrokeColor(hx("#a3aec2"))
                    c.setLineWidth(0.6)
                    c.line(bx + bs + 3 * mm, y + 3.6 * mm, bx + bs + 3 * mm + tw, y + 3.6 * mm)
                c.setFillColor(hx(SUB if on else "#a3aec2"))
                c.setFont(f["EP"], 8.6)
                c.drawString(w * 0.62, y + 2.5 * mm, shop)
                c.setFont(f["EP-Bold"], 9.4)
                c.drawRightString(w - 4 * mm, y + 2.5 * mm, price)
        # Beschriftungen mit Pfeil
        c.setFont(f["EP-Semi"], 7.6)


def mock_caption(text):
    return Paragraph(text, S["cap"])


class Dots(Flowable):
    """Kleine Schemazeichnung der Willkommen-Karte (Einstellungen beim ersten Start)."""

    def __init__(self, width=CONTENT_W):
        super().__init__()
        self.w, self.h = width, 58 * mm

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c, f, w, h = self.canv, FONT, self.w, self.h
        c.setFillColor(hx(STRIPE))
        c.setStrokeColor(hx(BORDER))
        c.setLineWidth(0.8)
        c.roundRect(0, 0, w, h, 2.5 * mm, stroke=1, fill=1)
        # Willkommen-Karte
        c.setFillColor(hx(BLUE))
        c.roundRect(4 * mm, h - 15 * mm, w - 8 * mm, 11 * mm, 2 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(f["EP-Black"], 10.5)
        c.drawString(8 * mm, h - 9.2 * mm, "Willkommen bei Essens-Plan!")
        c.setFont(f["EP"], 8)
        c.drawString(8 * mm, h - 12.8 * mm, "Stell kurz ein, wo du einkaufst – dann geht es los.")
        # Felder links
        def field(x, y, wd, label, value):
            c.setFillColor(hx(SUB))
            c.setFont(f["EP-Semi"], 7.6)
            c.drawString(x, y + 7.6 * mm, label)
            c.setFillColor(colors.white)
            c.setStrokeColor(hx(BORDER))
            c.roundRect(x, y, wd, 6.2 * mm, 1 * mm, stroke=1, fill=1)
            c.setFillColor(hx(INK))
            c.setFont(f["EP"], 8.8)
            c.drawString(x + 2 * mm, y + 1.9 * mm, value)
        fx = 4 * mm
        field(fx, h - 29 * mm, 30 * mm, "Postleitzahl (Pflicht)", "10115")
        field(fx + 34 * mm, h - 29 * mm, 18 * mm, "Personen", "2")
        field(fx + 56 * mm, h - 29 * mm, 18 * mm, "Läden", "2")
        # Händler-Checkboxen rechts
        hxx = w * 0.60
        c.setFillColor(hx(SUB))
        c.setFont(f["EP-Semi"], 7.6)
        c.drawString(hxx, h - 21.5 * mm, "Händler  (nichts angehakt = alle)")
        for i, (name, on) in enumerate([("Lidl · 239 Angebote", True), ("Rewe · 301 Angebote", True),
                                        ("Aldi · 188 Angebote", False)]):
            yy = h - 27.5 * mm - i * 6 * mm
            if on:
                c.setFillColor(hx(BLUE))
                c.setStrokeColor(hx(BLUE))
            else:
                c.setFillColor(colors.white)
                c.setStrokeColor(hx("#9ca3af"))
            c.setLineWidth(1)
            c.roundRect(hxx, yy, 3.8 * mm, 3.8 * mm, 0.8 * mm, stroke=1, fill=1)
            if on:
                _tick(c, hxx, yy, 3.8 * mm, colors.white)
            c.setFillColor(hx(INK))
            c.setFont(f["EP"], 8.6)
            c.drawString(hxx + 6 * mm, yy + 0.9 * mm, name)
        # Rabatt-Filter
        c.setFillColor(hx(SUB))
        c.setFont(f["EP-Semi"], 7.6)
        c.drawString(fx, h - 40 * mm, "Rabatt-Filter (optional)")
        c.setFillColor(hx(INK))
        c.setFont(f["EP"], 8.6)
        c.drawString(fx, h - 44.6 * mm, "Nur Angebote ab 20 % Rabatt anzeigen")
        # Knopf
        bw = 58 * mm
        c.setFillColor(hx(HEAD1))
        c.rect(w - bw - 4 * mm, 4 * mm, bw, 8 * mm, stroke=0, fill=1)    # eckig wie im Programm
        c.setFillColor(colors.white)
        c.setFont(f["EP-Bold"], 9.2)
        c.drawCentredString(w - bw / 2 - 4 * mm, 6.5 * mm, "Speichern & Angebote laden")


# ─── Kopf- und Fußzeilen ──────────────────────────────────────────────────────
def _footer(c, page):
    f = FONT
    c.setStrokeColor(hx(LINE))
    c.setLineWidth(0.8)
    c.line(M, 14 * mm, W - M, 14 * mm)
    c.setFillColor(hx(SUB))
    c.setFont(f["EP"], 8.4)
    c.drawString(M, 9 * mm, f"{TITEL} {VERSION}  ·  Anleitung")
    c.setFont(f["EP-Semi"], 8.4)
    c.drawRightString(W - M, 9 * mm, f"Seite {page}")


def first_page(c, doc):
    f = FONT
    c.saveState()
    c.setFillColor(hx(BANNER_BG))
    c.rect(0, H - BANNER, W, BANNER, stroke=0, fill=1)
    c.setFillColor(hx(HEAD1))
    c.rect(0, H - BANNER, W, 2.2 * mm, stroke=0, fill=1)
    # dezente Kreise
    c.setFillColor(colors.Color(1, 1, 1, alpha=0.08))
    c.circle(W - 22 * mm, H - 14 * mm, 30 * mm, stroke=0, fill=1)
    c.circle(W - 62 * mm, H - 46 * mm, 16 * mm, stroke=0, fill=1)
    # Teller-Symbol: Kreis mit Gabel-Strichen
    cx, cy = M + 9 * mm, H - 25 * mm
    c.setFillColor(colors.white)
    c.circle(cx, cy, 9 * mm, stroke=0, fill=1)
    c.setFillColor(hx(BANNER_BG))
    c.circle(cx, cy, 6.4 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.circle(cx, cy, 5.2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(f["EP-Black"], 31)
    c.drawString(M + 24 * mm, H - 24 * mm, TITEL)
    c.setFont(f["EP"], 12.5)
    c.drawString(M + 24 * mm, H - 33 * mm, UNTERTITEL)
    # Versionsmarke
    c.setFillColor(colors.white)
    c.roundRect(M + 24 * mm, H - 44.5 * mm, 54 * mm, 6.4 * mm, 3.2 * mm, stroke=0, fill=1)
    c.setFillColor(hx(BANNER_BG))
    c.setFont(f["EP-Bold"], 9)
    c.drawCentredString(M + 51 * mm, H - 42.6 * mm, f"Anleitung  ·  Version {VERSION}")
    _footer(c, doc.page)
    c.restoreState()


def later_page(c, doc):
    f = FONT
    c.saveState()
    c.setFillColor(hx(BANNER_BG))
    c.rect(0, H - 9 * mm, W, 9 * mm, stroke=0, fill=1)
    c.setFillColor(hx(HEAD2))
    c.rect(0, H - 9 * mm, W, 1.2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(f["EP-Bold"], 9)
    c.drawString(M, H - 6.2 * mm, TITEL)
    c.setFont(f["EP"], 9)
    c.drawRightString(W - M, H - 6.2 * mm, UNTERTITEL)
    _footer(c, doc.page)
    c.restoreState()


# ─── Inhalt ───────────────────────────────────────────────────────────────────
def story():
    P = lambda t, s="body": Paragraph(t, S[s])
    out = []
    def A(x):
        out.extend(x) if isinstance(x, list) else out.append(x)

    # Seite 1: Überblick und Schnellstart
    A(P("Essens-Plan lädt die Prospekt-Angebote der Supermärkte in deiner Umgebung und baut daraus einen "
        "Wochenplan: Möglichst viele Zutaten sind gerade im Angebot, und der Einkauf verteilt sich auf "
        "möglichst wenige Läden. Am Ende hast du eine fertige Einkaufsliste mit Preisen – zum Kopieren "
        "aufs Handy oder als PDF zum Ausdrucken.", "lead"))
    A(P("<b>Start:</b> Doppelklick auf <b>Essens-Plan.exe</b>. Eine Installation ist nicht nötig, das "
        "Programm läuft auch von einem USB-Stick."))
    A(box("Windows meldet sich?",
          "Beim ersten Start zeigt Windows eventuell „Der Computer wurde durch Windows geschützt“. Das "
          "passiert bei jedem Programm ohne gekaufte Signatur. Klicke auf <b>Weitere Informationen</b> und "
          "dann auf <b>Trotzdem ausführen</b>.", "warn"))

    A(Heading("In 5 Schritten zum Plan"))
    A(steps([
        ("Programm starten",
         "Beim allerersten Start öffnen sich zuerst die <b>Einstellungen</b> mit einer Willkommen-Karte. "
         "Es wird noch nichts geladen, bevor du etwas eingestellt hast."),
        ("Postleitzahl, Personen und Läden",
         "Trage deine <b>Postleitzahl</b> ein (die ist Pflicht), dazu für wie viele <b>Personen</b> du kochst "
         "und in wie vielen <b>Läden</b> du höchstens einkaufen willst."),
        ("Händler und Treue-Programme auswählen",
         "Hake die <b>Händler</b> an, bei denen du einkaufst – zum Beispiel „Lidl · 239 Angebote“. Nutzt du "
         "Apps wie <b>Lidl Plus</b> oder <b>Payback</b>, hake auch die passenden Treue-Programme an, dann "
         "werden die App-Preise gerechnet."),
        ("Speichern & Angebote laden",
         "Ein Klick auf <b>Speichern & Angebote laden</b>: Das Programm holt jetzt die aktuellen Angebote. "
         "Das dauert je nach Region etwa eine halbe bis eine Minute."),
        ("Plan generieren",
         "Danach auf <b>Plan generieren</b> (Taste <b>F6</b>) – schon steht dein Wochenplan. Im Tab "
         "<b>Einkaufsliste</b> findest du alles zum Einkaufen."),
    ]))
    A(box("Tipp",
          "Du musst keinen Händler anhaken: <b>Nichts angehakt heißt: alle Händler</b> in deiner Nähe werden "
          "berücksichtigt. Alles lässt sich später im Tab <b>Einstellungen</b> ändern.", "tip"))

    A(Spacer(1, 4))
    A(KeepTogether([Dots(), mock_caption("So sieht die Willkommen-Karte beim ersten Start aus (vereinfacht dargestellt)."),
                    Spacer(1, 4)]))

    # Einstellungen im Detail
    A(Heading("Die Einstellungen im Detail"))
    A(table(["Einstellung", "Was sie bewirkt"], [
        ("Postleitzahl", "Bestimmt, welche Prospekte und Märkte in deiner Nähe gesucht werden. Pflichtfeld."),
        ("Personen", "Alle Mengen werden auf diese Personenzahl umgerechnet."),
        ("Anzahl Läden", "So viele Läden dürfen im Wochenplan höchstens vorkommen. Weniger Läden heißt "
                         "kürzere Einkaufstour."),
        ("Händler", "Kästchen zum Anhaken, mit der Zahl der Angebote je Händler. Nichts angehakt = alle. "
                    "Hat ein Händler diese Woche nichts, steht dahinter, warum: „kein Prospekt“, „Prospekt "
                    "ohne Angebote“ oder „Prospekt kommt noch“. Darunter erscheint dann die Karte „Kein "
                    "aktueller Prospekt“ mit dem Knopf „Letzten Prospekt ansehen“."),
        ("Treue-Programme", "Lidl Plus, Payback und weitere: Dann werden die günstigeren App-Preise gerechnet."),
        ("Rabatt-Filter", "Optional: „Nur Angebote ab … % Rabatt anzeigen“ (5 bis 90 %). Gilt für die "
                          "Angebotsliste, den Plan und die Einkaufsliste."),
        ("Ohne Angebot nachfragen", "Findet „Artikel hinzufügen“ kein Angebot, wird erst gefragt, ob der "
                                    "Artikel ohne Preis auf die Liste soll. Aus = sofort aufschreiben."),
        ("Größe der Oberfläche", "Automatisch oder fest von 100 bis 300 % (siehe „Ansicht & Größe“)."),
    ], [38 * mm, CONTENT_W - 38 * mm]))

    # Essensplan
    A(Heading("Der Essensplan"))
    A(P("Jeder Tag zeigt ein Gericht mit Zutaten, Zubereitungszeit und Kochanleitung. Was gerade im Angebot "
        "ist, steht direkt dabei – und was es kostet."))
    A(P("Gericht ändern", "h2"))
    A(P("Über die <b>Auswahlliste</b> an der Tageskarte tauschst du das Gericht selbst aus, mit "
        "<b>Neu</b> würfelt das Programm für diesen Tag ein anderes. Die anderen Tage bleiben unverändert."))
    A(P("Tage hinzufügen und entfernen", "h2"))
    A(bullets([
        "<b>Tag hinzufügen:</b> Klicke auf „Tag hinzufügen“ und wähle den Wochentag.",
        "<b>Tag entfernen:</b> Klicke auf das <b>x</b> oben rechts an der Tageskarte. Mindestens ein Tag "
        "bleibt immer stehen.",
        "Was du hier änderst, gilt automatisch auch für die Einkaufsliste und das PDF.",
    ]))
    A(P("Auf Abwechslung ist Verlass", "h2"))
    A(P("Dieselbe Hauptzutat kommt nicht zweimal in einer Woche vor, zwei Tage hintereinander gibt es nicht "
        "dieselbe Beilage, und Gerichte der letzten beiden Wochen werden seltener gezogen. Favoriten dafür "
        "häufiger."))

    # Einkaufsliste
    A(CondPageBreak(100 * mm))
    A(Heading("Die Einkaufsliste"))
    A(P("Jede Zeile hat einen <b>Haken</b>. Das ist dein Schalter für „muss ich kaufen“:"))
    A(bullets([
        "<b>Angehakt:</b> kommt auf die Einkaufsliste.",
        "<b>Nicht angehakt:</b> habe ich schon da, zum Beispiel Pfeffer. Die Zeile wird grau und zählt nicht "
        "zur Summe, zum Kopieren und zum PDF.",
        "Zutaten, die als <b>Vorrat</b> gelten, sind anfangs nicht angehakt.",
        "Umschalten geht mit <b>Klick</b>, <b>Doppelklick</b> oder der <b>Leertaste</b>.",
    ]))
    A(Spacer(1, 4))
    A(ListMock())
    A(mock_caption("Angehakt = kaufen. Grau und ohne Haken = habe ich schon, zählt nicht zur Summe."))
    A(Spacer(1, 8))
    A(P("Artikel hinzufügen – erst Angebote, dann aufschreiben", "h2"))
    A(P("Über der Liste steht ein Eingabefeld. Tippe ein, was du brauchst – eine Sorte wie „Duschgel“, "
        "„Shampoo“ oder „Zahnpasta“ oder gleich eine Marke wie „Axe“ – und drücke <b>Enter</b> oder "
        "<b>Artikel hinzufügen</b>. Essens-Plan sucht dann zuerst bei deinen Händlern nach passenden "
        "Angeboten:"))
    A(bullets([
        "<b>Es gibt Angebote:</b> Das Fenster <b>Artikel hinzufügen</b> zeigt alle passenden Sorten und "
        "Marken, die besten Rabatte zuerst. Angebot anklicken und <b>Angebot übernehmen</b> – es landet mit "
        "Preis auf der Liste. Passt nichts, setzt <b>Ohne Angebot aufschreiben</b> nur den Namen ohne Preis "
        "auf die Liste.",
        "<b>Kein Angebot:</b> Essens-Plan sagt dir das und fragt, ob der Artikel ohne Preis auf die "
        "Einkaufsliste soll. Mit dem Kästchen <b>Nicht mehr fragen</b> wird er künftig sofort aufgeschrieben.",
        "<b>Schreibweise egal:</b> Groß/klein, Umlaute und kleine Tippfehler stören nicht. „Deo“ findet auch "
        "Axe, Rexona oder Nivea, „Axe“ findet Deo und Duschgel. Bei einem Tippfehler schlägt die Suche das "
        "gemeinte Wort vor.",
        "Ein Klick auf <b>Artikel hinzufügen</b> bei leerem Feld zeigt die besten Rabatte deiner Händler.",
    ]))
    A(box("Tipp", "Die Rückfrage lässt sich jederzeit wieder einschalten: Tab <b>Einstellungen</b>, Kästchen "
          "<b>Ohne Angebot nachfragen</b>. Mehr Platz und Auswahl bietet der Reiter "
          "<b>Angebot raussuchen</b> (nächster Abschnitt).", "tip"))
    A(P("Notiz hinzufügen", "h2"))
    A(P("Mit <b>Notiz hinzufügen</b> schreibst du freien Text auf die Liste, etwa „Geburtstagskarte“. "
        "Extras und Notizen stehen gesammelt in der letzten Gruppe <b>Extras & Notizen</b>. Entfernen geht mit "
        "<b>Entf</b> oder per Rechtsklick auf <b>Entfernen</b>."))
    A(P("Mitnehmen", "h2"))
    A(P("<b>Kopieren</b> legt die Liste in die Zwischenablage (praktisch zum Verschicken aufs Handy), "
        "<b>PDF drucken</b> (<b>Strg+P</b>) erzeugt den Ausdruck: Seite 1 der Wochenplan, danach die "
        "Einkaufsliste."))

    # Angebot raussuchen
    A(CondPageBreak(90 * mm))
    A(Heading("Angebot raussuchen"))
    A(P("Du brauchst etwas Bestimmtes und willst wissen, wo es gerade günstig ist? Dafür gibt es den Reiter "
        "<b>Angebot raussuchen</b> (<b>Strg+2</b>). Die drei Schritte stehen auch oben im Reiter:"))
    A(steps([
        ("Eintippen",
         "Was brauchst du? Eine Sorte wie „Duschgel“, eine Marke wie „Axe“ oder einen Oberbegriff wie "
         "„Obst“, „Fleisch“ oder „Alkohol“. Groß/klein und kleine Tippfehler sind egal – „Deo“ und "
         "„Axe“ finden beide die Deo-Angebote. Die Knöpfe unter dem Feld (Brot, Obst, Klopapier, "
         "Katzenstreu …) suchen mit einem Klick."),
        ("Angebot anklicken",
         "Oben stehen die passenden Angebote deiner Händler, die besten zuerst. Darunter stehen "
         "<b>ähnliche Produkte, die gerade stark reduziert sind</b> (ab 25 % billiger als sonst) – zum "
         "Beispiel dieselbe Sorte von einer anderen Marke."),
        ("Auf die Einkaufsliste",
         "Unten rechts auf <b>Auf die Einkaufsliste</b> drücken oder doppelt klicken. Ein Haken vor dem "
         "Produkt zeigt: steht schon auf deiner Liste."),
    ]))
    A(bullets([
        "<b>Kein Angebot?</b> Essens-Plan sagt es dir und fragt, ob der Artikel ohne Preis auf die "
        "Einkaufsliste soll – mit <b>Nicht mehr fragen</b>, genau wie bei „Artikel hinzufügen“.",
        "<b>Feld leer:</b> Dann zeigt der Reiter die stärksten Rabatte der Woche bei deinen Händlern.",
        "Der Knopf <b>So geht's</b> erklärt alles noch einmal.",
    ]))
    A(P("<b>Schneller durch die Angebote:</b>"))
    A(bullets([
        "<b>Kategorien:</b> Die runde Knopfleiste unter dem Feld zeigt eine ganze Abteilung – Getränke, "
        "Kaffee &amp; Tee, Süßes, Fleisch, Fisch, Obst &amp; Gemüse, Kräuter &amp; Gewürze, Milch &amp; Käse, "
        "Brot, Tiefkühl, Drogerie, Haushalt, Tier. Was du eintippst, sucht dann nur noch darin.",
        "<b>Getränke:</b> mit oder ohne Alkohol, nach Sorte (Bier, Wasser, Energy …) und mit Marken-Knöpfen.",
        "<b>⭐ Top-Deals</b> (Schnäppchen-Radar): Kisten, Träger, Großpackungen, deine Marken und starke "
        "Rabatte – jeweils mit Grund und Preis je Liter oder Kilo. Unter <b>Meine Marken</b> legst du fest, "
        "welche Marken zählen.",
        "<b>Händler, Mindest-Rabatt und Sortierung</b> (Rabatt, Preis, Händler) stellst du direkt im Reiter "
        "ein; sie bleiben gespeichert.",
        "<b>Nur neue</b> zeigt, was seit deinem letzten Besuch dazugekommen ist (in der Liste mit „NEU“).",
        "<b>Mehrere auf einmal:</b> mit Strg oder Umschalt anklicken, dann <b>Auf die Einkaufsliste</b>.",
    ]))

    # Angebote
    A(Heading("Angebote ansehen"))
    A(P("Im Tab <b>Alle Angebote</b> siehst du alles, was geladen wurde, mit Filtern für Händler, Kategorie und "
        "Suche. Neue Prospekte erscheinen meist ab Sonntag für die kommende Woche – darum zeigt Essens-Plan "
        "<b>sonntags schon die neue Woche</b>. Zur laufenden Woche geht es mit dem linken Pfeil neben der "
        "Wochenanzeige. Mit <b>F5</b> lädst du die "
        "Angebote jederzeit neu. Ist der Rabatt-Filter aktiv, siehst du nur Angebote ab dem eingestellten "
        "Prozentwert."))
    A(P("Die <b>Suche</b> kennt Sorten, Marken und viele Schreibweisen: „Deo“ und „Axe“ finden beide die "
        "Deo-Angebote, „Duschgel“ auch Cremeduschen und Duschbäder. Oberbegriffe wie „Alkohol“, „Obst“, "
        "„Gemüse“, „Brot“, „Fleisch“, „Süßigkeiten“ oder „Tierfutter“ finden alles aus den passenden "
        "Prospekt-Kategorien, auch wenn das Wort nicht im Produktnamen steht. Mit Suchbegriff wird in allen Branchen "
        "gesucht, also auch bei Drogerien – die besten Treffer stehen oben. Bei einem Tippfehler erscheint "
        "„Meintest du …?“ mit einem Knopf für die richtige Suche."))

    # Eigene Gerichte
    A(Heading("Eigene Gerichte"))
    A(P("Mitgeliefert sind rund 130 alltagstaugliche Gerichte, von Spaghetti Bolognese über Rindergulasch "
        "und Ofenlachs bis Kaiserschmarrn. Im Tab <b>Gerichte</b> steckt die komplette Rezeptdatenbank:"))
    A(bullets([
        "Suche und Filter: Favoriten, Kategorien, eigene Gerichte.",
        "<b>Neues Gericht</b> für eigene Rezepte; Bearbeiten, Duplizieren und Löschen (mit Papierkorb).",
        "<b>Favoriten</b> werden beim Planen bevorzugt, <b>pausierte</b> Gerichte nie eingeplant.",
        "<b>Einplanen</b> legt ein Gericht direkt auf einen Wochentag.",
    ]))
    A(box("Gut zu wissen",
          "Mengen trägst du immer <b>für 2 Personen</b> ein, das Programm rechnet sie auf deine Personenzahl "
          "hoch. Die <b>Suchbegriffe</b> einer Zutat bestimmen, wonach in den Angeboten gesucht wird (mehrere "
          "mit | trennen, z. B. hackfleisch|rinderhack). Ein Haken bei <b>Vorrat</b> heißt: habe ich zu "
          "Hause, nicht suchen.", "tip"))
    A(P("Die mitgelieferte Grunddatenbank wird nie überschrieben. Deine Änderungen liegen getrennt davon und "
        "lassen sich jederzeit über <b>Original</b> zurücksetzen."))

    # Tastenkürzel
    A(Heading("Tastenkürzel"))
    A(table(["Taste", "Wirkung"], [
        ("F5", "Angebote neu laden (scannen)"),
        ("F6", "Wochenplan generieren"),
        ("Strg + P", "PDF exportieren (drucken)"),
        ("Strg + Pfeil links", "eine Woche zurück"),
        ("Strg + Pfeil rechts", "eine Woche vor"),
        ("Strg + 1 bis 6", "zwischen den Tabs wechseln (Strg + 2 = Angebot raussuchen)"),
        ("Leertaste", "Haken in der Einkaufsliste umschalten"),
        ("Entf", "Extra oder Notiz aus der Einkaufsliste entfernen"),
    ], [48 * mm, CONTENT_W - 48 * mm]))

    # Daten
    A(Heading("Wo liegen meine Daten?"))
    A(P("Ist der Ordner der EXE beschreibbar (zum Beispiel USB-Stick oder eigener Ordner), liegt alles "
        "daneben im Ordner <b>res</b>:"))
    A(table(["Datei", "Inhalt"], [
        ("res\\config.json", "deine Einstellungen"),
        ("res\\meine_rezepte.json", "deine Gerichte und Favoriten"),
        ("res\\wochen\\*.json", "Angebote und Pläne je Kalenderwoche"),
    ], [58 * mm, CONTENT_W - 58 * mm]))
    A(P("Liegt das Programm unter „Programme“, wo Windows nichts hineinschreiben lässt, wandern die Daten "
        "automatisch nach <b>%APPDATA%\\Essens-Plan</b>. Den richtigen Ordner öffnet immer das Menü "
        "<b>Datei &gt; Datenordner öffnen</b>."))
    A(box("Sichern und umziehen",
          "<b>Datei &gt; Rezepte sichern …</b> schreibt alle deine Gerichte in eine JSON-Datei, "
          "<b>Rezepte importieren …</b> liest sie wieder ein. So nimmst du deine Rezepte auf einen anderen PC "
          "mit.", "ok"))

    # Ansicht
    A(Heading("Ansicht & Größe"))
    A(bullets([
        "Das Fenster öffnet immer <b>maximiert</b> und startet im <b>dunklen Design</b>.",
        "Zu fast jedem Knopf gibt es einen <b>Hinweis</b>: Maus kurz darüber halten, dann erscheint eine kurze Erklärung. "
        "Leere Listen sagen dir außerdem, was als Nächstes zu tun ist.",
        "Das Menü <b>Ansicht</b> schaltet zwischen dem hellen Design (helles Grau) und dem dunklen Design um (das Fenster startet "
        "danach neu).",
        "Alles zu klein oder zu groß, zum Beispiel auf einem 4K-Bildschirm? Tab <b>Einstellungen</b>, Karte "
        "<b>Größe</b>: Bei „Größe der Oberfläche“ <b>Automatisch</b> lassen oder einen festen Wert von 100 bis "
        "300 % wählen (wird automatisch gespeichert). Die neue Größe gilt nach einem <b>Neustart</b> des Programms.",
        "<b>Kleiner Bildschirm</b> (zum Beispiel Laptop mit 1366 × 768): Das Band ganz oben fällt weg und "
        "alles rückt enger zusammen. Den Knopf für Hell/Dunkel findest du dann in der Leiste oben rechts – "
        "ist auch dafür kein Platz, im Menü <b>Ansicht</b>.",
    ]))

    # Updates
    A(Heading("Updates"))
    A(P("Die neueste Version gibt es immer unter "
        "<b>https://github.com/98koellnertd-code/Essens-Plan/releases/latest</b>. Dieses Projekt ist im Tab "
        "<b>Einstellungen</b> in der Karte <b>Update</b> schon eingetragen; der Knopf <b>Download-Seite</b> "
        "öffnet die Seite. Das Programm sieht beim Start still nach (abschaltbar), und "
        "<b>Nach Updates suchen</b> (auch im Menü <b>Hilfe</b>) findet die neueste Version, lädt sie nach "
        "Rückfrage und tauscht die EXE aus. Klappt der Tausch nicht, bleibt die bisherige EXE erhalten. Deine "
        "Daten bleiben in jedem Fall unberührt."))

    # Probleme
    A(Heading("Probleme?"))
    A(table(["Wenn …", "dann …"], [
        ("„Keine Angebote gefunden“", "Prospekte erscheinen meist ab Sonntag für die kommende Woche. "
                                      "Postleitzahl prüfen und erneut laden (F5). Prüfe auch, ob der "
                                      "Rabatt-Filter zu hoch eingestellt ist."),
        ("Bei einem Händler wird nichts gefunden (z. B. Kaufland)",
         "marktguru.de, woher Essens-Plan die Angebote bekommt, hat für diesen Händler gerade keinen "
         "aktuellen Prospekt. Das kann an marktguru liegen (dort fehlen manchmal Prospekte) oder der Händler "
         "hat keinen veröffentlicht. In den Einstellungen steht dann „kein Prospekt“ dabei, und in der Karte "
         "„Kein aktueller Prospekt“ öffnet „Letzten Prospekt ansehen“ den letzten Prospekt im Browser – seine "
         "Preise gelten aber meist nicht mehr. Für die Suche solange weitere Händler anhaken oder alle Haken "
         "entfernen (= alle Händler)."),
        ("Ein Händler hat „Prospekt ohne Angebote“ (z. B. ALDI)",
         "Der Prospekt ist da, aber marktguru hat die Angebote daraus nicht einzeln erfasst. Essens-Plan kann "
         "ihn darum nicht nutzen. Mit „Prospekt ansehen“ kannst du selbst hineinschauen."),
        ("„PDF ist noch geöffnet“", "Das PDF im Reader schließen und erneut exportieren."),
        ("Ein Gericht taucht nie auf", "Im Tab Gerichte prüfen, ob es pausiert ist oder ob der Filter "
                                       "„Nur vegetarisch“ es ausschließt."),
        ("„Unerwarteter Fehler“", "Sollte nicht vorkommen. Die Einzelheiten stehen in der Datei fehler.log "
                                  "im Datenordner (Datei &gt; Datenordner öffnen), die hilft bei der "
                                  "Fehlersuche."),
    ], [52 * mm, CONTENT_W - 52 * mm], key_col=True))
    A(P("Hinweise", "h2"))
    A(bullets([
        "Angebotsdaten kommen von marktguru.de. Preise und Verfügbarkeit ohne Gewähr – im Zweifel gilt der "
        "Aushang im Laden.",
        "Mit <b>~</b> markierte Preise sind geschätzt (aus dem Durchschnitts-Grundpreis der Kategorie), weil "
        "der Prospekt keine Menge nennt.",
        "Für das Laden der Angebote wird eine Internetverbindung gebraucht, sonst nicht.",
        "Das Programm sendet keine persönlichen Daten; die Postleitzahl wird nur für die regionale "
        "Angebotssuche verwendet.",
    ]))
    A(Spacer(1, 8))
    A(KeepTogether([Paragraph("<b>Viel Spaß beim Sparen!</b>",
                              ParagraphStyle("end", parent=S["lead"], fontSize=13, textColor=hx(HEAD1),
                                             alignment=1))]))
    return out


def build(path):
    global S
    register_fonts()
    S = make_styles()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    doc = BaseDocTemplate(tmp, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=14 * mm, bottomMargin=20 * mm,
                          title=f"{TITEL} {VERSION} – Anleitung", author=TITEL,
                          subject=UNTERTITEL)
    f_first = Frame(M, 20 * mm, CONTENT_W, H - BANNER - 20 * mm - 8 * mm, id="first",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_later = Frame(M, 20 * mm, CONTENT_W, H - 20 * mm - 18 * mm, id="later",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate("first", [f_first], onPage=first_page),
                          PageTemplate("later", [f_later], onPage=later_page)])
    items = [NextPageTemplate("later")] + story()
    doc.build(items)
    os.replace(tmp, path)
    return doc.page


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    out = argv[1] if len(argv) > 1 else os.path.join(here, "dist", "Anleitung.pdf")
    try:
        pages = build(out)
        if not os.path.isfile(out) or os.path.getsize(out) < 2000:
            raise RuntimeError("Die PDF-Datei ist leer oder fehlt.")
    except Exception as e:
        print(f"Anleitung konnte nicht erstellt werden: {e}", file=sys.stderr)
        try:
            if os.path.exists(out + ".tmp"):
                os.remove(out + ".tmp")
        except OSError:
            pass
        return 1
    print(f"Anleitung geschrieben: {out}  ({pages} Seiten)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
