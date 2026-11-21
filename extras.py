"""Zusatzfenster der Einkaufsliste: Artikel hinzufügen (erst Angebote vorschlagen, sonst ohne Preis),
Rückfrage „ohne Angebot aufschreiben?“ und Notiz schreiben.

Alle Fenster sind Kinder des Hauptfensters (transient), im aktuellen Design und dürfen jederzeit
mit ihm zusammen geschlossen werden – auch mitten in der Suche, auch beim Neustart für Hell/Dunkel."""
import tkinter as tk
from tkinter import ttk

import planner as pl
import suchbegriffe as sb
import ui
from ui import Btn
from utils import C, F, S, ToolTip

MAX_ZEILEN = 300            # mehr Zeilen braucht niemand; die Suche grenzt weiter ein
SUCH_DELAY = 250            # ms Entprellung der Live-Suche
BEISPIELE = "z. B. Brot, Obst, Alkohol, Duschgel, Axe, Klopapier, Katzenstreu"


def _eur(v):
    return f"{v:.2f} €".replace(".", ",")


def _gross(text):
    text = " ".join(text.split())
    return text[:1].upper() + text[1:]


def fragen(app):
    """True = vor dem Aufschreiben ohne Angebot nachfragen (Einstellung „artikel_fragen“)."""
    return bool(app.cfg.get("artikel_fragen", True))


def setze_fragen(app, an):
    """Einstellung umschalten und gleich sichern; das Kästchen in den Einstellungen zieht mit."""
    an = bool(an)
    if fragen(app) == an:
        return
    app.cfg["artikel_fragen"] = an
    var = getattr(app, "frag_var", None)
    if var is not None:
        try:
            var.set(an)
        except tk.TclError:
            pass
    app._save_cfg()


def angebote(app):
    """Alle Angebote der erlaubten Händler – auch ohne Vergleichspreis (Drogerie-Prospekte nennen oft
    keinen), mit Rabatt-Filter: Angebote mit bekanntem Rabatt unter dem Mindestwert fallen weg.
    Rückgabe: Liste (rabatt|None, angebot, name, preis, vorher|None, geschätzt)."""
    cfg = app.cfg
    ok = pl.erlaubt(cfg.get("haendler"))
    mn = app._min_rabatt()
    out = []
    for o in app.week.get("offers", []):
        if not ok(o["haendler"]):
            continue
        p, v = pl.eff_price(o, cfg), pl.vorher(o, cfg)
        rab = round((1 - p / v) * 100) if v else None
        if rab is not None and rab <= 0:
            rab, v = None, None
        if mn is not None and rab is not None and rab < mn:
            continue
        est = bool(v) and pl.vorher(o, cfg, schaetzen=False) is None
        out.append((rab, o, name_von(o), p, v, est))
    return out


def leere_haendler(app):
    """Angehakte Händler ohne ein einziges Angebot in dieser Woche (marktguru führt ihren
    Prospekt gerade nicht). Leer, wenn nichts angehakt ist (= alle) oder nichts geladen ist."""
    namen = {o["haendler"] for o in app.week.get("offers", [])}
    if not namen:
        return []
    return [h for h in app.cfg.get("haendler") or [] if not any(pl.erlaubt((h,))(n) for n in namen)]


def leer_text(app):
    """Erklärung, wenn bei den angehakten Händlern gar nichts im Angebot ist."""
    leer = leere_haendler(app)
    namen = ", ".join(leer) or "Deine Händler"
    return (f"Angehakt: {namen}. Dafür hat marktguru, woher Essens-Plan die Angebote bekommt, diese Woche "
            "keine Angebote – das kann an marktguru liegen oder der Händler hat keinen Prospekt "
            "veröffentlicht. Darum findet die Suche nichts. Hake in den Einstellungen weitere Händler an "
            "(oder entferne alle Haken = alle Händler). Dort kannst du dir auch den letzten Prospekt ansehen.")


def treffer(daten, such):
    """Passende Angebote, beste zuerst: Sorte/Name vor Marke vor Info-Text, dann Rabatt, dann Preis."""
    hits = []
    for d in daten:
        pkt = such.passt(d[1])
        if pkt:
            hits.append((pkt, d))
    hits.sort(key=lambda x: (-x[0], -(x[1][0] if x[1][0] is not None else -1), x[1][3]))
    return [d for _, d in hits]


def eintrag(o, name, p, v, est):
    """Angebots-Schnappschuss für die Einkaufsliste (extra_hinzufuegen) – bleibt, auch wenn das
    Angebot abläuft oder neu gescannt wird."""
    return {"haendler": o["haendler"], "produkt": name, "info": (o.get("info") or "")[:160],
            "preis": p, "vorher": v, "geschaetzt": est, "id": o.get("id")}


def name_von(o):
    name, marke = o.get("produkt") or "", o.get("marke") or ""
    return f"{marke} {name}".strip() if marke and marke.lower() not in name.lower() else name


def _fenster(app, titel, breite, hoehe):
    """Leeres, noch verstecktes Fenster im Design der App, mittig über dem Hauptfenster."""
    win = tk.Toplevel(app)
    win.withdraw()
    win.title(titel)
    win.configure(bg=C["bg"])
    win.transient(app)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(S(breite), sw - S(60)), min(S(hoehe), sh - S(100))
    try:
        cx = app.winfo_rootx() + app.winfo_width() // 2
        cy = app.winfo_rooty() + app.winfo_height() // 2
    except tk.TclError:
        cx, cy = sw // 2, sh // 2
    x = max(0, min(cx - w // 2, sw - w))
    y = max(0, min(cy - h // 2, sh - h - S(40)))
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.minsize(min(S(560), w), min(S(300), h))
    return win


class _FrageKarte:
    """Karte über der Trefferliste, wenn es nichts zu zeigen gibt: Icon, Titel, Erklärung, bis zu zwei
    Knöpfe und optional das Kästchen „Nicht mehr fragen“. Wie LeerHinweis: einmal gebaut, Texte und
    Knöpfe ändern sich nur, wenn sich wirklich etwas geändert hat."""

    def __init__(self, ueber, frage_var, kompakt=False):
        """kompakt: kleineres Icon und engere Abstände – für Listen, die nur einen Teil der Höhe haben."""
        self.ueber, self._key, self._sichtbar = ueber, None, False
        self.card = ui.Card(ueber.master, pad=0)
        mitte = self.inhalt = tk.Frame(self.card.body, bg=C["surface"])
        mitte.pack(expand=True)
        self.icon = ui.RoundIcon(mitte, "🔎", 44 if kompakt else 64)
        self.icon.pack()
        self.titel = tk.Label(mitte, bg=C["surface"], fg=C["text"], font=F["big"], justify="center")
        self.titel.pack(pady=(S(8 if kompakt else 14), S(4 if kompakt else 6)))
        self.text = tk.Label(mitte, bg=C["surface"], fg=C["subtext"], font=F["base"], justify="center",
                             wraplength=S(620 if kompakt else 520))
        self.text.pack()
        self.zeile = tk.Frame(mitte, bg=C["surface"])
        self.zeile.pack(pady=(S(12 if kompakt else 18), 0))
        self._check_pady = S(8 if kompakt else 14)
        self.knoepfe = []
        self.check = ttk.Checkbutton(mitte, text="Nicht mehr fragen – Artikel ohne Angebot künftig "
                                                 "direkt aufschreiben", variable=frage_var)
        ToolTip(self.check, "Gilt auch für das Eingabefeld in der Einkaufsliste. Wieder einschalten: "
                            "hier oder in den Einstellungen („Ohne Angebot nachfragen“).", delay=500)
        self._check_da, self._kompakt, self._eng = False, kompakt, False
        if kompakt:     # breite, flache Liste: Text breiter umbrechen, Kästchen neben die Knöpfe
            self.card.bind("<Configure>", self._anordnen, add="+")

    def _anordnen(self, _=None):
        w = self.card.winfo_width()
        if w > 1:
            self.text.config(wraplength=max(S(400), min(w - S(80), S(1000))))
        self._check_setzen()

    def _check_setzen(self):
        if not self._check_da:
            self.check.pack_forget()
            return
        w = self.card.winfo_width()
        knoepfe = sum(b.winfo_reqwidth() for b in self.knoepfe) + S(10) * len(self.knoepfe)
        if self._kompakt and self.knoepfe and knoepfe + S(24) + self.check.winfo_reqwidth() <= w - S(40):
            self.check.pack(in_=self.zeile, side="left", after=self.knoepfe[-1], padx=(S(24), 0), pady=0)
        else:
            self.check.pack(in_=self.inhalt, side="top", after=self.zeile, padx=0, pady=(self._check_pady, 0))

    def eng(self, flag):
        """Niedriges Fenster: engere Abstände und ein etwas kleinerer erster Knopf."""
        if flag == self._eng:
            return
        self._eng, k = flag, self._kompakt
        self.titel.pack_configure(pady=(0, S(2)) if flag else (S(8 if k else 14), S(4 if k else 6)))
        self.zeile.pack_configure(pady=(S(6) if flag else S(12 if k else 18), 0))
        self._check_pady = S(4 if flag else 8 if k else 14)
        if self.knoepfe:
            self.knoepfe[0].set_font(F["h3"] if flag else F["big"], pady=7 if flag else 9)
        self._check_setzen()

    def zeigen(self, icon, titel, text, knoepfe=(), check=False):
        """knoepfe: [(text, befehl, kind, icon)]"""
        key = (icon, titel, text, tuple(k[0] for k in knoepfe), check)
        if key != self._key:
            self._key = key
            self.icon.set(icon)
            self.titel.config(text=titel)
            self.text.config(text=text)
            for b in self.knoepfe:
                b.destroy()
            self.knoepfe = []
            for i, (t, cmd, kind, ic) in enumerate(knoepfe):
                gross = i == 0 and not self._eng
                b = Btn(self.zeile, t, cmd, kind=kind, icon=ic,
                        font=F["big"] if gross else F["h3"] if i == 0 else None,
                        padx=18 if i == 0 else 14, pady=9 if gross else 7)
                b.pack(side="left", padx=(0 if i == 0 else S(10), 0))
                self.knoepfe.append(b)
            self._check_da = check
            self._check_setzen()
        else:
            for b, k in zip(self.knoepfe, knoepfe):     # Befehle dürfen sich ändern, ohne neu zu zeichnen
                b.command = k[1]
        if not self._sichtbar:
            self._sichtbar = True
            self.card.place(in_=self.ueber, x=0, y=0, relwidth=1, relheight=1)
            self.card.lift()

    def verbergen(self):
        if self._sichtbar:
            self._sichtbar = False
            self.card.place_forget()


class ArtikelSuche:
    """„Artikel hinzufügen“: Sorte oder Marke eintippen, passende Angebote der erlaubten Händler werden
    vorgeschlagen (alle Sorten, Schreibweise egal). Passt keins, kommt der Artikel ohne Preis auf die
    Liste – mit Rückfrage, solange „Nicht mehr fragen“ nicht angehakt ist.

    app muss bieten: week, cfg, _min_rabatt(), _tree(), _save_cfg(), scan(),
    extra_hinzufuegen(typ, text, angebot|None) -> bool (False = schon vorhanden)."""

    def __init__(self, app, text=""):
        self.app, self._after, self._zu = app, None, False
        self.rows = {}              # iid -> (angebot, name, preis, vorher, geschätzt)
        self._daten = angebote(app)
        self._top = sorted((d for d in self._daten if d[0] is not None), key=lambda d: -d[0])
        win = self.win = _fenster(app, "Artikel hinzufügen", 980, 760)
        win.protocol("WM_DELETE_WINDOW", self.schliessen)
        win.bind("<Escape>", lambda e: self.schliessen())

        kopf = tk.Frame(win, bg=C["bg"])
        kopf.pack(fill="x", padx=S(16), pady=(S(14), S(4)))
        ui.RoundIcon(kopf, "🛒", 44).pack(side="left", padx=(0, S(12)))
        txt = tk.Frame(kopf, bg=C["bg"])
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text="Artikel hinzufügen", bg=C["bg"], fg=C["text"],
                 font=F["h3"], anchor="w").pack(fill="x")
        tk.Label(txt, text="Erst Angebote finden, dann aufschreiben – Schreibweise egal", bg=C["bg"],
                 fg=C["subtext"], font=F["small"], anchor="w").pack(fill="x")

        # So funktioniert's – drei kurze Schritte, damit niemand raten muss
        info = ui.Card(win, pad=10, padx=14)
        info.pack(fill="x", padx=S(6))
        for i, (ic, fett, rest) in enumerate((
                ("⌨️", "Eintippen, was du brauchst: ",
                 "eine Sorte wie „Duschgel“ oder „Deo“ – oder eine Marke wie „Axe“."),
                ("🔍", "Angebote ansehen: ",
                 "Essens-Plan sucht bei deinen Händlern nach allen passenden Sorten und Marken."),
                ("✅", "Aufschreiben: ",
                 "Angebot anklicken → „Angebot übernehmen“ (mit Preis). Nichts dabei? "
                 "„Ohne Angebot aufschreiben“ setzt nur den Namen ohne Preis auf die Liste."))):
            z = tk.Frame(info.body, bg=C["surface"])
            z.pack(fill="x", pady=(0 if i == 0 else S(4), 0))
            ui.RoundIcon(z, ic, 28).pack(side="left", padx=(0, S(10)))
            t = tk.Text(z, height=1, bg=C["surface"], fg=C["subtext"], font=F["small"], bd=0,
                        highlightthickness=0, wrap="word", cursor="arrow", takefocus=0)
            t.tag_configure("b", foreground=C["text"], font=F["small_bold"])
            t.insert("end", fett, "b")
            t.insert("end", rest)
            t.config(state="disabled")
            t.pack(side="left", fill="x", expand=True)
            t.bind("<Configure>", lambda e, t=t: self._zeilen(t))

        zeile = tk.Frame(win, bg=C["bg"])
        zeile.pack(fill="x", padx=S(16), pady=(S(8), S(2)))
        self.q = tk.StringVar(value=text)
        self.entry = ttk.Entry(zeile, textvariable=self.q, font=F["base"])
        self.entry.pack(fill="x")
        self.q.trace_add("write", lambda *_: self._spaeter())
        ToolTip(self.entry, "Sorte oder Marke eintippen – die Liste sucht beim Tippen. Groß/klein, Umlaute "
                            "und kleine Tippfehler sind egal. Mehrere Wörter grenzen ein (z. B. "
                            "„duschgel axe“). Enter wählt das beste Angebot aus.", delay=600)
        tk.Label(win, text=BEISPIELE, bg=C["bg"], fg=C["subtext"], font=F["small"],
                 anchor="w").pack(fill="x", padx=S(16))

        unten = tk.Frame(win, bg=C["bg"])
        unten.pack(side="bottom", fill="x", padx=S(16), pady=(S(4), S(14)))
        self.status = ui.wrap_label(unten, "", bg=C["bg"], fg=C["subtext"], font=F["small_bold"])
        self.status.pack(side="left", fill="x", expand=True, padx=(0, S(10)))
        Btn(unten, "Schließen", self.schliessen, kind="light", padx=12,
            tip="Fenster schließen (Esc)").pack(side="right", padx=(S(8), 0))
        self.ohne_btn = Btn(unten, "Ohne Angebot aufschreiben", self.ohne_angebot, kind="sky", icon="✏️",
                            padx=12, tip="Den eingetippten Artikel ohne Preis auf die Einkaufsliste "
                                         "setzen – z. B. wenn dir kein Angebot zusagt")
        self.ohne_btn.pack(side="right", padx=(S(8), 0))
        Btn(unten, "Angebot übernehmen", self.hinzufuegen, kind="primary", icon="➕", padx=12,
            tip="Markiertes Angebot mit Preis auf die Einkaufsliste setzen (Enter oder Doppelklick)"
            ).pack(side="right")

        mitte = tk.Frame(win, bg=C["bg"])
        mitte.pack(fill="both", expand=True, padx=S(6))
        cols = [("haendler", "Händler", 150), ("produkt", "Produkt", 230), ("info", "Info", 210),
                ("preis", "Preis", 74), ("alt", "Vorher", 74), ("rabatt", "Rabatt", 66)]
        self.tv = app._tree(mitte, cols, flex=("produkt", "info"))
        ToolTip(self.tv, "Doppelklick oder „Angebot übernehmen“ setzt das Angebot auf die Einkaufsliste. "
                         "Rabatt „–“ = Prospektpreis ohne Vergleichspreis.", delay=600)
        self.frage_var = tk.BooleanVar(value=not fragen(app))
        self.frage_var.trace_add("write", lambda *_: self._frage_umgestellt())
        self.karte = _FrageKarte(self.tv._card, self.frage_var)
        self.tv.bind("<Double-1>", self._doppel)
        self.tv.bind("<Return>", lambda e: self.hinzufuegen())
        self.entry.bind("<Return>", self._enter)
        self.entry.bind("<Down>", self._runter)

        self._fuellen()
        win.deiconify()
        win.lift()
        win.focus_force()
        self.entry.focus_set()
        self.entry.icursor("end")

    @staticmethod
    def _zeilen(t):
        """Text-Widget so hoch machen, wie der umbrochene Text braucht (ohne Scrollbalken)."""
        try:
            n = t.count("1.0", "end", "displaylines")
            n = n[0] if isinstance(n, tuple) else n
            if n and int(t.cget("height")) != n:
                t.config(height=n)
        except tk.TclError:
            pass

    # ── Anzeige ───────────────────────────────────────────────────────────────
    def suche_setzen(self, text):
        """Von außen (Eingabefeld der Einkaufsliste): Suchbegriff übernehmen und Fenster nach vorn."""
        self.q.set(text)
        self.entry.icursor("end")
        self._fuellen()

    def _spaeter(self):
        if self._zu:
            return
        if self._after:
            self.win.after_cancel(self._after)
        self._after = self.win.after(SUCH_DELAY, self._fuellen)

    def _fuellen(self):
        if self._after:
            try:
                self.win.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = None
        if self._zu:
            return
        try:
            self._fuellen_roh()
        except tk.TclError:             # Fenster wird gerade geschlossen
            pass

    def _text(self):
        return " ".join(self.q.get().split())

    def _fuellen_roh(self):
        tv, text = self.tv, self._text()
        tv.delete(*tv.get_children())
        self.rows.clear()
        self._gemeint = None
        self.ohne_btn.set_enabled(bool(text))
        if text:
            such = sb.Suche(text)
            liste = treffer(self._daten, such)
            if not liste and self._daten:
                vor = sb.vorschlag(text, (d[1] for d in self._daten))
                if vor:
                    liste = treffer(self._daten, sb.Suche(vor))
                    if liste:
                        self._gemeint = vor
        else:
            liste = self._top
        for n, (rab, o, name, p, v, est) in enumerate(liste[:MAX_ZEILEN]):
            iid = str(n)
            tv.insert("", "end", iid=iid, tags=("odd",) if n % 2 else (), values=(
                o["haendler"], name, o.get("info", ""), _eur(p), pl.eur(v, est) if v else "",
                f"{'~' if est else ''}-{rab} %" if rab is not None else "–"))
            self.rows[iid] = (o, name, p, v, est)
        self._status(text, liste)

    def _status(self, text, liste):
        self.status.config(fg=C["subtext"])
        if liste:
            self.karte.verbergen()
            n = len(liste)
            mehr = f"Die {MAX_ZEILEN} besten von {n} – Suchbegriff eingrenzen. " if n > MAX_ZEILEN else ""
            if not text:
                self.status.config(text=mehr + f"Die besten Rabatte deiner Händler ({n}). "
                                               "Tippe oben einen Artikel, um gezielt zu suchen.")
            elif self._gemeint:
                self.status.config(text=f"Nichts zu „{text}“ – meintest du „{self._gemeint}“? "
                                        f"{n} Angebot{'e' if n != 1 else ''} dafür. Passt nichts: "
                                        "„Ohne Angebot aufschreiben“.")
            else:
                self.status.config(text=mehr + f"{n} Angebot{'e' if n != 1 else ''} für „{text}“ – "
                                              "anklicken und übernehmen. Passt nichts: "
                                              "„Ohne Angebot aufschreiben“.")
            return
        self.status.config(text="")
        app = self.app
        if not text:
            if not app.week.get("offers"):
                self.karte.zeigen(
                    "🔍", "Noch keine Angebote geladen",
                    "Zum Suchen braucht Essens-Plan die Prospekte dieser Woche. Lade sie mit "
                    "„Angebote laden (F5)“ – oder tippe oben einfach einen Artikel ein und schreib "
                    "ihn ohne Preis auf.",
                    [("Angebote laden (F5)", self._laden, "primary", "🔍")])
            elif not self._daten:
                self.karte.zeigen(
                    "🏪", "Deine Händler haben diese Woche keine Angebote", leer_text(app),
                    [("Händler ändern", self._haendler, "primary", "⚙️")])
            else:
                mn = app._min_rabatt()
                self.karte.zeigen(
                    "🏷️", "Tippe oben ein, was du brauchst",
                    "Bei deinen Händlern gibt es diese Woche keine Angebote mit erkennbarem Rabatt"
                    + (f" (Rabatt-Filter: ab {mn} %)" if mn is not None else "")
                    + ". Die Suche findet trotzdem alle Prospekt-Angebote, z. B. für „Duschgel“.")
            return
        if app.week.get("offers") and not self._daten:
            self.karte.zeigen(
                "🏪", "Deine Händler haben diese Woche keine Angebote",
                f"{leer_text(app)}\nSoll „{_gross(text)}“ ohne Preis auf die Einkaufsliste?",
                [("Ja, ohne Preis aufschreiben", self.ohne_angebot, "primary", "✏️"),
                 ("Händler ändern", self._haendler, "sky", "⚙️")],
                check=True)
            return
        grund = ("Es sind noch keine Angebote geladen." if not app.week.get("offers") else
                 f"Bei deinen Händlern ist diese Woche nichts zu „{text}“ im Angebot.")
        self.karte.zeigen(
            "🔎", "Kein Angebot gefunden",
            f"{grund}\nSoll „{_gross(text)}“ ohne Preis auf die Einkaufsliste?",
            [(f"Ja, ohne Preis aufschreiben", self.ohne_angebot, "primary", "✏️"),
             ("Nein, anders suchen", self._nein, "light", None)],
            check=True)

    def _laden(self):
        self.schliessen()
        self.app.scan()

    def _haendler(self):
        self.schliessen()
        self.app._zu_haendlern()

    def _frage_umgestellt(self):
        try:
            setze_fragen(self.app, not self.frage_var.get())
        except tk.TclError:
            pass

    # ── Aktionen ──────────────────────────────────────────────────────────────
    def _runter(self, _):
        kids = self.tv.get_children()
        if kids:
            self.tv.selection_set(kids[0])
            self.tv.focus(kids[0])
            self.tv.focus_set()
            return "break"

    def _enter(self, _=None):
        """Enter im Suchfeld: sofort suchen; mit Treffern das beste markieren (zweites Enter übernimmt),
        ohne Treffer ist die Frage schon sichtbar – Enter heißt dann „Ja, ohne Preis aufschreiben“."""
        if self._zu:
            return "break"
        if self._after:
            self._fuellen()
        if not self._text():
            self.status.config(text="Zuerst einen Artikel eintippen", fg=C["orange"])
        elif self.rows:
            self._runter(None)
            self.status.config(text="Bestes Angebot markiert – Enter übernimmt es. Lieber ohne Preis? "
                                    "„Ohne Angebot aufschreiben“.", fg=C["subtext"])
        else:
            self.ohne_angebot()
        return "break"

    def _doppel(self, e):
        if self.tv.identify_row(e.y):
            self.hinzufuegen()

    def hinzufuegen(self):
        if self._zu:
            return
        sel = self.tv.selection()
        if not sel or sel[0] not in self.rows:
            self.status.config(text="Zuerst ein Angebot in der Liste anklicken", fg=C["orange"])
            return
        o, name, p, v, est = self.rows[sel[0]]
        neu = self.app.extra_hinzufuegen("produkt", name, eintrag(o, name, p, v, est))
        self.status.config(text=f"✔ {name} ({o['haendler']}) steht auf der Einkaufsliste" if neu
                           else f"{name} steht schon auf der Liste",
                           fg=C["green"] if neu else C["orange"])

    def ohne_angebot(self):
        if self._zu:
            return
        text = _gross(self._text())
        if not text:
            self.status.config(text="Zuerst einen Artikel eintippen", fg=C["orange"])
            self.entry.focus_set()
            return
        neu = self.app.extra_hinzufuegen("produkt", text, None)
        self.status.config(text=f"✔ {text} steht ohne Preis auf der Einkaufsliste" if neu
                           else f"{text} steht schon auf der Liste",
                           fg=C["green"] if neu else C["orange"])
        if neu:
            self.q.set("")
            self._fuellen()
            self.status.config(text=f"✔ {text} steht ohne Preis auf der Einkaufsliste – "
                                    "nächsten Artikel eintippen oder schließen", fg=C["green"])
        self.entry.focus_set()

    def _nein(self):
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.status.config(text="Anders schreiben, eine Marke versuchen – oder Fenster schließen",
                           fg=C["subtext"])

    def schliessen(self):
        if self._zu:
            return
        self._zu = True
        try:
            if self._after:
                self.win.after_cancel(self._after)
            self.win.destroy()
        except tk.TclError:
            pass
        self._after = None
        if getattr(self.app, "_extra_suche", None) is self:
            self.app._extra_suche = None


class FrageDialog:
    """Rückfrage aus dem Eingabefeld der Einkaufsliste: kein Angebot – trotzdem aufschreiben?
    Ja (Enter) / Nein (Esc), dazu „Nicht mehr fragen“. ja() wird nach dem Schließen aufgerufen."""

    def __init__(self, app, text, grund, ja):
        self.app, self.ja, self._zu = app, ja, False
        win = self.win = _fenster(app, "Kein Angebot gefunden", 560, 290)
        win.protocol("WM_DELETE_WINDOW", self.schliessen)
        win.bind("<Escape>", lambda e: self.schliessen())
        win.bind("<Return>", lambda e: self._ja())
        body = tk.Frame(win, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=S(18), pady=(S(16), S(14)))
        kopf = tk.Frame(body, bg=C["bg"])
        kopf.pack(fill="x")
        ui.RoundIcon(kopf, "🔎", 40).pack(side="left", padx=(0, S(12)))
        tk.Label(kopf, text="Kein Angebot gefunden", bg=C["bg"], fg=C["text"],
                 font=F["h3"], anchor="w").pack(side="left")
        ui.wrap_label(body, f"{grund}\nSoll „{text}“ ohne Preis auf die Einkaufsliste?", bg=C["bg"],
                      fg=C["text"], font=F["base"]).pack(fill="x", pady=(S(12), S(8)))
        self.nicht_var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(body, text="Nicht mehr fragen – künftig direkt aufschreiben",
                             variable=self.nicht_var, style="Bg.TCheckbutton")
        cb.pack(anchor="w")
        ToolTip(cb, "Wieder einschalten: Einstellungen → „Ohne Angebot nachfragen“", delay=500)
        zeile = tk.Frame(body, bg=C["bg"])
        zeile.pack(side="bottom", fill="x")
        Btn(zeile, "Nein", self.schliessen, kind="light", padx=16,
            tip="Nichts aufschreiben (Esc)").pack(side="right", padx=(S(8), 0))
        Btn(zeile, "Ja, aufschreiben", self._ja, kind="primary", icon="✏️", padx=14,
            tip="Ohne Preis auf die Einkaufsliste setzen (Enter)").pack(side="right")
        win.deiconify()
        win.lift()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()

    def _ja(self):
        if self._zu:
            return
        if self.nicht_var.get():
            setze_fragen(self.app, False)
        self.schliessen()
        self.ja()

    def schliessen(self):
        if self._zu:
            return
        self._zu = True
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
        if getattr(self.app, "_frage_dialog", None) is self:
            self.app._frage_dialog = None


class NotizDialog:
    """Kleiner Dialog: eine Zeile Text für die Einkaufsliste (Enter = OK, Esc = Abbrechen)."""

    def __init__(self, app, ok):
        self.app, self.ok, self._zu = app, ok, False
        win = self.win = _fenster(app, "Notiz hinzufügen", 520, 230)
        win.protocol("WM_DELETE_WINDOW", self.schliessen)
        win.bind("<Escape>", lambda e: self.schliessen())
        body = tk.Frame(win, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=S(18), pady=(S(16), S(14)))
        kopf = tk.Frame(body, bg=C["bg"])
        kopf.pack(fill="x")
        ui.RoundIcon(kopf, "📝", 40).pack(side="left", padx=(0, S(12)))
        tk.Label(kopf, text="Notiz für die Einkaufsliste", bg=C["bg"], fg=C["text"],
                 font=F["h3"], anchor="w").pack(side="left")
        tk.Label(body, text="z. B. „Geschenk für Oma“ oder „Batterien nicht vergessen“", bg=C["bg"],
                 fg=C["subtext"], font=F["small"], anchor="w").pack(fill="x", pady=(S(10), S(4)))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(body, textvariable=self.var)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda e: self._ok())
        self.fehler = tk.Label(body, text="", bg=C["bg"], fg=C["orange"], font=F["small_bold"], anchor="w")
        self.fehler.pack(fill="x", pady=(S(4), 0))
        zeile = tk.Frame(body, bg=C["bg"])
        zeile.pack(side="bottom", fill="x")
        Btn(zeile, "Abbrechen", self.schliessen, kind="light", padx=12,
            tip="Nichts hinzufügen (Esc)").pack(side="right", padx=(S(8), 0))
        Btn(zeile, "OK", self._ok, kind="primary", padx=18,
            tip="Notiz auf die Liste setzen (Enter)").pack(side="right")
        win.deiconify()
        win.lift()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()
        self.entry.focus_set()

    def _ok(self):
        text = " ".join(self.var.get().split())
        if not text:
            self.fehler.config(text="Bitte erst etwas eintippen")
            return
        self.schliessen()
        self.ok(text)

    def schliessen(self):
        if self._zu:
            return
        self._zu = True
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
        if getattr(self.app, "_notiz_dialog", None) is self:
            self.app._notiz_dialog = None
