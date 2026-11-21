"""Reiter „Angebot raussuchen“: gezielt nach einem Artikel suchen – Sorte oder Marke, Schreibweise egal.

Oben stehen die passenden Angebote der angehakten Händler, darunter ähnliche Produkte, die gerade stark
reduziert sind (gleiche Sorte einer anderen Marke, verwandte Sorte, gleiche Abteilung). Gibt es nichts,
kommt der Artikel auf Wunsch ohne Preis auf die Einkaufsliste – mit Rückfrage, solange „Nicht mehr
fragen“ nicht angehakt ist (dieselbe Einstellung wie im Fenster „Artikel hinzufügen“).

Geschrieben für Menschen, die sich mit Computern nicht auskennen: große Schrift, drei nummerierte
Schritte, Alltagssprache und nach jedem Klick eine klare Rückmeldung unten im Reiter."""
import collections
import datetime as dt
import tkinter as tk
from tkinter import font as tkfont, ttk, messagebox

import extras as ext
import offers as off
import planner as pl
import suchbegriffe as sb
import ui
from ui import Btn
from utils import C, F, S, ToolTip

MAX_TREFFER = 300               # mehr liest niemand; ein genauerer Suchbegriff grenzt ein
ALT_RABATT = 25                 # „stark reduziert“ ab so viel Prozent Rabatt …
ALT_RABATT_GESCHAETZT = 35      # … bzw. ab so viel, wenn der Vorher-Preis nur geschätzt ist (~)
ALT_JE_GRUND = 12               # höchstens so viele Vorschläge je Grund („Gleiche Sorte: Deo“)
ALT_MAX = 40
FREMD = ("Möbelhaus", "Baumarkt", "KFZ", "Zoo")     # nur vorschlagen, wenn die Treffer selbst dorther sind
BEISPIELE = ("Brot", "Fleisch", "Obst", "Gemüse", "Kaffee", "Süßigkeiten", "Alkohol", "Duschgel", "Deo",
             "Zahnpasta", "Shampoo", "Tampons", "Taschentücher", "Klopapier", "Küchenrolle", "Waschmittel",
             "Katzenstreu")
SUCH_DELAY = 250                # ms Entprellung der Live-Suche
TIP = 600
WOCHENTAG = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
SCHRITTE = (
    ("⌨️", "1. Eintippen",
     "Was brauchst du? Eine Sorte wie „Duschgel“ oder eine Marke wie „Axe“. "
     "Groß- und Kleinschreibung und kleine Tippfehler sind egal."),
    ("👆", "2. Angebot anklicken",
     "Oben erscheinen die Angebote deiner Händler. Darunter stehen ähnliche Produkte, "
     "die gerade viel billiger sind als sonst."),
    ("➕", "3. Auf die Liste",
     "Unten rechts auf „Auf die Einkaufsliste“ drücken (oder doppelt klicken). Nichts dabei? "
     "Dann „Ohne Angebot aufschreiben“."))
LEGENDE = ("„Preis“ zahlst du.  „Vorher“ ist der normale Preis.  „~“ heißt geschätzt – der Prospekt "
           "nennt keinen normalen Preis.  „✔“ steht schon auf deiner Einkaufsliste.")


# ─── Vorschläge berechnen (ohne Oberfläche, testbar) ─────────────────────────
def stark(d):
    """Gerade stark reduziert? Geschätzte Rabatte (~) müssen höher sein – sie sind unsicherer.
    d ist ein Eintrag aus extras.angebote(): (rabatt|None, angebot, name, preis, vorher, geschätzt)."""
    rab, est = d[0], d[5]
    return rab is not None and rab >= (ALT_RABATT_GESCHAETZT if est else ALT_RABATT)


def _gewicht(d):
    return d[0] * (0.7 if d[5] else 1)


def _branchen(o):
    return [b.strip() for b in (o.get("branche") or "").split(",") if b.strip()]


def _fremd(o, erlaubt=()):
    return any(b.startswith(f) and b not in erlaubt for b in _branchen(o) for f in FREMD)


_SUCHEN = {}


def _suche(name):
    """sb.Suche je Sorte nur einmal bauen."""
    s = _SUCHEN.get(name)
    if s is None:
        s = _SUCHEN[name] = sb.Suche(name)
    return s


def _sorten_der_treffer(hits):
    """Zu welchen Sorten gehören die besten Treffer? Für Suchen, die selbst keine Sorte sind."""
    zaehler = collections.Counter()
    for d in hits[:10]:
        for name, ty in sb.TYPEN.items():
            if not ty["ober"] and _suche(name).passt(d[1]) >= 2:
                zaehler[name] += 1
    return [n for n, _ in zaehler.most_common(3)]


def alternativen(daten, such, hits):
    """Stark reduzierte Produkte, die statt der Treffer in Frage kommen – jeweils mit Grund.
    Genaues vor Allgemeinem: gleiche Sorte (andere Marke), verwandte Sorte, gleiche Abteilung.
    Rückgabe: [(grund, d)] mit d wie in extras.angebote()."""
    schon = {id(d[1]) for d in hits}
    hit_branchen = {b for d in hits for b in _branchen(d[1])}
    kandidaten = [d for d in daten
                  if stark(d) and id(d[1]) not in schon and not _fremd(d[1], hit_branchen)]
    if not kandidaten:
        return []
    sorten = list(dict.fromkeys(such.sorten + such.marken_sorten)) if such else []
    if not sorten:
        sorten = _sorten_der_treffer(hits)
    stufen = [(f"Gleiche Sorte: {sb.anzeige(s)}", lambda o, q=_suche(s): q.passt(o) >= 2) for s in sorten]
    nachbarn = dict.fromkeys(n for s in sorten for n in sb.nachbarn(s) if n not in sorten)
    stufen += [(f"Ähnlich: {sb.anzeige(n)}", lambda o, q=_suche(n): q.passt(o) >= 2) for n in nachbarn]
    kats = collections.Counter(d[1].get("kategorie") for d in hits if (d[1].get("kategorie") or "").strip())
    if kats:
        meist = max(kats.values())
        grenze = max(min(2, meist), meist / 4)      # Ausreißer-Kategorien („Lachs“ im Schinken) weglassen
        stufen += [(f"Gleiche Abteilung: {k.strip()}", lambda o, k=k: o.get("kategorie") == k)
                   for k, n in kats.most_common() if n >= grenze]
    out, vergeben = [], set()
    for grund, passt in stufen:
        gruppe = [d for d in kandidaten if id(d[1]) not in vergeben and passt(d[1])]
        gruppe.sort(key=lambda d: (-_gewicht(d), d[3]))
        for d in gruppe[:ALT_JE_GRUND]:
            vergeben.add(id(d[1]))
            out.append((grund, d))
        if len(out) >= ALT_MAX:
            break
    return out[:ALT_MAX]


def top(daten):
    """Ohne Suchbegriff: die stärksten Rabatte bei Lebensmitteln und Drogerie-Artikeln."""
    liste = [d for d in daten if stark(d) and (off.is_food(d[1]) or
                                              any(b.startswith("Drogerie") for b in _branchen(d[1])))]
    liste.sort(key=lambda d: (-_gewicht(d), d[3]))
    out = []
    for d in liste[:ALT_MAX]:
        kat = (d[1].get("kategorie") or "").strip()
        out.append((f"Top-Rabatt: {kat}" if kat else "Top-Rabatt", d))
    return out


_ZEITRAUM = {}


def gueltig(o, heute=None):
    """„bis Sa. 18.10.“ – oder „ab Mo. 20.10.“, wenn das Angebot noch nicht gilt."""
    heute = heute or dt.date.today()
    key = (o.get("von"), o.get("bis"), heute)
    t = _ZEITRAUM.get(key)
    if t is None:
        try:
            von, bis = dt.date.fromisoformat(key[0]), dt.date.fromisoformat(key[1])
            tag = von if von > heute else bis
            t = f"{'ab' if von > heute else 'bis'} {WOCHENTAG[tag.weekday()]} {tag:%d.%m.}"
        except (TypeError, ValueError):
            t = ""
        _ZEITRAUM[key] = t
    return t


# ─── Oberfläche ──────────────────────────────────────────────────────────────
class _LeerZeile:
    """Schlichter Hinweis über der leeren Vorschlagsliste (die hat für eine große Karte zu wenig Höhe)."""

    def __init__(self, ueber):
        self.ueber, self._sichtbar = ueber, False
        self.card = ui.Card(ueber.master, pad=0)
        self.lbl = tk.Label(self.card.body, bg=C["surface"], fg=C["subtext"], font=F["bold"],
                            justify="center", wraplength=S(640))
        self.lbl.pack(expand=True)

    def zeigen(self, text):
        if self.lbl.cget("text") != text:
            self.lbl.config(text=text)
        if not self._sichtbar:
            self._sichtbar = True
            self.card.place(in_=self.ueber, x=0, y=0, relwidth=1, relheight=1)
            self.card.lift()

    def verbergen(self):
        if self._sichtbar:
            self._sichtbar = False
            self.card.place_forget()


class _Willkommen:
    """Die Anleitung in drei Schritten – über der oberen Liste, solange nichts eingetippt ist. Dort ist
    dann ohnehin Platz; sobald gesucht wird, bekommt die Liste die ganze Höhe."""

    def __init__(self, app, ueber):
        self.ueber, self._sichtbar = ueber, False
        self.card = ui.Card(ueber.master, pad=0)
        self.inhalt = tk.Frame(self.card.body, bg=C["surface"])
        self.inhalt.pack(expand=True, fill="x", padx=S(20))
        self.titel = tk.Label(self.inhalt, text="So findest du ein Angebot", bg=C["surface"], fg=C["text"],
                              font=F["big"])
        self.titel.pack()
        schritte = self.schritte = tk.Frame(self.inhalt, bg=C["surface"])
        schritte.pack(fill="x", pady=(S(12), 0))
        felder = []
        for ic, titel, text in SCHRITTE:
            f = tk.Frame(schritte, bg=C["surface2"], padx=S(12), pady=S(10))
            ui.RoundIcon(f, ic, 40, bg=C["surface2"]).pack(side="left", anchor="n", padx=(0, S(10)))
            t = tk.Frame(f, bg=C["surface2"])
            t.pack(side="left", fill="both", expand=True)
            tk.Label(t, text=titel, bg=C["surface2"], fg=C["text"], font=F["h3"], anchor="w").pack(fill="x")
            ui.wrap_label(t, text, bg=C["surface2"], fg=C["subtext"], font=F["base"]).pack(fill="x")
            felder.append(f)
        self.felder = felder
        app._reflow(schritte, felder, 300, gap=10)
        self.legende = ui.wrap_label(self.inhalt, "So liest du die Listen:  " + LEGENDE, bg=C["surface"],
                                     fg=C["subtext"], font=F["base"])
        self.legende.pack(fill="x", pady=(S(10), 0))

    def zeigen(self):
        if not self._sichtbar:
            self._sichtbar = True
            self.card.place(in_=self.ueber, x=0, y=0, relwidth=1, relheight=1)
            self.card.lift()

    def verbergen(self):
        if self._sichtbar:
            self._sichtbar = False
            self.card.place_forget()


class RaussuchenTab:
    """Der Reiter. app muss bieten: week, cfg, tabs, _busy, _schluss, _tree(), _sort_marks(), _reflow(),
    _field_label(), _min_rabatt(), _save_cfg(), scan(), _zu_einstellungen(), _zu_haendlern(),
    extra_hinzufuegen(typ, text, angebot) -> bool. zur_liste() wechselt zum Reiter „Einkaufsliste“."""

    def __init__(self, app, page, zur_liste):
        self.app, self.page, self.zur_liste = app, page, zur_liste
        self._after = None
        self._daten = None              # extras.angebote(app) – erst, wenn der Reiter gebraucht wird
        self._veraltet = True
        self._gesucht = None            # Suchtext, für den die Listen gerade gefüllt sind
        self._gemeint = None            # „meintest du …“ bei Tippfehlern
        self._enter_fuer = None         # zweites Enter ohne Treffer = ohne Preis aufschreiben
        self.rows1, self.rows2 = {}, {}     # iid -> (angebot, name, preis, vorher, geschätzt)
        self._min = (0, 0)              # Mindesthöhen oben (Karte) und unten (eine Zeile)
        self._unten_da = True           # untere Liste sichtbar (fällt nur in sehr kleinen Fenstern weg)
        self._letzter = None            # letzter Zustand (text, hits, alts) – für den Hinweistext
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=S(8), pady=(0, S(4)))
        self._kompakt = False
        self._kopf(wrap)
        self._unten(wrap)
        self._mitte(wrap)
        wrap.bind("<Configure>", self._hoehe, add="+")

    # ── Aufbau ────────────────────────────────────────────────────────────────
    def _kopf(self, wrap):
        card = self.kopf = ui.Card(wrap, pad=12, padx=16)
        card.pack(fill="x")
        b = card.body
        zeile = self.titelzeile = tk.Frame(b, bg=C["surface"])
        zeile.pack(fill="x")
        ui.RoundIcon(zeile, "🔎", 48).pack(side="left", anchor="n", padx=(0, S(12)))
        Btn(zeile, "So geht's", self._hilfe, kind="light", icon="❓",
            tip="Kurze Anleitung zu diesem Reiter").pack(side="right", anchor="n", padx=(S(10), 0))
        txt = tk.Frame(zeile, bg=C["surface"])
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text="Angebot raussuchen", bg=C["surface"], fg=C["text"], font=F["big"],
                 anchor="w").pack(fill="x")
        self.unterzeile = ui.wrap_label(txt, "Hier findest du gezielt Angebote für einen Artikel – mit allen "
                                             "Sorten und Marken. Dazu siehst du ähnliche Produkte, die gerade "
                                             "stark reduziert sind.",
                                        bg=C["surface"], fg=C["subtext"], font=F["base"])
        self.unterzeile.pack(fill="x")

        # Suchfeld – groß, mit Beispiel im Feld und Beispiel-Knöpfen darunter
        self.such = tk.Frame(b, bg=C["surface"])
        self.such.pack(fill="x", pady=(S(12), 0))
        self.feldname = self.app._field_label(self.such, "Wonach suchst du?")
        self.feldname.pack(fill="x")
        reihe = self.reihe = tk.Frame(self.such, bg=C["surface"])
        reihe.pack(fill="x", pady=(S(4), 0))
        self.such_btn = Btn(reihe, "Suchen", self._suchen_klick, kind="primary", icon="🔎", font=F["big"],
                            padx=18, pady=8, tip="Angebote suchen (Enter). Die Liste sucht auch schon beim Tippen.")
        self.such_btn.pack(side="right", padx=(S(10), 0))
        # nur bei wenig Höhe sichtbar – dann fällt die Titelzeile mit ihrem „So geht's“ weg
        self.hilfe2 = Btn(reihe, "So geht's", self._hilfe, kind="light", icon="❓", padx=12, pady=8,
                          tip="Kurze Anleitung zu diesem Reiter")
        Btn(reihe, "Leeren", self.leeren, kind="light", icon="🧹", padx=12, pady=8,
            tip="Suchfeld leeren und neu anfangen (Esc)").pack(side="right", padx=(S(10), 0))
        self.q = tk.StringVar()
        self.entry = ttk.Entry(reihe, textvariable=self.q, font=F["big"], width=1)
        self.entry.pack(side="left", fill="both", expand=True)
        ui.Platzhalter(self.entry, self.q, "z. B. Duschgel, Deo oder Axe", font=F["big"])
        ToolTip(self.entry, "Sorte oder Marke eintippen – die Listen suchen schon beim Tippen.\n"
                            "Mehrere Wörter grenzen ein, z. B. „Duschgel Axe“.\n"
                            "Enter markiert das beste Angebot, ein zweites Enter schreibt es auf.", delay=TIP)
        self.q.trace_add("write", lambda *_: self._spaeter())
        self.entry.bind("<Return>", self._enter)
        self.entry.bind("<KP_Enter>", self._enter)
        self.entry.bind("<Down>", self._runter)
        self.entry.bind("<Escape>", lambda e: self.leeren())

        # Beispiel-Knöpfe fließen in so viele Zeilen, wie die Breite verlangt (200 %, schmales Fenster)
        chips = self.chips = tk.Frame(self.such, bg=C["surface"], height=1)
        chips.pack(fill="x", pady=(S(8), 0))
        self._chip_teile = [tk.Label(chips, text="Zum Ausprobieren:", bg=C["surface"], fg=C["subtext"],
                                     font=F["small_bold"])]
        for w in BEISPIELE:
            self._chip_teile.append(Btn(chips, w, lambda w=w: self.suche_setzen(w), kind="light",
                                        font=F["small_bold"], padx=10, pady=4, tip=f"Nach „{w}“ suchen"))
        self._chip_breite = 0
        chips.bind("<Configure>", self._chips_umbrechen, add="+")

    def _chips_umbrechen(self, e):
        """Beispiel-Knöpfe zeilenweise anordnen; die Höhe des Rahmens folgt der Zeilenzahl."""
        if e.width == self._chip_breite or e.width < 50:
            return
        self._chip_breite = e.width
        zeilen, x = [[]], 0
        for w in self._chip_teile:
            bw = w.winfo_reqwidth()
            if zeilen[-1] and x + bw > e.width:
                zeilen.append([])
                x = 0
            zeilen[-1].append((w, x))
            x += bw + S(6)
        y = 0
        for zeile in zeilen:
            hoch = max(w.winfo_reqheight() for w, _ in zeile)
            for w, x in zeile:
                w.place(x=x, y=y + (hoch - w.winfo_reqheight()) // 2)
            y += hoch + S(6)
        self.chips.configure(height=y - S(6))

    def _unten(self, wrap):
        card = self.unten = ui.Card(wrap, pad=10, padx=16)
        card.pack(side="bottom", fill="x", pady=(S(6), 0), before=self.kopf)    # wird zuletzt eng
        b = card.body
        knoepfe = tk.Frame(b, bg=C["surface"])
        knoepfe.pack(side="right")
        self.auf_btn = Btn(knoepfe, "Auf die Einkaufsliste", self.hinzufuegen, kind="primary", icon="➕",
                           font=F["big"], padx=18, pady=9,
                           tip="Das angeklickte Angebot mit Preis auf die Einkaufsliste setzen\n"
                               "(oder doppelt auf das Angebot klicken)")
        self.auf_btn.pack(side="right")
        self.ohne_btn = Btn(knoepfe, "Ohne Angebot aufschreiben", self.ohne_angebot, kind="sky", icon="✏️",
                            padx=12, pady=8, tip="Den eingetippten Artikel ohne Preis auf die Einkaufsliste "
                                                 "setzen – z. B. wenn dir kein Angebot zusagt")
        self.ohne_btn.pack(side="right", padx=(0, S(10)))
        Btn(knoepfe, "Einkaufsliste ansehen", self.zur_liste, kind="light", icon="📝", padx=12, pady=8,
            tip="Zum Reiter „Einkaufsliste“ wechseln").pack(side="right", padx=(0, S(10)))
        self.status = ui.wrap_label(b, "", bg=C["surface"], fg=C["subtext"], font=F["bold"])
        self.status.pack(side="left", fill="x", expand=True, padx=(0, S(14)))

    def _mitte(self, wrap):
        m = self.m = tk.Frame(wrap, bg=C["bg"])
        m.pack(fill="both", expand=True)
        m.columnconfigure(0, weight=1)
        m.rowconfigure(1, weight=3)         # obere Liste etwas höher; Mindesthöhe setzt _platz()
        m.rowconfigure(3, weight=2)
        self.k1 = self._ueberschrift(m, 0, "🛒")
        self.k2 = self._ueberschrift(m, 2, "💡")
        box1, box2 = tk.Frame(m, bg=C["bg"]), tk.Frame(m, bg=C["bg"])
        box1.grid(row=1, column=0, sticky="nsew")
        box2.grid(row=3, column=0, sticky="nsew")

        app = self.app
        self.tv = app._tree(box1, [("haendler", "Händler", 175), ("produkt", "Produkt", 250),
                                   ("info", "Info", 220), ("preis", "Preis", 82), ("alt", "Vorher", 82),
                                   ("rabatt", "Rabatt", 90), ("gueltig", "Gültig", 112)],
                            flex=("produkt", "info"))
        self.tv2 = app._tree(box2, [("warum", "Warum vorgeschlagen", 200), ("haendler", "Händler", 150),
                                    ("produkt", "Produkt", 220), ("info", "Info", 180), ("preis", "Preis", 82),
                                    ("alt", "Vorher", 82), ("rabatt", "Rabatt", 90), ("gueltig", "Gültig", 112)],
                             flex=("produkt", "info"))
        legende = ("Preis = was du zahlst · Vorher = normaler Preis · ~ = geschätzt\n"
                   "✔ = steht schon auf deiner Einkaufsliste · Spaltenkopf anklicken = sortieren")
        ToolTip(self.tv, "Angebot anklicken, dann „Auf die Einkaufsliste“ – oder doppelt klicken.\n" + legende,
                delay=TIP)
        ToolTip(self.tv2, "Produkte, die gerade stark reduziert sind (ab 25 % billiger als sonst):\n"
                          "gleiche Sorte einer anderen Marke, etwas Ähnliches oder aus derselben Abteilung.\n"
                          + legende, delay=TIP)
        for tv, rows, andere in ((self.tv, self.rows1, self.tv2), (self.tv2, self.rows2, self.tv)):
            tv.configure(style="Gross.Treeview", height=3 if tv is self.tv else 2)
            tv.heading("rabatt", anchor="center")       # sonst klebt „-26 %“ an „bis Sa.“
            tv.column("rabatt", anchor="center")
            tv.bind("<<TreeviewSelect>>", lambda e, t=tv, r=rows, a=andere: self._gewaehlt(t, r, a))
            tv.bind("<Double-1>", lambda e, t=tv: self.hinzufuegen() if t.identify_row(e.y) else None)
            tv.bind("<Return>", lambda e: self.hinzufuegen())
            tv.bind("<KP_Enter>", lambda e: self.hinzufuegen())

        self.frage_var = tk.BooleanVar(value=not ext.fragen(app))
        self.frage_var.trace_add("write", lambda *_: self._frage_umgestellt())
        self.karte = ext._FrageKarte(self.tv._card, self.frage_var, kompakt=True)
        self.willkommen = _Willkommen(app, self.tv._card)
        self.leer2 = _LeerZeile(self.tv2._card)
        for teil in (self.karte.inhalt, self.willkommen.inhalt, self.m):   # Umbruch, Fenstergröße
            teil.bind("<Configure>", self._platz, add="+")

    def _ueberschrift(self, parent, row, icon):
        f = tk.Frame(parent, bg=C["bg"])
        f.grid(row=row, column=0, sticky="ew", pady=(S(10), S(4)))
        ic = ui.RoundIcon(f, icon, 30, bg=C["bg"])
        ic.pack(side="left", padx=(S(4), S(8)))
        titel = tk.Label(f, bg=C["bg"], fg=C["text"], font=F["h3"], anchor="w")
        titel.pack(side="left")
        sub = ui.wrap_label(f, "", bg=C["bg"], fg=C["subtext"], font=F["base"])
        sub.pack(side="left", fill="x", expand=True, padx=(S(12), 0))
        return ic, titel, sub

    # ── Hilfe und Platz ───────────────────────────────────────────────────────
    def _hilfe(self):
        messagebox.showinfo("So geht's: Angebot raussuchen",
                            "\n\n".join(f"{titel}\n{text}" for _, titel, text in SCHRITTE)
                            + "\n\nSo liest du die Listen\n" + LEGENDE.replace("  ", "\n"),
                            parent=self.app)
        self.entry.focus_set()

    def _hoehe(self, e):
        """Wenig Höhe (Laptop mit 1366×768, 150 % auf Full HD): Titelzeile, Feldname, Beispiel-Knöpfe und die
        Lese-Hilfe ausblenden und die Überschriften der Listen flacher machen, damit beide Listen und die
        Knöpfe unten sichtbar bleiben. „So geht's“ rückt neben das Suchfeld, dort steht alles noch einmal."""
        kompakt = e.height < S(640)
        if kompakt == self._kompakt:
            return
        self._kompakt = kompakt
        wk = self.willkommen
        if kompakt:
            for w in (self.titelzeile, self.feldname, self.chips, wk.titel, wk.legende):
                w.pack_forget()
            self.such.pack_configure(pady=0)
            self.reihe.pack_configure(pady=0)
            wk.schritte.pack_configure(pady=0)
            self.hilfe2.pack(side="right", padx=(S(10), 0), before=self.such_btn)
        else:
            self.hilfe2.pack_forget()
            self.titelzeile.pack(fill="x", before=self.such)
            self.such.pack_configure(pady=(S(12), 0))
            self.feldname.pack(fill="x", before=self.reihe)
            self.reihe.pack_configure(pady=(S(4), 0))
            self.chips.pack(fill="x", pady=(S(8), 0))
            wk.titel.pack(before=wk.schritte)
            wk.schritte.pack_configure(pady=(S(12), 0))
            wk.legende.pack(fill="x", pady=(S(10), 0))
        for ic, titel, _ in (self.k1, self.k2):
            if kompakt:
                ic.pack_forget()
            else:
                ic.pack(side="left", padx=(S(4), S(8)), before=titel)
            ic.master.grid_configure(pady=self._kopf_pady())
        if kompakt:                             # „10 gefunden“ steht auch unten in der Statuszeile
            self.k1[0].master.grid_remove()
        if not self._unten_da:                  # grid_configure hat die Überschrift wieder eingeblendet
            self.k2[0].master.grid_remove()
        self.kopf.body.configure(pady=S(6 if kompakt else 12))
        self.unten.body.configure(pady=S(5 if kompakt else 10))
        for karte in (self.kopf, self.unten, self.tv._card, self.tv2._card, wk.card, self.karte.card,
                      self.leer2.card):
            karte.set_margin(5 if kompakt else 10)
        for f in wk.felder:
            f.configure(pady=S(6 if kompakt else 10))
        self.tv2.configure(height=1 if kompakt else 2)    # bei wenig Platz hat die obere Liste Vorrang
        # die großen Knöpfe eine Stufe kleiner – immer noch größer als die übrigen
        self.such_btn.set_font(F["h3"] if kompakt else F["big"], pady=6 if kompakt else 8)
        self.auf_btn.set_font(F["h3"] if kompakt else F["big"], pady=7 if kompakt else 9)
        self.karte.eng(kompakt)
        self._platz()
        self.m.after_idle(self._platz_spaeter)  # nochmal, wenn die neuen Größen feststehen

    def _platz(self, _=None):
        """Die obere Liste mindestens so hoch machen, wie die Karte darüber braucht – sonst würde sie bei
        200 % oder auf kleinen Bildschirmen abgeschnitten. Die untere Liste gibt dann Höhe ab. Wird es
        dafür zu eng, fällt das Icon der Frage-Karte weg (der Titel sagt dasselbe)."""
        k, wk = self.karte, self.willkommen
        p = sum(self._kopf_pady())
        k1, k2, box2 = self.k1[0].master, self.k2[0].master, self.tv2._card.master
        frei = self.m.winfo_height() - (k1.winfo_reqheight() + p if k1.winfo_manager() else 0)
        # Überschrift + kleinste untere Liste; deren Schattenrand unten darf abgeschnitten werden
        box = box2.winfo_reqheight() - self.tv2._card.m
        unten = k2.winfo_reqheight() + p + box
        zeile = int(ttk.Style().lookup("Gross.Treeview", "rowheight") or S(30))
        need = klein = 0
        if wk._sichtbar:
            need = klein = wk.inhalt.winfo_reqheight() + 2 * wk.card.m + S(8)
        elif k._sichtbar:
            ic = k.icon.winfo_reqheight()
            mit = bool(k.icon.winfo_manager())
            voll = k.inhalt.winfo_reqheight() + 2 * k.card.m + S(8) + (0 if mit else ic)
            klein = voll - ic
            rest = frei - (unten + zeile if self._unten_da else 0)     # unten eine Zeile mehr als nötig frei
            soll = frei <= 1 or rest >= voll + S(10)
            if soll != mit:
                if soll:
                    k.icon.pack(before=k.titel)
                else:
                    k.icon.pack_forget()
            need = voll if soll else klein
        # Sehr kleines Fenster: Zeigt die untere Liste nicht einmal eine Zeile, fällt sie ganz weg –
        # besser als ein leerer Streifen. Kommt wieder, sobald es genug Platz gibt.
        # Puffer beim Zurückholen: Mit dem Satz „Unten stehen …“ wird die Karte wieder etwas höher.
        if frei > 1:
            zurueck = 2 * tkfont.Font(font=F["base"]).metrics("linespace") + S(8)
            da = frei - klein >= unten + (0 if self._unten_da else zurueck)
            if da != self._unten_da:
                self._unten_da = da
                for w in (k2, box2):
                    if da:
                        w.grid()
                    else:
                        w.grid_remove()
                self.m.rowconfigure(3, weight=2 if da else 0)
                t = self._letzter
                if t and t[0] and not t[1] and t[2] and k._sichtbar:
                    self._zustand_roh(*t)                   # Text „Unten stehen …“ anpassen
        # Mindesthöhen: oben die Karte, unten mindestens eine ganze Zeile (sonst schrumpft sie auf null)
        mins = (need, box if self._unten_da else 0)
        if mins != self._min:
            self._min = mins
            self.m.rowconfigure(1, minsize=mins[0])
            self.m.rowconfigure(3, minsize=mins[1])

    def _platz_spaeter(self):
        try:
            self._platz()
        except tk.TclError:                 # Fenster schon zu
            pass

    def _kopf_pady(self):
        """Abstand der Überschriften über den Listen."""
        return (S(4), 0) if self._kompakt else (S(10), S(4))

    # ── Lebenszyklus (wie im Reiter „Gerichte“) ───────────────────────────────
    def _sichtbar(self):
        t = self.app.tabs
        return 0 <= t.current < len(t.pages) and t.pages[t.current] is self.page

    def daten_geaendert(self):
        """Neue Woche, neuer Scan, andere Händler oder Rabatt-Filter: Angebote neu einlesen."""
        self._daten = None
        if self._sichtbar():
            self.fuellen()
        else:
            self._veraltet = True

    def tab_gewaehlt(self):
        soll = not ext.fragen(self.app)         # „Nicht mehr fragen“ kann in den Einstellungen umgestellt sein
        if self.frage_var.get() != soll:
            self.frage_var.set(soll)
        if self._veraltet:
            self.fuellen()
        else:
            self._marken()                      # Einkaufsliste kann sich geändert haben
        self.entry.focus_set()

    def schliessen(self):
        """Beim Beenden: wartende Suche verwerfen."""
        if self._after:
            try:
                self.app.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    # ── Suchen und Füllen ─────────────────────────────────────────────────────
    def _text(self):
        return " ".join(self.q.get().split())

    def suche_setzen(self, text):
        self.q.set(text)
        self.fuellen()
        self.entry.focus_set()
        self.entry.icursor("end")

    def leeren(self):
        self.q.set("")
        self.fuellen()
        self.entry.focus_set()
        return "break"

    def _spaeter(self):
        if getattr(self.app, "_schluss", False):
            return
        self.schliessen()
        self._after = self.app.after(SUCH_DELAY, self.fuellen)

    def _suchen_klick(self):
        self.fuellen()
        self.entry.focus_set()

    def fuellen(self):
        self.schliessen()
        if getattr(self.app, "_schluss", False):
            return
        try:
            self._fuellen_roh()
        except tk.TclError:             # Fenster wird gerade geschlossen
            pass

    def _fuellen_roh(self):
        app = self.app
        self._veraltet = False
        if self._daten is None:
            self._daten = ext.angebote(app)
        daten, text = self._daten, self._text()
        if text != self._gesucht:
            self._enter_fuer = None
        self._gesucht, self._gemeint = text, None
        self.ohne_btn.set_enabled(bool(text))
        hits = []
        if text:
            such = sb.Suche(text)
            hits = ext.treffer(daten, such)
            if not hits and daten:
                vor = sb.vorschlag(text, (d[1] for d in daten))
                if vor:
                    s2 = sb.Suche(vor)
                    h2 = ext.treffer(daten, s2)
                    if h2:
                        hits, such, self._gemeint = h2, s2, vor
            alts = alternativen(daten, such, hits)
        else:
            alts = top(daten)
        auf = self._auf_liste()
        self._zeilen(self.tv, self.rows1, ((None, d) for d in hits[:MAX_TREFFER]), auf)
        self._zeilen(self.tv2, self.rows2, alts, auf)
        self._ueberschriften(text, hits)
        self._zustand(text, hits, alts)

    def _auf_liste(self):
        extras = (self.app.week.get("liste") or {}).get("extras", [])
        return {x["angebot"].get("id") for x in extras if x.get("angebot")} - {None}

    def _zeilen(self, tv, rows, liste, auf):
        tv.delete(*tv.get_children())
        rows.clear()
        if tv._sorted:
            tv._sorted = None
            self.app._sort_marks(tv)
        for n, (grund, (rab, o, name, p, v, est)) in enumerate(liste):
            iid = str(n)
            werte = (o["haendler"], ("✔ " if o.get("id") in auf else "") + name, o.get("info") or "",
                     ext._eur(p), pl.eur(v, est) if v else "",
                     f"{'~ ' if est else ''}-{rab} %" if rab is not None else "–", gueltig(o))
            tv.insert("", "end", iid=iid, tags=("odd",) if n % 2 else (),
                      values=werte if grund is None else (grund,) + werte)
            rows[iid] = (o, name, p, v, est)

    def _marken(self):
        """„✔“ vor den Produkten auffrischen, die (nicht mehr) auf der Einkaufsliste stehen."""
        auf = self._auf_liste()
        try:
            for tv, rows in ((self.tv, self.rows1), (self.tv2, self.rows2)):
                for iid, (o, name, *_rest) in rows.items():
                    soll = ("✔ " if o.get("id") in auf else "") + name
                    if tv.set(iid, "produkt") != soll:
                        tv.set(iid, "produkt", soll)
        except tk.TclError:
            pass

    def _ueberschriften(self, text, hits):
        ic1, t1, s1 = self.k1
        ic2, t2, s2 = self.k2
        if text:
            n = len(hits)
            t1.config(text=f"Angebote für „{self._gemeint or text}“")
            s1.config(text=(f"{n} gefunden – die {MAX_TREFFER} besten stehen oben" if n > MAX_TREFFER else
                            f"{n} gefunden" if n else ""))
            ic2.set("💡")
            t2.config(text="Ähnliche Produkte – gerade stark reduziert")
            s2.config(text="ab 25 % billiger als sonst")
        else:
            t1.config(text="Angebote für deinen Artikel")
            s1.config(text="")
            ic2.set("🔥")
            t2.config(text="Diese Woche stark reduziert")
            s2.config(text="Lebensmittel und Drogerie, ab 25 % billiger als sonst")

    def _melden(self, text, farbe=None):
        self.status.config(text=text, fg=farbe or C["subtext"])

    def _zustand(self, text, hits, alts):
        """Hinweiskarten und Statuszeile passend zur Lage: Treffer, keine Treffer, nichts geladen …"""
        self._letzter = (text, hits, alts)
        self._zustand_roh(text, hits, alts)
        if self._daten and not text and not self.app._busy:
            self.karte.verbergen()
            self.willkommen.zeigen()
        else:
            self.willkommen.verbergen()
        self._platz()

    def _zustand_roh(self, text, hits, alts):
        app = self.app
        if alts:
            self.leer2.verbergen()
        elif not self._daten:
            self.leer2.zeigen("Hier erscheinen Produkte, die gerade stark reduziert sind.")
        elif text:
            self.leer2.zeigen("Gerade nichts Ähnliches stark reduziert.")
        else:
            self.leer2.zeigen("Diese Woche ist bei deinen Händlern nichts stark reduziert.")

        if text and hits:
            self.karte.verbergen()
            n = len(hits)
            if self._gemeint:
                self._melden(f"Zu „{text}“ gibt es nichts – meintest du „{self._gemeint}“? Dafür gibt es "
                             f"{n} Angebot{'e' if n != 1 else ''}. Anklicken und „Auf die Einkaufsliste“ "
                             "drücken.", C["orange"])
            else:
                self._melden(f"{n} Angebot{'e' if n != 1 else ''} gefunden. Klick eins an und drück dann "
                             "„Auf die Einkaufsliste“.")
            return
        ohne = [("Ohne Preis aufschreiben", self.ohne_angebot, "sky", "✏️")] if text else []
        if app._busy:
            self.karte.zeigen("⏳", "Die Angebote werden gerade geladen …",
                              "Das dauert etwa eine Minute. Die Listen füllen sich danach von selbst.")
            self._melden("Bitte kurz warten – die Prospekte werden geladen.")
        elif not app.cfg.get("plz"):
            self.karte.zeigen("📍", "Zuerst die Postleitzahl eintragen",
                              "Essens-Plan braucht deine Postleitzahl, um die Prospekte aus deiner Gegend "
                              "zu laden. Das geht in den Einstellungen.",
                              [("Postleitzahl eintragen", app._zu_einstellungen, "primary", "⚙️")] + ohne)
            self._melden("Ohne Postleitzahl gibt es keine Angebote.")
        elif not app.week.get("offers"):
            self.karte.zeigen("🔍", "Noch keine Angebote geladen",
                              "Für diese Woche sind noch keine Prospekte da. Ein Klick lädt sie "
                              "(dauert etwa eine Minute).",
                              [("Angebote laden (F5)", app.scan, "primary", "🔍")] + ohne)
            self._melden("Zuerst die Angebote laden.")
        elif not self._daten:
            self.karte.zeigen("🏪", "Deine Händler haben diese Woche keine Angebote", ext.leer_text(app),
                              [("Händler ändern", app._zu_haendlern, "primary", "⚙️")] + ohne)
            self._melden("Bei den angehakten Händlern gibt es diese Woche nichts.", C["orange"])
        elif not text:
            self._melden("Tippe oben ein, was du brauchst – z. B. „Duschgel“ oder „Axe“.")
        else:
            name = ext._gross(text)
            unten = (" Unten stehen ähnliche Produkte, die gerade stark reduziert sind."
                     if alts and self._unten_da else "")
            self.karte.zeigen("🔎", f"Kein Angebot für „{name}“",
                              f"Bei deinen Händlern ist diese Woche nichts dazu im Angebot.{unten}\n"
                              f"Soll „{name}“ ohne Preis auf die Einkaufsliste?",
                              [("Ja, ohne Preis aufschreiben", self.ohne_angebot, "primary", "✏️"),
                               ("Nein, anders suchen", self._nein, "light", None)],
                              check=True)
            self._melden("Kein Angebot gefunden. Anders schreiben, eine Marke versuchen – oder ohne Preis "
                         "aufschreiben.")

    def _frage_umgestellt(self):
        try:
            ext.setze_fragen(self.app, not self.frage_var.get())
        except tk.TclError:
            pass

    # ── Auswahl und Aufschreiben ──────────────────────────────────────────────
    def _gewaehlt(self, tv, rows, andere):
        sel = tv.selection()
        if not sel or sel[0] not in rows:
            return
        if andere.selection():
            andere.selection_remove(*andere.selection())
        o, name, p, *_rest = rows[sel[0]]
        if o.get("id") is not None and o.get("id") in self._auf_liste():
            self._melden(f"„{name}“ bei {o['haendler']} steht schon auf deiner Einkaufsliste (✔).", C["text"])
        else:
            self._melden(f"Ausgewählt: {name} bei {o['haendler']} für {ext._eur(p)}. "
                         "Jetzt „Auf die Einkaufsliste“ drücken.", C["text"])

    def _auswahl(self):
        for tv, rows in ((self.tv, self.rows1), (self.tv2, self.rows2)):
            sel = tv.selection()
            if sel and sel[0] in rows:
                return rows[sel[0]]
        return None

    def _runter(self, _=None):
        for tv in (self.tv, self.tv2):
            kids = tv.get_children()
            if kids:
                tv.selection_set(kids[0])
                tv.focus(kids[0])
                tv.see(kids[0])
                tv.focus_set()
                return "break"
        return "break"

    def _enter(self, _=None):
        """Enter im Suchfeld: sofort suchen und das beste Angebot markieren (Enter in der Liste schreibt
        es auf). Ohne Treffer fragt erst die Karte – ein zweites Enter heißt „Ja, ohne Preis“, außer
        „Nicht mehr fragen“ ist an: dann sofort."""
        if self._after or self._gesucht != self._text():
            self.fuellen()
        text = self._text()
        if not text:
            self._melden("Zuerst oben eintippen, was du brauchst.", C["orange"])
        elif self.rows1:
            self._runter()
            self._melden("Das beste Angebot ist markiert. Noch einmal Enter schreibt es auf die Einkaufsliste.",
                         C["text"])
        elif not ext.fragen(self.app) or self._enter_fuer == text:
            self.ohne_angebot()
        else:
            self._enter_fuer = text
            self._melden("Kein Angebot gefunden. Noch einmal Enter schreibt den Artikel ohne Preis auf.",
                         C["orange"])
        return "break"

    def hinzufuegen(self):
        wahl = self._auswahl()
        if not wahl:
            self._melden("Zuerst ein Angebot in einer der Listen anklicken – oder „Ohne Angebot "
                         "aufschreiben“ drücken.", C["orange"])
            return "break"
        o, name, p, v, est = wahl
        neu = self.app.extra_hinzufuegen("produkt", name, ext.eintrag(o, name, p, v, est))
        if neu:
            self._melden(f"✔ {name} ({o['haendler']}, {ext._eur(p)}) steht jetzt auf deiner Einkaufsliste.",
                         C["green"])
        else:
            self._melden(f"„{name}“ steht schon auf deiner Einkaufsliste.", C["orange"])
        self._marken()
        return "break"

    def ohne_angebot(self):
        text = ext._gross(self._text())
        if not text:
            self._melden("Zuerst oben eintippen, was du brauchst.", C["orange"])
            self.entry.focus_set()
            return
        neu = self.app.extra_hinzufuegen("produkt", text, None)
        if neu:
            self.q.set("")
            self.fuellen()
            self._melden(f"✔ {text} steht jetzt ohne Preis auf deiner Einkaufsliste. Du kannst gleich den "
                         "nächsten Artikel eintippen.", C["green"])
        else:
            self._melden(f"„{text}“ steht schon auf deiner Einkaufsliste.", C["orange"])
        self.entry.focus_set()

    def _nein(self):
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self._melden("Schreib es anders oder versuch eine Marke – z. B. „Nivea“ statt „Creme“.")
