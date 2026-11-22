"""Essens-Plan – Angebote scannen, Wochenplan erstellen, PDF + Einkaufsliste."""
import os
import sys
import shutil
import threading
import tempfile
import webbrowser
import datetime as dt
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

import utils
from utils import (C, F, S, CONFIG, CONFIG_FILE, DATA_DIR, ICON_FILE, ToolTip, apply_theme,
                   save_json, mix, enable_dpi_awareness, init_scaling, init_fonts)
import ui
from ui import Card, Btn, RoundIcon, Tabs, FlatScrollbar, ScrollArea, Stat, Section
import offers as off
import planner as pl
import recipes as db
import dishes
import extras as ext
import suchbegriffe as sb
import update as up
import raussuchen

APP_NAME = "Essens-Plan"
APP_VERSION = "1.6.0"
TABS = ("Alle Angebote", "Angebot raussuchen", "Essensplan", "Einkaufsliste", "Gerichte", "Einstellungen")
T_ANGEBOTE, T_SUCHE, T_PLAN, T_LISTE, T_GERICHTE, T_EINST = range(len(TABS))
NB = " "   # geschütztes Leerzeichen: Angebots-Chips nicht mitten im Chip umbrechen
RIGHT = ("preis", "alt", "rabatt", "rel", "vorher", "spar")
GROUP_ICONS = {"Vorrat prüfen": "🧂", "Ohne Angebot": "🛍️", "Extras & Notizen": "✏️"}
# Größe der Oberfläche; 0 = so, wie Windows es vorgibt
GROESSEN = (("Automatisch (Windows)", 0.0), ("100 %", 1.0), ("125 %", 1.25), ("150 %", 1.5),
            ("175 %", 1.75), ("200 %", 2.0), ("250 %", 2.5), ("300 %", 3.0))


PLZ_HINT = "5 Ziffern, z. B. 10115 – danach werden die Prospekte deiner Region geladen"
TIP_DELAY = 600     # ms bis ein Hinweis erscheint (Standard der Hilfetexte in diesem Programm)


def tip(widget, text):
    """Hinweisblase mit einheitlicher Wartezeit; gibt das Widget zurück."""
    ToolTip(widget, text, delay=TIP_DELAY)
    return widget


def planwoche(heute=None):
    """(Jahr, KW) der Woche, die man gerade plant. Sonntags schon die kommende: Die Prospekte der
    laufenden Woche sind dann abgelaufen, die neuen aber schon da – sonst stünde fast überall
    „keine Angebote“."""
    d = heute or dt.date.today()
    if d.weekday() == 6:
        d += dt.timedelta(days=1)
    return d.isocalendar()[:2]


class LeerHinweis:
    """Wiederverwendbarer Leer-Zustand: eine Karte mit Icon, Überschrift, Erklärung und – wenn es einen
    sinnvollen nächsten Schritt gibt – einem Knopf. Sie legt sich über ein vorhandenes Widget (meist die
    leere Liste) und gibt es wieder frei, sobald es etwas zu zeigen gibt.

    Benutzung (siehe App._leer_hinweis):
        h = app._leer_hinweis(liste_card)          # einmal beim Aufbau des Tabs
        h.zeigen("🛒", "Titel", "Erklärung", "Knopf", befehl)   # Liste leer
        h.verbergen()                              # Liste hat Inhalt

    Gebaut wird nur einmal; zeigen() ändert Texte nur, wenn sich wirklich etwas geändert hat, und
    verbergen() ist bei bereits verstecktem Hinweis ein No-op – beides darf bei jedem Refresh laufen."""

    def __init__(self, parent, ueber):
        self.ueber, self._key, self._sichtbar = ueber, None, False
        self.card = Card(parent, pad=0)
        mitte = tk.Frame(self.card.body, bg=C["surface"])
        mitte.pack(expand=True)             # ohne fill: wird in der Karte zentriert
        self.icon = RoundIcon(mitte, "🛒", 64)
        self.icon.pack()
        self.titel = tk.Label(mitte, bg=C["surface"], fg=C["text"], font=F["big"], justify="center")
        self.titel.pack(pady=(S(14), S(6)))
        self.text = tk.Label(mitte, bg=C["surface"], fg=C["subtext"], font=F["base"],
                             justify="center", wraplength=S(480))
        self.text.pack()
        self.knopf = Btn(mitte, "", None, kind="primary", font=F["big"], padx=22, pady=10)
        self._knopf_da = False

    def zeigen(self, icon, titel, text, knopf=None, befehl=None, knopf_icon=None, kind="primary"):
        key = (icon, titel, text, knopf, knopf_icon, kind)
        if key != self._key:
            self._key = key
            self.icon.set(icon)
            self.titel.config(text=titel)
            self.text.config(text=text)
            if knopf:
                self.knopf.kind, self.knopf.icon = kind, knopf_icon
                self.knopf.set_text(knopf)
                if not self._knopf_da:
                    self.knopf.pack(pady=(S(18), 0))
                    self._knopf_da = True
            elif self._knopf_da:
                self.knopf.pack_forget()
                self._knopf_da = False
        self.knopf.command = befehl                 # der Befehl darf sich ändern, ohne neu zu zeichnen
        if not self._sichtbar:
            self._sichtbar = True
            self.card.place(in_=self.ueber, x=0, y=0, relwidth=1, relheight=1)
            self.card.lift()

    def verbergen(self):
        if self._sichtbar:
            self._sichtbar = False
            self.card.place_forget()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_scaling(self)
        init_fonts(self)
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.configure(bg=C["bg"])
        apply_theme(self)
        self._place_window()
        self._set_icon()

        self.cfg = CONFIG
        if not self.cfg.get("update_repo"):          # leer = offizielles Projekt
            self.cfg["update_repo"] = utils.DEFAULT_CONFIG["update_repo"]
        self.store = db.Store()
        self.recipes = self.store.all()
        self.year, self.kw = planwoche()
        self.week = {}
        self.items = []
        self._save_pending = None   # (Jahr, KW, Woche), die noch gespeichert werden muss (siehe _save_later)
        self._save_id = None
        self._auto_id = None        # Timer fürs automatische Speichern der Einstellungen
        self._auto_aus = False      # unterdrückt Autosave, während gespeichert wird
        self._extra_suche = None    # offene Fenster „Artikel hinzufügen“ / „Notiz“ / Rückfrage
        self._notiz_dialog = None
        self._frage_dialog = None
        self.food = []      # Lebensmittel-Angebote mit Rezept-Suchbegriffen (planner.index_offers)
        self._busy = False
        self._up_busy = False
        self._fehler_offen = False
        self._fehler_zahl = 0
        self._schluss = False       # ab destroy(): nichts mehr anfassen, nichts mehr melden
        self._erst_scan = False     # Scan kommt aus der Ersteinrichtung → danach Hinweis auf den Plan
        self.h_vars, self.h_btns = {}, {}   # Händler-Häkchen: Beschriftung → BooleanVar / Checkbutton

        self._build_menu()
        self._build_header()
        self._build_statusbar()
        self._build_toolbar()
        self.tabs = Tabs(self)
        self.tabs.pack(fill="both", expand=True)
        self._build_offers_tab(self.tabs.add(TABS[T_ANGEBOTE], "🛒"))
        self.such_tab = raussuchen.RaussuchenTab(self, self.tabs.add(TABS[T_SUCHE], "🔎"),
                                                 lambda: self.tabs.select(T_LISTE))
        self._build_plan_tab(self.tabs.add(TABS[T_PLAN], "🍽️"))
        self._build_list_tab(self.tabs.add(TABS[T_LISTE], "📝"))
        self.dish_tab = dishes.DishTab(self, self.tabs.add(TABS[T_GERICHTE], "📖"))
        self._build_settings_tab(self.tabs.add(TABS[T_EINST], "⚙️"))
        self.tabs.on_change = self._tab_gewechselt
        ui.install_wheel(self)
        self._groesse = None
        self._niedrig = False
        self.bind("<Configure>", self._groesse_geaendert, add="+")
        self._load_week()
        if dt.date.today().weekday() == 6:
            self.set_status("Sonntag: Du siehst schon die neue Woche mit den neuen Prospekten. "
                            "Zurück zur laufenden Woche mit ◀.")
        if not self.cfg.get("plz"):         # erster Start: gleich zu den Einstellungen
            self.tabs.select(T_EINST)
            self.after_idle(self.plz_entry.focus_set)
        if self.cfg.get("update_auto", True) and up.repo_name(self.cfg.get("update_repo", "")):
            self.after(4000, lambda: self.check_update(still=True))   # leise, erst nach dem Start

    def report_callback_exception(self, exc, val, tb):
        """Unerwartete Fehler nicht verschlucken. Die EXE hat keine Konsole – ohne das hier würde
        ein Klick einfach nichts tun. Also: ins Protokoll schreiben und (höchstens dreimal,
        nie zwei Fenster zugleich) kurz melden."""
        if self._schluss and issubclass(exc, tk.TclError):
            return                                  # später Aufruf traf ein schon zerstörtes Fenster
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            sys.stderr.write(text)
        except Exception:
            pass                                    # in der EXE gibt es kein stderr
        log = os.path.join(DATA_DIR, "fehler.log")
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            neu = not os.path.exists(log) or os.path.getsize(log) > 200_000   # nicht endlos wachsen
            with open(log, "w" if neu else "a", encoding="utf-8") as f:
                f.write(f"── {dt.datetime.now():%d.%m.%Y %H:%M:%S} · v{APP_VERSION} ──\n{text}\n")
        except OSError:
            pass
        self._fehler_zahl += 1
        if self._fehler_offen or self._fehler_zahl > 3 or self._schluss:
            return
        self._fehler_offen = True
        try:
            messagebox.showerror(
                "Unerwarteter Fehler",
                f"Das hat nicht geklappt:\n\n{exc.__name__}: {val}\n\n"
                f"Einzelheiten stehen in\n{log}", parent=self)
        except tk.TclError:
            pass                                    # Fenster schon zu
        finally:
            self._fehler_offen = False

    def _groesse_geaendert(self, e):
        """Neue Fenstergröße: das Layout aller verschachtelten Ebenen in einem Durchgang rechnen.
        Sonst reicht Tk die Größe Ebene für Ebene weiter und zeichnet dazwischen jedes Mal alles
        darunter neu – die Angebots-Tabelle z. B. siebenmal je Schritt statt einmal."""
        if e.widget is not self or (e.width, e.height) == self._groesse or self._schluss:
            return
        self._groesse = (e.width, e.height)
        self._band_anpassen(e.height)
        self.update_idletasks()

    def _band_anpassen(self, hoehe):
        """Niedriges Fenster (Laptop mit 1366×768, Full HD mit 150 %): das Band mit dem Namen oben weglassen –
        die Listen brauchen die Höhe dringender. „Hell/Dunkel“ steht dann als Knopf neben „PDF drucken“."""
        niedrig = hoehe < S(760)
        if niedrig == self._niedrig:
            return
        self._niedrig = niedrig
        if niedrig:
            self.hdr.pack_forget()
            self._fade.pack_forget()
        else:
            self.hdr.pack(fill="x", before=self.toolbar)
            self._fade.pack(fill="x", before=self.toolbar)
        self._tb_breiten = self._tb_wrap = None     # Hell/Dunkel-Knopf dazu/weg: Leiste neu messen
        self._layout_toolbar()

    def destroy(self):
        """Fenster schließen. tkinter baut dabei jedes Kind einzeln ab. Läuft gerade ein
        Windows-Dialog (Speichern unter, Meldung), arbeitet Tk zwischen zwei Kindern alle
        wartenden Ereignisse ab – eine Karte bekäme dann noch ein <Configure>, obwohl ihre
        Zeichenfläche schon weg ist. Darum jeden Ast in einem Zug abräumen: einem Fenster,
        das Tk selbst gerade zerstört, stellt es nichts mehr zu."""
        self._schluss = True
        such = getattr(self, "such_tab", None)
        if such is not None:
            such.schliessen()               # wartende Suche abbrechen
        for fenster in (self._extra_suche, self._notiz_dialog):     # eigene Fenster zuerst sauber schließen
            if fenster is not None:
                try:
                    fenster.schliessen()
                except Exception:
                    pass
        try:
            if self._auto_id is not None:       # Einstellung noch nicht gespeichert (Timer läuft)
                self._auto_flush()
        except Exception:
            pass
        try:
            self._save_flush()
        except Exception:
            pass
        for kind in list(self.children.values()):
            try:
                self.tk.call("destroy", kind._w)
            except tk.TclError:
                pass
        super().destroy()

    def _place_window(self):
        """Das Fenster öffnet immer maximiert. Die Normalgröße (relativ zur skalierten Bildschirmgröße,
        passt bei 100 % bis 200 %) gilt, sobald der Nutzer es wieder verkleinert."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(S(1440), sw - S(40)), min(S(920), sh - S(100))
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - S(20))}")
        self.minsize(min(S(980), w), min(S(600), h))
        try:
            self.state("zoomed")
        except tk.TclError:
            pass                    # nicht unter Windows: bleibt bei der Normalgröße

    def _set_icon(self):
        """Fenster- und Taskleistensymbol. Die eigene App-ID sorgt dafür, dass Windows in der
        Taskleiste unser Symbol zeigt und nicht das von Python."""
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MarviSoft.EssensPlan")
            except Exception:
                pass
        if os.path.exists(ICON_FILE):
            try:
                self.iconbitmap(default=ICON_FILE)
                return
            except tk.TclError:
                pass
        logo = ui.emoji_img("🍽️", S(64), C["accent"])
        if logo:
            self.iconphoto(True, logo)

    # ── Menü ──────────────────────────────────────────────────────────────────
    def _build_menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="PDF exportieren…", accelerator="Strg+P", command=self.export_pdf)
        f.add_command(label="Einkaufsliste kopieren", command=self.copy_list)
        f.add_separator()
        f.add_command(label="Gerichte verwalten", accelerator=f"Strg+{T_GERICHTE + 1}",
                      command=lambda: self.tabs.select(T_GERICHTE))
        f.add_command(label="Rezepte importieren…", command=lambda: self.dish_tab.do_import())
        f.add_command(label="Rezepte sichern…", command=lambda: self.dish_tab.do_export())
        f.add_command(label="Rezepte neu laden", command=self.reload_recipes)
        f.add_command(label="Datenordner öffnen", command=self.open_data_dir)
        f.add_separator()
        f.add_command(label="Beenden", command=self.destroy)
        m.add_cascade(label="Datei", menu=f)

        a = tk.Menu(m, tearoff=0)
        a.add_command(label="Angebote scannen", accelerator="F5", command=self.scan)
        a.add_command(label="Angebot raussuchen", accelerator=f"Strg+{T_SUCHE + 1}",
                      command=lambda: self.tabs.select(T_SUCHE))
        m.add_cascade(label="Angebote", menu=a)

        p = tk.Menu(m, tearoff=0)
        p.add_command(label="Woche generieren", accelerator="F6", command=self.generate)
        p.add_separator()
        p.add_command(label="Vorherige Woche", accelerator="Strg+←", command=lambda: self.shift_week(-1))
        p.add_command(label="Nächste Woche", accelerator="Strg+→", command=lambda: self.shift_week(1))
        p.add_command(label="Aktuelle Woche", command=self.today_week)
        m.add_cascade(label="Plan", menu=p)

        v = tk.Menu(m, tearoff=0)
        for i, name in enumerate(TABS):
            v.add_command(label=name, accelerator=f"Strg+{i + 1}", command=lambda i=i: self.tabs.select(i))
            self.bind(f"<Control-Key-{i + 1}>", lambda e, i=i: self.tabs.select(i))
        v.add_separator()
        v.add_command(label="Hell / Dunkel umschalten", command=self.toggle_theme)
        m.add_cascade(label="Ansicht", menu=v)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Kurzanleitung", command=self.show_help)
        h.add_command(label="Tastenkürzel", command=self.show_keys)
        h.add_separator()
        h.add_command(label="Nach Updates suchen…", command=self.check_update)
        h.add_separator()
        h.add_command(label="Über", command=self.show_about)
        m.add_cascade(label="Hilfe", menu=h)
        self.config(menu=m)

        self.bind("<F5>", lambda e: self.scan())
        self.bind("<F6>", lambda e: self.generate())
        self.bind("<Control-p>", lambda e: self.export_pdf())
        self.bind("<Control-Left>", lambda e: self.shift_week(-1))
        self.bind("<Control-Right>", lambda e: self.shift_week(1))

    # ── Kopfbereich ───────────────────────────────────────────────────────────
    def _build_header(self):
        self._f_h1 = tkfont.Font(font=F["h1"])
        self._f_sub = tkfont.Font(font=F["small_bold"])
        self._f_btn = tkfont.Font(font=F["btn"])
        self.hdr = tk.Canvas(self, height=S(68), bg=C["header"], highlightthickness=0, bd=0)
        self.hdr.pack(fill="x")
        self.hdr.bind("<Configure>", lambda e: self._draw_header())
        self._tgl_tip = ToolTip(self.hdr, "", delay=TIP_DELAY)
        self._tgl_tip.widget.unbind("<Enter>")      # nur über dem Knopf (Tag „tgl“), nicht im ganzen Kopf
        fade = self._fade = tk.Canvas(self, height=S(8), bg=C["bg"], highlightthickness=0, bd=0)
        fade.pack(fill="x")
        fade.bind("<Configure>", lambda e: self._draw_fade(fade))

    def _draw_header(self):
        cv = self.hdr
        w, h = cv.winfo_width(), cv.winfo_height()
        if (w, h) == getattr(cv, "_gezeichnet", None):
            return
        cv._gezeichnet = (w, h)
        cv.delete("all")
        steps = 64
        for i in range(steps):   # Farbverlauf
            cv.create_rectangle(w * i / steps, 0, w * (i + 1) / steps + 1, h, width=0,
                                fill=mix(C["header"], C["header2"], i / (steps - 1)))
        for cx, cy, r in ((w * 0.58, -S(64), S(110)), (w - S(260), -S(34), S(88)), (w - S(70), h + S(26), S(76))):
            base = mix(C["header"], C["header2"], max(0.0, min(1.0, cx / max(1, w))))
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=mix(base, "#ffffff", 0.2), width=S(2))

        x, isz = S(18), S(46)
        img = ui.emoji_img("🍽️", isz, "#ffffff")
        if img:
            cv.create_image(x + isz / 2, h / 2, image=img)
        x += isz + S(13)
        lt, ls = self._f_h1.metrics("linespace"), self._f_sub.metrics("linespace")
        top = (h - lt - ls + S(6)) / 2
        cv.create_text(x, top, text=APP_NAME, anchor="nw", font=self._f_h1, fill=C["header_text"])
        cv.create_text(x + S(2), top + lt - S(6), anchor="nw", font=self._f_sub, fill=C["header_sub"],
                       text=f"Angebote  →  Wochenplan  →  Einkaufsliste   ·   v{APP_VERSION}")

        dark = utils.ACTIVE_THEME == "dark"
        icon, label = ("☀️", "Hell") if dark else ("🌙", "Dunkel")
        isz = S(26)
        bw, bh = S(10) + isz + S(8) + self._f_btn.measure(label) + S(14), S(40)
        x1, y0 = w - S(20), (h - bh) / 2
        x0, y1 = x1 - bw, y0 + bh
        base = C["header2"]
        ui.draw_shadow(cv, x0, y0, x1, y1, base, blur=S(6), dy=S(2), strength=0.3)
        normal, hover = mix(base, "#ffffff", 0.16), mix(base, "#ffffff", 0.3)
        cv.create_rectangle(x0, y0, x1, y1, fill=normal, outline=mix(base, "#ffffff", 0.5),
                            tags=("tgl", "tglbox"))
        img = ui.emoji_img(icon, isz, "#ffffff")
        if img:
            cv.create_image(x0 + S(10) + isz / 2, h / 2, image=img, tags="tgl")
        cv.create_text(x0 + S(18) + isz, h / 2, text=label, anchor="w", font=self._f_btn,
                       fill="#ffffff", tags="tgl")
        tt = self._tgl_tip
        tt._cancel()
        tt.text = (("Zum hellen Design wechseln" if dark else "Zum dunklen Design wechseln")
                   + "\n(das Programm startet dafür kurz neu)")
        cv.tag_bind("tgl", "<Enter>", lambda e: (cv.itemconfigure("tglbox", fill=hover),
                                                 cv.configure(cursor="hand2"), tt._schedule()))
        cv.tag_bind("tgl", "<Leave>", lambda e: (cv.itemconfigure("tglbox", fill=normal),
                                                 cv.configure(cursor=""), tt._cancel()))
        cv.tag_bind("tgl", "<ButtonRelease-1>", lambda e: self.toggle_theme())

    def _draw_fade(self, cv):
        n, w = cv.winfo_height(), cv.winfo_width()
        if (w, n) == getattr(cv, "_gezeichnet", None):
            return
        cv._gezeichnet = (w, n)
        cv.delete("all")
        for i in range(n):
            a = (0.45 if utils.ACTIVE_THEME == "dark" else 0.16) * (1 - i / n) ** 2
            cv.create_line(0, i, w, i, fill=mix(C["bg"], C["shadow"], a))

    def _build_toolbar(self):
        tb = self.toolbar = tk.Frame(self, bg=C["bg"])
        tb.pack(fill="x", padx=S(8))
        nav = Card(tb, pad=7, padx=10)
        b = nav.body
        Btn(b, "◀", lambda: self.shift_week(-1), kind="light", padx=12,
            tip="Vorherige Woche (Strg+←)").pack(side="left")
        self.kal_icon = RoundIcon(b, "📅", 36)
        self.kal_icon.pack(side="left", padx=(S(12), S(8)))
        self._wk_font = {}                  # Schrift der Woche: normal und in schmaler Leiste
        for name in ("big", "h3"):
            fb = tkfont.Font(font=F[name])
            self._wk_font[name] = (F[name], -(-fb.measure("KW 88  ·  88.88. – 88.88.8888")
                                               // max(1, fb.measure("0"))))
        self.week_lbl = tk.Label(b, text="", bg=C["surface"], fg=C["text"], font=F["big"],
                                 anchor="w", width=self._wk_font["big"][1])
        self.week_lbl.pack(side="left", padx=(0, S(8)))
        Btn(b, "▶", lambda: self.shift_week(1), kind="light", padx=12,
            tip="Nächste Woche (Strg+→)").pack(side="left")
        Btn(b, "Heute", self.today_week, kind="light", icon="📍",
            tip="Zur aktuellen Woche springen –\nsonntags schon zur neuen Woche, deren Prospekte dann da sind"
            ).pack(side="left", padx=(S(6), 0))

        acts = Card(tb, pad=7, padx=10)
        b = acts.body
        Btn(b, "Speichern", self.save_all, kind="green", icon="💾",
            tip="Einstellungen und Wochenplan sofort speichern\n(Änderungen werden ohnehin automatisch gespeichert)"
            ).pack(side="left", padx=(0, S(6)))
        self.btn_scan = Btn(b, "Angebote scannen", self.scan, kind="sky", icon="🔍",
                            tip="Alle Prospekte dieser Woche laden (F5)")
        self.btn_scan.pack(side="left")
        Btn(b, "Plan generieren", self.generate, kind="primary", icon="✨",
            tip="Wochenplan aus den Angeboten erstellen (F6)").pack(side="left", padx=S(6))
        Btn(b, "PDF drucken", self.export_pdf, kind="navy", icon="🖨️",
            tip="Wochenplan und Einkaufsliste als PDF (Strg+P)").pack(side="left")
        # nur in niedrigen Fenstern sichtbar – dann fehlt das Band oben mit seinem Hell/Dunkel-Knopf
        dark = utils.ACTIVE_THEME == "dark"
        self._theme_text = "Hell" if dark else "Dunkel"
        self.btn_theme = Btn(b, self._theme_text, self.toggle_theme, kind="light",
                             icon="☀️" if dark else "🌙",
                             tip=("Zum hellen Design wechseln" if dark else "Zum dunklen Design wechseln")
                                 + "\n(das Programm startet dafür kurz neu)")
        self._tb_cards, self._tb_wrap = (nav, acts), None
        self._tb_breiten, self._tb_eng, self._tb_messen = None, False, False
        tb.columnconfigure(1, weight=1)
        tb.bind("<Configure>", lambda e: self._layout_toolbar())
        self._layout_toolbar()

    def _tb_stufe(self, stufe):
        """Leiste schmaler machen: 0 = alles, 1 = Hell/Dunkel nur als Symbol, 2 = ohne Kalender-Symbol und
        ohne Hell/Dunkel-Knopf (steht auch im Menü „Ansicht“), die Woche etwas kleiner geschrieben.
        Den Hell/Dunkel-Knopf gibt es nur in niedrigen Fenstern – sonst ist er oben im Band."""
        bt = self.btn_theme
        if getattr(self, "_niedrig", False) and stufe < 2:
            if not bt.winfo_manager():
                bt.pack(side="left", padx=(S(6), 0))
            text = self._theme_text if stufe == 0 else ""
            if bt.text != text:
                bt.set_text(text)
        else:
            bt.pack_forget()
        eng = stufe == 2
        if eng != self._tb_eng:
            self._tb_eng = eng
            if eng:
                self.kal_icon.pack_forget()
            else:
                self.kal_icon.pack(side="left", padx=(S(12), S(8)), before=self.week_lbl)
            font, chars = self._wk_font["h3" if eng else "big"]
            self.week_lbl.config(font=font, width=chars)

    def _layout_toolbar(self):
        """Passt die Leiste nicht in eine Zeile, wird sie erst schmaler (siehe _tb_stufe). Reicht das
        nicht, rutschen die Knöpfe rechts in eine zweite Zeile."""
        if self._tb_messen:
            return
        nav, acts = self._tb_cards
        w = self.toolbar.winfo_width()
        wrap = False
        if w > 1:
            if self._tb_breiten is None:    # Breite jeder Stufe einmal messen
                self._tb_messen, breiten = True, []
                try:
                    for stufe in (0, 1, 2):
                        self._tb_stufe(stufe)
                        self.update_idletasks()
                        breiten.append(nav.winfo_reqwidth() + acts.winfo_reqwidth())
                finally:
                    self._tb_messen = False
                self._tb_breiten = breiten
            stufe = next((i for i, b in enumerate(self._tb_breiten) if b <= w), 2)
            self._tb_stufe(stufe)
            wrap = self._tb_breiten[stufe] > w
        if wrap == self._tb_wrap:
            return
        self._tb_wrap = wrap
        nav.grid(row=0, column=0, sticky="w")
        acts.grid(row=1 if wrap else 0, column=0 if wrap else 2, sticky="w" if wrap else "e")

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=C["surface"])
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg=C["border"], height=max(1, S(1))).pack(fill="x")
        row = tk.Frame(bar, bg=C["surface"], padx=S(16), pady=S(5))
        row.pack(fill="x")
        d = S(10)
        self.dot = tk.Canvas(row, width=d, height=d, bg=C["surface"], highlightthickness=0, bd=0)
        self.dot.create_oval(0, 0, d - 1, d - 1, fill=C["green"], outline="", tags="dot")
        self.dot.pack(side="left", padx=(0, S(8)))
        tk.Label(row, text=f"v{APP_VERSION}  ·  Angebotsdaten: marktguru.de", bg=C["surface"],
                 fg=C["subtext"], font=F["small"]).pack(side="right")
        self.status = tk.Label(row, text="Bereit", anchor="w", bg=C["surface"], fg=C["text"],
                               font=F["small_bold"])
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(row, length=S(200), mode="determinate")
        self.scan_lbl = tk.Label(row, text="", bg=C["surface"], fg=C["accent"], font=F["small_bold"])

    def set_status(self, txt):
        self.status.config(text=txt)

    def _leer_hinweis(self, ueber):
        """Leer-Zustand für einen Tab anlegen (siehe LeerHinweis). `ueber` ist das Widget, das bei
        leerem Inhalt verdeckt werden soll, z. B. die Karte mit der Liste; es muss im selben Container
        liegen wie der Hinweis. Rückgabe: Objekt mit zeigen(icon, titel, text, knopf, befehl) und
        verbergen() – beides darf bei jedem Auffrischen aufgerufen werden."""
        return LeerHinweis(ueber.master, ueber)

    def _zu_einstellungen(self, hinweis=None, feld=None):
        """In den Einstellungen-Tab wechseln (Fokus auf `feld`, sonst die PLZ) und optional einen
        Hinweis in die Statuszeile schreiben – statt einer Fehlermeldung."""
        self.tabs.select(T_EINST)
        (feld or self.plz_entry).focus_set()
        if hinweis:
            self.set_status(hinweis)

    def _zu_haendlern(self):
        """Einstellungen öffnen, Fokus auf die Händler-Häkchen (erstes angehaktes)."""
        feld = (next((b for l, b in self.h_btns.items() if self.h_vars[l].get()), None)
                or next(iter(self.h_btns.values()), None))
        self._zu_einstellungen("Weitere Händler anhaken (oder alle Haken weg = alle Händler)", feld)

    # ── Hilfsfunktionen für Layouts ───────────────────────────────────────────
    def _reflow(self, frame, widgets, minw, gap=16):
        """Widgets in so vielen Spalten anordnen, wie bei minw Mindestbreite hineinpassen."""
        state = {"cols": 0}

        def do(_=None):
            w = frame.winfo_width()
            cols = max(1, min(len(widgets), w // S(minw))) if w > 1 else len(widgets)
            if cols == state["cols"]:
                return
            state["cols"] = cols
            for c in range(len(widgets)):
                frame.columnconfigure(c, weight=1 if c < cols else 0, uniform="rf" if c < cols else "")
            for i, wd in enumerate(widgets):
                wd.grid(row=i // cols, column=i % cols, sticky="ew",
                        padx=(0 if i % cols == 0 else S(gap), 0), pady=(0 if i < cols else S(10), 0))
        frame.bind("<Configure>", do, add="+")
        do()

    def _field_label(self, parent, text):
        return tk.Label(parent, text=text.upper(), bg=C["surface"], fg=C["subtext"],
                        font=F["small_bold"], anchor="w")

    # ── Tab: Angebote ─────────────────────────────────────────────────────────
    def _build_offers_tab(self, page):
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=S(8), pady=(0, S(4)))
        card = Card(wrap, pad=12, padx=16)
        card.pack(fill="x")
        top = card.body
        self.q_var = tk.StringVar()
        self._q_after = None
        self.q_var.trace_add("write", lambda *_: self._fill_offers_later())
        self._field_label(top, "Suche").grid(row=0, column=0, sticky="w")
        q_entry = ttk.Entry(top, textvariable=self.q_var, width=1)
        q_entry.grid(row=1, column=0, sticky="ew", padx=(0, S(12)))
        tip(q_entry, "Sorte oder Marke eintippen – z. B. „Duschgel“, „Deo“, „Axe“ oder „Joghurt“.\n"
                     "Findet alle passenden Sorten und Marken; Groß/klein, Umlaute und kleine Tippfehler\n"
                     "sind egal. Mit Suchbegriff wird in allen Branchen gesucht (auch Drogerie).")

        def combo(col, label, var, hilfe):
            self._field_label(top, label).grid(row=0, column=col, sticky="w")
            cb = ttk.Combobox(top, textvariable=var, state="readonly", width=1)
            cb.grid(row=1, column=col, sticky="ew", padx=(0, S(12) if col < 3 else 0))
            cb.bind("<<ComboboxSelected>>", lambda e: self._fill_offers())
            return tip(cb, hilfe)
        self.h_var = tk.StringVar(value="Alle Händler")
        self.h_cb = combo(1, "Händler", self.h_var, "Nur Angebote eines Händlers zeigen.\n"
                      "Welche Händler der Plan nutzt, stellst du unter Einstellungen ein.")
        self.b_var = tk.StringVar(value="Lebensmittel")
        self.b_cb = combo(2, "Branche", self.b_var, "„Lebensmittel“ blendet Drogerie, Elektro u. a. aus.\n"
                      "„Alle Branchen“ zeigt alles, was gescannt wurde.")
        self.k_var = tk.StringVar(value="Alle Kategorien")
        self.k_cb = combo(3, "Kategorie", self.k_var, "Nur eine Warengruppe zeigen, z. B. Milchprodukte oder Obst.")
        for col, weight in ((0, 5), (1, 4), (2, 3), (3, 4)):
            top.columnconfigure(col, weight=weight)

        row2 = tk.Frame(top, bg=C["surface"])
        row2.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(S(10), 0))
        RoundIcon(row2, "🛒", 26).pack(side="left", padx=(0, S(8)))
        self.off_count = tk.Label(row2, text="", bg=C["surface"], fg=C["text"], font=F["bold"])
        self.off_count.pack(side="left")
        tip(self.off_count, "Preis = was du zahlst (mit deinen Treue-Programmen)\n"
                            "Vorher = Normalpreis laut Prospekt/App, ~ = geschätzt aus Ø-Grundpreis\n"
                            "vs. Ø Kat. = Grundpreis im Vergleich zum Durchschnitt der Kategorie")
        self._link_font = tkfont.Font(font=F["small_bold"], underline=True)
        self.off_reset = tk.Label(row2, text="Alle zeigen", bg=C["surface"], fg=C["accent"],
                                  font=self._link_font, cursor="hand2")
        self.off_reset.bind("<Button-1>", lambda e: self._reset_offer_filters())
        self.off_reset.bind("<Enter>", lambda e: self.off_reset.config(fg=C["text"]))
        self.off_reset.bind("<Leave>", lambda e: self.off_reset.config(fg=C["accent"]))
        tip(self.off_reset, "Branche, Händler, Kategorie, Suche und Häkchen zurücksetzen")
        self._reset_shown = False
        self.rezept_var = tk.BooleanVar(value=False)
        self.rabatt_var = tk.BooleanVar(value=False)
        self.treue_var = tk.BooleanVar(value=False)
        for text, var, hilfe in (
                ("Nur Treue-Aktionen", self.treue_var,
                 "Nur Preise, die durch eines deiner Treue-Programme (Einstellungen) gelten"),
                ("Nur reduziert", self.rabatt_var,
                 "Nur Angebote mit bekanntem Vorher-Preis – geschätzte (~) Rabatte zählen nicht"),
                ("Nur Rezept-Zutaten", self.rezept_var,
                 "Nur Angebote, die zu Zutaten deiner Gerichte passen (Tab „Gerichte“)")):
            cb = ttk.Checkbutton(row2, text=text, variable=var, command=self._fill_offers)
            cb.pack(side="right", padx=(S(18), 0))
            tip(cb, hilfe)

        cols = [("haendler", "Händler", 120), ("produkt", "Produkt", 190), ("info", "Info", 220),
                ("kategorie", "Kategorie", 110), ("preis", "Preis", 70), ("alt", "Vorher", 70),
                ("rabatt", "Rabatt", 62), ("rel", "vs. Ø Kat.", 76), ("treue", "Treue-Aktion", 150),
                ("grundpreis", "Grundpreis", 95), ("gueltig", "Gültig", 90)]
        self.off_tree = self._tree(wrap, cols, flex=("produkt", "info"))
        tip(self.off_tree, "Spaltenköpfe anklicken = sortieren (nochmal = umgekehrt).\n"
                           "Preis = was du zahlst (mit deinen Treue-Programmen)\n"
                           "Vorher = Normalpreis laut Prospekt/App, ~ = geschätzt aus Ø-Grundpreis\n"
                           "vs. Ø Kat. = Grundpreis im Vergleich zum Durchschnitt der Kategorie")
        self.off_hinweis = self._leer_hinweis(self.off_tree._card)

    def _tree(self, parent, cols, show="headings", flex=()):
        """flex = Textspalten, die sich der Fensterbreite anpassen – die übrigen behalten ihre Breite,
        damit bei jeder Windows-Skalierung alle Spalten sichtbar bleiben."""
        card = Card(parent, pad=0)
        card.pack(fill="both", expand=True)
        body = card.body
        tv = ttk.Treeview(body, columns=[c[0] for c in cols], show=show)
        tv._titles, tv._sorted, tv._widths, tv._card = {}, None, {}, card
        for key, title, w in cols:
            tv._titles[key], tv._widths[key] = title, S(w)
            anchor = "e" if key in RIGHT else "w"
            tv.heading(key, text=title, anchor=anchor, command=lambda k=key, t=tv: self._sort(t, k))
            tv.column(key, width=S(w), minwidth=S(40), anchor=anchor, stretch=key in flex)

        def fit(e=None):
            # nur die sichtbaren Spalten zählen (displaycolumns kann einzelne ausblenden)
            shown = tv["displaycolumns"]
            shown = set(tv["columns"]) if not shown or shown[0] == "#all" else set(shown)
            width = e.width if e is not None else tv.winfo_width()
            room = width - 4 - sum(w for k, w in tv._widths.items() if k not in flex and k in shown)
            share = sum(tv._widths[k] for k in flex)
            for k in flex:
                tv.column(k, width=max(S(60), room * tv._widths[k] // share))
        tv._fit = fit if flex else (lambda e=None: None)
        if flex:
            tv.bind("<Configure>", fit, add="+")
        sb = FlatScrollbar(body, tv.yview, bg=C["surface"])
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=S(2), pady=S(2))
        tv.pack(side="left", fill="both", expand=True)
        tv.tag_configure("odd", background=C["row_stripe"])
        tv.tag_configure("grp", background=C["surface2"], foreground=C["accent"], font=F["bold"])
        ui.tree_hover(tv)
        return tv

    def _sort(self, tv, key):
        rev = tv._sorted == (key, False)
        tv._sorted = (key, rev)
        rows = [(tv.set(i, key), i) for i in tv.get_children("")]

        def k(x):
            try:
                return float(x[0].replace(" €", "").replace(" %", "").replace("~", "").replace(",", "."))
            except ValueError:
                return x[0].lower()
        try:
            rows.sort(key=k, reverse=rev)
        except TypeError:
            rows.sort(key=lambda x: x[0].lower(), reverse=rev)
        # Ein Aufruf für alle Zeilen statt einer pro Zeile – bei 1500 Angeboten spürbar.
        if rows:
            tv.set_children("", *(i for _, i in rows))
        for n, (_, i) in enumerate(rows):
            tags = tv.item(i, "tags")
            if "grp" not in tags:
                neu = ("odd",) if n % 2 else ()
                if tuple(tags or ()) != neu:
                    tv.item(i, tags=neu)
        self._sort_marks(tv)

    def _sort_marks(self, tv):
        for k, t in tv._titles.items():
            mark = (" ▼" if tv._sorted[1] else " ▲") if tv._sorted and tv._sorted[0] == k else ""
            tv.heading(k, text=t + mark)

    def _fill_offers_later(self):
        if self._q_after:
            self.after_cancel(self._q_after)
        self._q_after = self.after(250, self._fill_offers)

    def _offer_filters(self):
        """Händler/Kategorie-Auswahl passend zur gewählten Branche befüllen."""
        offers = self.week.get("offers", [])
        branchen = sorted({b for o in offers for b in o.get("branche", "").split(", ") if b})
        self.b_cb.config(values=["Lebensmittel", "Alle Branchen"] + branchen)
        b = self.b_var.get()
        sel = [o for o in offers if self._branche_ok(o, b)]
        for cb, var, vals in ((self.h_cb, self.h_var, {o["haendler"] for o in sel}),
                              (self.k_cb, self.k_var, {o["kategorie"] for o in sel if o.get("kategorie")})):
            vals = [cb["values"][0] if cb["values"] else var.get()] + sorted(vals)
            cb.config(values=vals)
            if var.get() not in vals:
                var.set(vals[0])

    def _branche_ok(self, o, b=None):
        if b is None:
            b = self.b_var.get()
        return (b == "Alle Branchen" or (b == "Lebensmittel" and off.is_food(o))
                or b in o.get("branche", ""))

    def _min_rabatt(self):
        """Mindest-Rabatt aus den Einstellungen (5–90), None wenn der Filter aus ist."""
        if not self.cfg.get("rabatt_filter"):
            return None
        try:
            return max(5, min(90, int(self.cfg.get("min_rabatt", 20))))
        except (TypeError, ValueError):
            return 20

    def _reset_offer_filters(self):
        """Alle Filter im Angebote-Tab zurücksetzen (der Rabatt-Filter aus den Einstellungen bleibt)."""
        self.b_var.set("Alle Branchen")
        self.h_var.set("Alle Händler")
        self.k_var.set("Alle Kategorien")
        self.rezept_var.set(False)
        self.rabatt_var.set(False)
        self.treue_var.set(False)
        self.q_var.set("")
        self._fill_offers()

    def _fill_offers(self):
        if self._q_after:                       # wartende Such-Aktualisierung wäre doppelt
            self.after_cancel(self._q_after)
            self._q_after = None
        self._offer_filters()
        tv = self.off_tree
        tv.delete(*tv.get_children())
        tv._sorted = None
        self._sort_marks(tv)
        q = " ".join(self.q_var.get().split())
        such = sb.Suche(q) if q else None       # kennt Sorten, Marken und Schreibweisen (suchbegriffe.py)
        h, k = self.h_var.get(), self.k_var.get()
        rezept_ids = {o["id"] for o in self.food} if self.rezept_var.get() else None
        cfg = self.cfg
        # Die Filter einmal lesen, nicht je Angebot – jede Abfrage geht durch Tcl.
        b = self.b_var.get()
        # Mit Suchbegriff gilt „Lebensmittel“ für alle Branchen – sonst fände „Duschgel“ oder „Axe“ nie etwas.
        b_such = "Alle Branchen" if such and b == "Lebensmittel" else b
        nur_rabatt, nur_treue = self.rabatt_var.get(), self.treue_var.get()
        alle_h, alle_k = h == "Alle Händler", k == "Alle Kategorien"
        min_rabatt = self._min_rabatt()
        zeitraum = {}
        zeilen = []
        for o in self.week.get("offers", []):
            if not self._branche_ok(o, b_such):
                continue
            if not alle_h and o["haendler"] != h:
                continue
            if not alle_k and o.get("kategorie") != k:
                continue
            if rezept_ids is not None and o["id"] not in rezept_ids:
                continue
            if nur_treue and not o.get("treue"):
                continue
            pkt = such.passt(o) if such else 0
            if such and not pkt:
                continue
            p = pl.eff_price(o, cfg)
            v = pl.vorher(o, cfg)
            est = v is not None and pl.vorher(o, cfg, schaetzen=False) is None
            if nur_rabatt and (not v or est):
                continue
            rab = round((1 - p / v) * 100) if v else None
            if min_rabatt is not None and (rab is None or rab < min_rabatt):
                continue
            tage = (o["von"], o["bis"])
            gueltig = zeitraum.get(tage)
            if gueltig is None:
                gueltig = zeitraum[tage] = (f"{dt.date.fromisoformat(o['von']):%d.%m.}–"
                                            f"{dt.date.fromisoformat(o['bis']):%d.%m.}")
            rel = o.get("rel")
            zeilen.append((pkt, rab, p, (
                o["haendler"], o["produkt"], o["info"], o.get("kategorie", ""), _eur(p),
                pl.eur(v, est) if v else "", f"{'~' if est else ''}-{rab} %" if v else "",
                f"{rel * 100:+.0f} %" if rel is not None else "", pl.treue_text(o, cfg),
                o["grundpreis"], gueltig)))
        if such:        # beste Treffer zuerst: Sorte/Name vor Marke vor Info-Text, dann Rabatt, dann Preis
            zeilen.sort(key=lambda z: (-z[0], -(z[1] if z[1] is not None else -1), z[2]))
        for n, z in enumerate(zeilen):
            tv.insert("", "end", tags=("odd",) if n % 2 else (), values=z[3])
        n = len(zeilen)
        total = len(self.week.get("offers", []))
        scanned = self.week.get("scanned")
        if not total:
            txt = "Noch keine Angebote geladen"
        else:
            txt = f"{n} Angebote angezeigt  ·  {total} gescannt" + (f" am {scanned}" if scanned else "")
        if min_rabatt is not None:
            txt += f"  ·  ab {min_rabatt} % Rabatt"
        if total and such and b == "Lebensmittel":
            txt += "  ·  Suche in allen Branchen"
        self.off_count.config(text=txt)
        # „Alle zeigen“ nur, wenn ein Filter dieses Tabs die Liste einschränkt
        begrenzt = bool(total) and (b != "Alle Branchen" or not alle_h or not alle_k or q
                                    or rezept_ids is not None or nur_rabatt or nur_treue)
        if begrenzt != self._reset_shown:
            self._reset_shown = begrenzt
            if begrenzt:
                self.off_reset.pack(side="left", padx=(S(14), 0))
            else:
                self.off_reset.pack_forget()
        vor = sb.vorschlag(q, self.week["offers"]) if such and not n and total else None
        self._offers_hinweis(n, total, begrenzt, min_rabatt, vor)

    def _offers_hinweis(self, n, total, begrenzt, min_rabatt, vorschlag=None):
        """Leer-Zustand der Angebotsliste: kein Ort, keine Angebote, Scan läuft oder Filter zu streng."""
        h, plz = self.off_hinweis, self.cfg.get("plz")
        if n:
            return h.verbergen()
        if not total:
            if self._busy:
                h.zeigen("⏳", "Angebote werden geladen …",
                         f"Die Prospekte für die Postleitzahl {plz} werden gerade abgerufen. "
                         "Das dauert einen Moment – den Fortschritt siehst du unten rechts.")
            elif not plz:
                h.zeigen("📍", "Zuerst die Postleitzahl eintragen",
                         "Damit Essens-Plan die Prospekte aus deiner Region laden kann, braucht es "
                         "deine Postleitzahl. Das geht in den Einstellungen.",
                         "Zu den Einstellungen", lambda: self._zu_einstellungen(
                             "Postleitzahl eintragen, dann „Speichern & Angebote laden“"),
                         knopf_icon="⚙️")
            else:
                h.zeigen("🔍", "Noch keine Angebote für diese Woche",
                         f"Lade die aktuellen Prospekte für die Postleitzahl {plz}. "
                         "Danach siehst du hier alle Angebote und kannst daraus einen Wochenplan erstellen. "
                         "Prospekte erscheinen meist ab Sonntag davor.",
                         "Angebote laden (F5)", self.scan, knopf_icon="🔍")
        elif vorschlag:
            h.zeigen("🔎", f"Meintest du „{vorschlag}“?",
                     f"Zu „{' '.join(self.q_var.get().split())}“ passt kein Angebot – vielleicht ein "
                     "Tippfehler. Die Suche kennt Sorten, Marken und viele Schreibweisen.",
                     f"Nach „{vorschlag}“ suchen", lambda: self.q_var.set(vorschlag), knopf_icon="🔍")
        elif begrenzt:
            extra = (f" Der Rabatt-Filter (ab {min_rabatt} %) aus den Einstellungen ist ebenfalls aktiv."
                     if min_rabatt is not None else "")
            h.zeigen("🔎", "Keine passenden Angebote",
                     "Mit der Suche und den Filtern oben bleibt kein Angebot übrig." + extra,
                     "Alle zeigen", self._reset_offer_filters, knopf_icon="🔄", kind="sky")
        elif min_rabatt is None:
            h.verbergen()
        else:
            h.zeigen("🏷️", "Der Rabatt-Filter blendet alles aus",
                     f"Es sind {total} Angebote geladen, aber keins hat mindestens "
                     f"{min_rabatt} % Rabatt. Senke die Schwelle oder schalte den Filter aus.",
                     "Rabatt-Filter ändern",
                     lambda: self._zu_einstellungen(feld=self.mr_spin), knopf_icon="⚙️", kind="sky")

    # ── Tab: Essensplan ───────────────────────────────────────────────────────
    def _build_plan_tab(self, page):
        sa = self.plan_area = ScrollArea(page, bg=C["bg"])
        sa.pack(fill="both", expand=True, padx=(S(8), 0), pady=(0, S(4)))
        f = sa.inner

        sc = Card(f, pad=12, padx=16)
        sc.pack(fill="x")
        self.st_stores = Stat(sc.body, "🏪", "Einkauf bei")
        self.st_hits = Stat(sc.body, "🏷️", "Zutaten im Angebot")
        self.st_cost = Stat(sc.body, "💶", "ca. Kosten")
        self.st_saved = Stat(sc.body, "💰", "Gespart", circle=C["green_soft"])
        self._reflow(sc.body, [self.st_stores, self.st_hits, self.st_cost, self.st_saved], 210)

        self.tage_zeile = tz = tk.Frame(f, bg=C["bg"])
        tz.pack(fill="x", padx=S(14), pady=(0, S(2)))
        self.tage_lbl = tk.Label(tz, text="", bg=C["bg"], fg=C["subtext"], font=F["small_bold"], anchor="w")
        self.tage_lbl.pack(side="left")
        tip(self.tage_lbl, "Nicht jeder Tag braucht ein Gericht: Mit ✕ an einem Tag nimmst du ihn aus dem "
                           "Plan, mit „Tag hinzufügen“ holst du ihn zurück.")
        self.btn_tag = Btn(tz, "Tag hinzufügen", self._tag_menue, kind="light", icon="➕", padx=10, pady=5,
                           tip="Einen Tag, der nicht im Plan ist, wieder aufnehmen")
        self.btn_tag.pack(side="right")

        names = sorted(r["n"] for r in self.recipes)
        self.day_rows = []
        for i in range(7):
            card = Card(f, pad=10, padx=14, hover=True)
            card.pack(fill="x")
            b = card.body
            icon = RoundIcon(b, "🍽️", 52)
            icon.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, S(14)))
            icon.configure(cursor="hand2")
            icon.bind("<Button-1>", lambda e, i=i: self.show_dish(i))
            tip(icon, "Zutaten und Zubereitung dieses Gerichts ansehen (Tab „Gerichte“)")
            head = tk.Frame(b, bg=C["surface"])
            head.grid(row=0, column=1, sticky="w", padx=(0, S(14)))
            day = tk.Label(head, text="", bg=C["surface"], fg=C["text"], font=F["h3"], anchor="w")
            day.pack(anchor="w")
            sub = tk.Frame(head, bg=C["surface"])
            sub.pack(anchor="w")
            date = tk.Label(sub, text="", bg=C["surface"], fg=C["subtext"], font=F["small_bold"])
            date.pack(side="left")
            badge = tk.Label(sub, text="HEUTE", bg=C["accent"], fg=C["on_accent"],
                             font=F["small_bold"], padx=S(6))
            tip(badge, "Das ist der heutige Tag")
            b.columnconfigure(1, minsize=S(118))

            var = tk.StringVar()
            cb = ttk.Combobox(b, textvariable=var, values=names, state="readonly", width=34, font=F["combo"])
            cb.grid(row=0, column=2, sticky="w")
            cb.bind("<<ComboboxSelected>>", lambda e, i=i: self._set_day(i))
            sa.bind_wheel(cb)
            tip(cb, "Gericht für diesen Tag selbst auswählen")
            Btn(b, "Neu", lambda i=i: self.regen_day(i), kind="light", icon="🔄", padx=10, pady=5,
                tip="Für diesen Tag ein anderes Gericht auswürfeln").grid(
                row=0, column=3, sticky="w", padx=(S(8), 0))
            meta = tk.Label(b, text="", bg=C["surface"], fg=C["subtext"], font=F["small_bold"], anchor="e")
            meta.grid(row=0, column=4, sticky="e", padx=(S(12), 0))
            tip(meta, "So viele Zutaten dieses Gerichts sind diese Woche im Angebot – und was sie zusammen kosten")
            b.columnconfigure(4, weight=1)
            xbtn = Btn(b, "✕", lambda i=i: self.remove_day(i), kind="light", padx=8, pady=3,
                       tip="Diesen Tag aus dem Plan nehmen")
            xbtn.grid(row=0, column=5, sticky="ne", padx=(S(10), 0))

            holder = tk.Frame(b, bg=C["surface"], height=S(22))
            holder.pack_propagate(False)
            holder.grid(row=1, column=1, columnspan=4, sticky="ew", pady=(S(6), 0))
            t = tk.Text(holder, bg=C["surface"], fg=C["text"], font=F["small"], relief="flat", bd=0,
                        highlightthickness=0, wrap="word", cursor="arrow", padx=0, pady=0, width=1, height=1,
                        spacing1=S(2), spacing2=S(5), spacing3=S(2), takefocus=0, insertwidth=0,
                        selectbackground=C["surface"], inactiveselectbackground=C["surface"])
            t.pack(fill="both", expand=True)
            t.tag_configure("hit", foreground=C["green"], background=C["green_soft"], font=F["small_bold"])
            t.tag_configure("old", overstrike=True, foreground=C["subtext"], font=F["small"])
            t.tag_configure("muted", foreground=C["subtext"])
            t.tag_configure("label", foreground=C["subtext"], font=F["small_bold"])
            t.bind("<Configure>", lambda e, t=t: self._fit_text(t))
            sa.bind_wheel(t)
            self.day_rows.append({"card": card, "icon": icon, "day": day, "date": date, "badge": badge,
                                  "var": var, "cb": cb, "meta": meta, "info": t, "x": xbtn, "shown": True})
        legend = ui.wrap_label(f, bg=C["bg"], fg=C["subtext"], font=F["small"], padx=S(12),
                               text="Grün = Zutat ist diese Woche im Angebot  ·  durchgestrichen = Normalpreis  ·  "
                                    "~ = geschätzt  ·  📱 = mit App/Karte  ·  Werte je Gericht, die Einkaufsliste "
                                    "fasst gleiche Zutaten zusammen")
        legend.pack(fill="x", pady=(0, S(10)))
        tip(legend, "Erklärung der Farben und Zeichen in den Tageskarten")
        self.plan_hinweis = self._leer_hinweis(sa)

    def _fit_text(self, t):
        """Höhe des Info-Textes an die umgebrochenen Zeilen anpassen."""
        try:
            h = int(t.tk.call(t._w, "count", "-update", "-ypixels", "1.0", "end")) + S(2)
        except (tk.TclError, ValueError):
            return
        if h != getattr(t, "_fit_h", None):
            t._fit_h = h
            t.master.configure(height=max(S(16), h))

    def _monday(self):
        return off.week_start(self.year, self.kw)

    def _day_key(self, i):
        return (self._monday() + dt.timedelta(days=i)).isoformat()

    def _pcfg(self):
        """Einstellungen für Plan/Liste: Händler = für diese Woche gewählte Läden."""
        stores = self.week.get("laeden")
        return {**self.cfg, "haendler": stores} if stores else self.cfg

    def _tage(self):
        """Aktive Wochentage des Plans (0 = Montag), sortiert, nie leer."""
        return self.week.setdefault("tage", list(range(7)))

    def _plan_aktiv(self):
        """Plan nur für die Tage, die im Plan sind."""
        keys = {self._day_key(i) for i in self._tage()}
        return {k: v for k, v in self.week.get("plan", {}).items() if k in keys}

    def _apply_tage(self):
        """Tageskarten ein-/ausblenden (nur bei Änderung; die Karten werden nie zerstört)."""
        tage = self._tage()
        prev = self.tage_zeile
        for i, row in enumerate(self.day_rows):
            an = i in tage
            if an and not row["shown"]:
                row["card"].pack(fill="x", after=prev)
                row["shown"] = True
            elif not an and row["shown"]:
                row["card"].pack_forget()
                row["shown"] = False
            if an:
                prev = row["card"]
        letzter = len(tage) <= 1
        for row in self.day_rows:
            if row["x"].enabled == letzter:
                row["x"].set_enabled(not letzter)
                row["x"].tooltip.text = ("Mindestens ein Tag muss im Plan bleiben" if letzter
                                         else "Diesen Tag aus dem Plan nehmen")
        n = len(tage)
        self.tage_lbl.config(text=f"{n} von 7 Tagen im Plan")
        if self.btn_tag.enabled == (n >= 7):
            self.btn_tag.set_enabled(n < 7)
            self.btn_tag.tooltip.text = ("Alle sieben Tage sind im Plan" if n >= 7
                                         else "Einen Tag, der nicht im Plan ist, wieder aufnehmen")

    def _fill_plan(self):
        plan = self.week.get("plan", {})
        by_name = {r["n"]: r for r in self.recipes}
        offers, cfg = self.food, self._pcfg()
        total, before, hits, need, used = 0.0, 0.0, 0, 0, set()
        today = dt.date.today()
        self._apply_tage()
        tage = self._tage()
        for i, row in enumerate(self.day_rows):
            if i not in tage:
                continue
            d = self._monday() + dt.timedelta(days=i)
            is_today = d == today
            row["card"].set_accent(C["accent"] if is_today else None, 2)
            row["day"].config(text=pl.TAGE[i], fg=C["accent"] if is_today else C["text"])
            row["date"].config(text=f"{d:%d.%m.%Y}")
            if is_today:
                row["badge"].pack(side="left", padx=(S(6), 0))
            else:
                row["badge"].pack_forget()
            name = plan.get(d.isoformat(), "")
            row["var"].set(name)
            r = by_name.get(name)
            row["icon"].set(pl.dish_icon(r))
            t = row["info"]
            t.config(state="normal")
            t.delete("1.0", "end")
            row["meta"].config(text="")
            if not r:
                t.insert("end", "Noch kein Gericht – oben „Plan generieren“ klicken, „Neu“ drücken oder "
                         "ein Gericht auswählen" if not name else f"Rezept „{name}“ nicht gefunden", "muted")
            else:
                other, d_hits, d_need, d_cost = [], 0, 0, 0.0
                for z, o in pl.recipe_offers(r, offers, cfg):
                    if pl._terms(z):
                        d_need += 1
                    if not o:
                        other.append(z[0])
                        continue
                    p, v = pl.eff_price(o, cfg), pl.vorher(o, cfg)
                    t.insert("end", f" ✔ {z[0]} · {o['haendler']} {_eur(p)} ".replace(" ", NB), "hit")
                    if v:
                        t.insert("end", pl.eur(v, pl.geschaetzt(o, cfg)).replace(" ", NB), ("hit", "old"))
                        t.insert("end", NB, "hit")
                    if o.get("treue"):
                        t.insert("end", "📱" + NB, "hit")
                    t.insert("end", "   ")
                    total += p
                    before += v or p
                    d_cost += p
                    d_hits += 1
                    used.add(o["haendler"])
                if not d_hits:
                    t.insert("end", "Keine Zutat im Angebot", "muted")
                if other:
                    t.insert("end", "\n")
                    t.insert("end", "Sonst:  ", "label")
                    t.insert("end", ", ".join(other), "muted")
                hits += d_hits
                need += d_need
                if d_hits:
                    row["meta"].config(text=f"{d_hits}/{d_need} im Angebot  ·  {_eur(d_cost)}")
            t.config(state="disabled")
        self.st_stores.set(" + ".join(sorted(used)) if used else "–")
        self.st_hits.set(f"{hits} von {need}" if need else "–")
        self.st_cost.set(_eur(total) if hits else "–")
        self.st_saved.set(_eur(before - total) if hits else "–", C["green"] if before > total else None)
        self._plan_leer()
        self.after_idle(lambda: [self._fit_text(row["info"]) for i, row in enumerate(self.day_rows)
                                 if i in tage])

    def _plan_leer(self):
        """Leer-Zustand des Plan-Tabs: keine PLZ, keine Angebote oder noch kein Plan."""
        h = self.plan_hinweis
        if self._plan_aktiv():
            return h.verbergen()
        plz, offers = self.cfg.get("plz"), self.week.get("offers")
        if self._busy and not offers:
            h.zeigen("⏳", "Angebote werden geladen …",
                     "Sobald die Prospekte da sind, kannst du hier einen Wochenplan erstellen lassen.")
        elif not plz and not offers:
            h.zeigen("📍", "Zuerst die Postleitzahl eintragen",
                     "Damit Essens-Plan Angebote aus deiner Region laden und daraus einen Plan machen kann, "
                     "braucht es deine Postleitzahl. Das geht in den Einstellungen.",
                     "Zu den Einstellungen", lambda: self._zu_einstellungen(
                         "Postleitzahl eintragen, dann „Speichern & Angebote laden“"), knopf_icon="⚙️")
        elif not offers:
            h.zeigen("🔍", "Noch keine Angebote für diese Woche",
                     "Ein Plan entsteht aus den Wochenangeboten. Lade zuerst die aktuellen Prospekte "
                     f"für die Postleitzahl {plz}.", "Angebote laden (F5)", self.scan, knopf_icon="🔍")
        else:
            h.zeigen("✨", "Noch kein Plan",
                     "Essens-Plan sucht Gerichte, deren Zutaten diese Woche im Angebot sind. "
                     "Einzelne Tage änderst du danach mit „Neu“ oder der Auswahlliste.",
                     "Plan generieren (F6)", self.generate, knopf_icon="✨")

    def _tag_menue(self):
        """Menü mit den Tagen, die gerade nicht im Plan sind."""
        fehlend = [i for i in range(7) if i not in self._tage()]
        if not fehlend:
            return
        if getattr(self, "_tag_menu", None) is not None:
            self._tag_menu.destroy()        # erst jetzt: unter Windows läuft der Befehl nach tk_popup
        m = self._tag_menu = tk.Menu(self, tearoff=0)
        for i in fehlend:
            d = self._monday() + dt.timedelta(days=i)
            m.add_command(label=f"{pl.TAGE[i]}, {d:%d.%m.}", command=lambda i=i: self.add_day(i))
        b = self.btn_tag
        try:
            m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            m.grab_release()

    def remove_day(self, i):
        tage = self._tage()
        if i not in tage or len(tage) <= 1:
            return self.set_status("Mindestens ein Tag muss im Plan bleiben")
        tage.remove(i)
        self.week.get("plan", {}).pop(self._day_key(i), None)
        self._save_and_refresh()
        self.set_status(f"{pl.TAGE[i]} aus dem Plan genommen – mit „Tag hinzufügen“ kommt er zurück")

    def add_day(self, i):
        tage = self._tage()
        if i in tage:
            return
        tage.append(i)
        tage.sort()
        neu = ""
        if self.week.get("plan"):             # es gibt schon einen Plan: der Tag bekommt gleich ein Gericht
            pl.regenerate_day(self.recipes, self.food, self._pcfg(), self.week["plan"], self._day_key(i))
            neu = " – mit „Neu“ gibt es ein anderes Gericht"
        self._save_and_refresh()
        self.set_status(f"{pl.TAGE[i]} zum Plan hinzugefügt{neu}")

    def _set_day(self, i):
        self.week.setdefault("plan", {})[self._day_key(i)] = self.day_rows[i]["var"].get()
        self._save_and_refresh()

    def regen_day(self, i):
        if not self.week.get("plan"):
            return self.generate()
        pl.regenerate_day(self.recipes, self.food, self._pcfg(),
                          self.week["plan"], self._day_key(i))
        self._save_and_refresh()
        self.set_status(f"{pl.TAGE[i]}: anderes Gericht ausgewählt")

    def generate(self):
        if not self.recipes:
            return messagebox.showerror("Fehler", "Keine Rezepte gefunden (res/rezepte.json).",
                                        parent=self)
        if not self.week.get("offers"):         # ohne Angebote gibt es nichts zu planen: dorthin, wo man sie holt
            if not self.cfg.get("plz"):
                return self._zu_einstellungen("Zuerst die Postleitzahl eintragen – dann lassen sich "
                                              "Angebote laden und ein Plan erstellen")
            self.tabs.select(T_ANGEBOTE)
            return self.set_status("Noch keine Angebote für diese Woche – zuerst „Angebote scannen“ (F5)")
        warn = ""
        mn = self._min_rabatt()
        if not self.food and mn is not None:    # alle Angebote vom Rabatt-Filter verschluckt
            warn = (f"Der Rabatt-Filter (ab {mn} %) lässt keine Angebote übrig – Plan ohne Angebote "
                    "erstellt. In den Einstellungen anpassen.")
        self.week["plan"], self.week["laeden"] = pl.generate_week(
            self.recipes, self.food, self.cfg, self._monday(), tage=list(self._tage()))
        self._save_and_refresh()
        self.tabs.select(T_PLAN)
        self.plan_area.cv.yview_moveto(0)
        if warn:
            return self.set_status(warn)
        stores = sorted({it["angebot"]["haendler"] for it in self.items if it["angebot"]})
        self.set_status("Wochenplan generiert" + (f" – Einkauf bei {' + '.join(stores)}" if stores else ""))

    # ── Tab: Einkaufsliste ────────────────────────────────────────────────────
    EXTRA_GRUPPE = "Extras & Notizen"

    def _build_list_tab(self, page):
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=S(8), pady=(0, S(4)))
        card = Card(wrap, pad=12, padx=16)
        card.pack(fill="x")
        b = card.body
        btns = tk.Frame(b, bg=C["surface"])
        btns.grid(row=0, column=0, sticky="w", padx=(0, S(24)))
        Btn(btns, "Kopieren", self.copy_list, kind="light", icon="📋",
            tip="Liste in die Zwischenablage – z. B. zum Einfügen in WhatsApp oder Notizen"
            ).pack(side="left")
        Btn(btns, "PDF drucken", self.export_pdf, kind="navy", icon="🖨️",
            tip="Wochenplan und Einkaufsliste als PDF speichern (Strg+P)").pack(side="left", padx=(S(6), 0))
        stats = tk.Frame(b, bg=C["surface"])
        stats.grid(row=0, column=1, sticky="ew")
        b.columnconfigure(1, weight=1)
        self.ls_sum = Stat(stats, "💶", "Summe")
        self.ls_before = Stat(stats, "🧾", "Normalpreis")
        self.ls_saved = Stat(stats, "💰", "Gespart", circle=C["green_soft"])
        tip(self.ls_sum, "Was die angehakten Artikel zusammen kosten (Angebotspreise)")
        tip(self.ls_before, "Was dieselben Artikel ohne Angebot kosten würden")
        tip(self.ls_saved, "Ersparnis gegenüber dem Normalpreis – nur für angehakte Artikel")
        self._reflow(stats, [self.ls_sum, self.ls_before, self.ls_saved], 170)
        # Schnelleingabe: erst Angebote suchen, sonst ohne Preis aufschreiben (extras.ArtikelSuche)
        extra = tk.Frame(b, bg=C["surface"])
        extra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(S(12), 0))
        RoundIcon(extra, "🛒", 30).pack(side="left", padx=(0, S(10)))
        self.artikel_var = tk.StringVar()
        self.artikel_entry = ttk.Entry(extra, textvariable=self.artikel_var, width=44)
        self.artikel_entry.pack(side="left")
        ui.Platzhalter(self.artikel_entry, self.artikel_var, "Artikel eintippen, z. B. Duschgel, Deo oder Axe")
        self.artikel_entry.bind("<Return>", lambda e: self.artikel_hinzufuegen())
        tip(self.artikel_entry, "Was brauchst du noch? Eine Sorte („Duschgel“, „Zahnpasta“) oder eine Marke "
                                "(„Axe“, „Nivea“) – Schreibweise egal.\nEnter = suchen: Gibt es ein Angebot "
                                "bei deinen Händlern, kannst du es übernehmen. Sonst kommt der Artikel ohne "
                                "Preis auf die Liste.")
        Btn(extra, "Artikel hinzufügen", self.artikel_hinzufuegen, kind="primary", icon="➕",
            tip="Erst nach Angeboten suchen (alle Sorten & Marken deiner Händler), dann auf die Liste "
                "setzen. Mit leerem Feld: die besten Rabatte zum Stöbern."
            ).pack(side="left", padx=(S(8), 0))
        Btn(extra, "Notiz hinzufügen", self.notiz_hinzufuegen, kind="light", icon="📝",
            tip="Einen eigenen Eintrag ohne Angebotssuche, z. B. „Geschenk für Oma“"
            ).pack(side="left", padx=(S(6), 0))
        ui.wrap_label(b, "So geht's: Artikel eintippen und Enter – Essens-Plan sucht zuerst bei deinen "
                         "Händlern nach Angeboten (alle Sorten und Marken, auch z. B. „Axe“ für Deo & "
                         "Duschgel). Gibt es keins, kommt der Artikel ohne Preis auf die Liste.",
                      bg=C["surface"], fg=C["subtext"], font=F["small"]
                      ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(S(6), 0))
        self.list_hint = ui.wrap_label(b, "", bg=C["surface"], fg=C["subtext"], font=F["small"])
        self.list_hint.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(S(8), 0))
        tip(self.list_hint, "Häkchen = kommt auf die Einkaufsliste. Kein Häkchen = habe ich schon da – "
                            "die Zeile wird grau und zählt nicht zur Summe.")

        cols = [("menge", "Menge", 80), ("artikel", "Artikel", 170), ("angebot", "Angebot", 330),
                ("preis", "Preis", 75), ("vorher", "Vorher", 75), ("spar", "Gespart", 75),
                ("treue", "Treue-Aktion", 150), ("fuer", "Für", 230)]
        self.list_tree = tv = self._tree(wrap, cols, show="tree headings", flex=("angebot", "fuer"))
        tv.column("#0", width=S(200), minwidth=S(120), stretch=False)
        tv._widths["#0"] = S(200)
        tv.heading("#0", text="Händler", anchor="w")
        tv.tag_configure("aus", foreground=mix(C["subtext"], C["surface"], 0.3))   # nur Schrift: Hover bleibt
        self._grp_icon = tkfont.Font(font=F["base"]).metrics("linespace") + S(4)
        self._li_rows, self._li_names, self._li_grp, self._li_alle = {}, {}, {}, []
        tv.bind("<Button-1>", self._li_klick, add="+")
        tv.bind("<Double-1>", self._li_doppel, add="+")
        tv.bind("<space>", self._li_leertaste)
        tv.bind("<Delete>", self._li_entf)
        tv.bind("<Button-3>", self._li_menue)
        self.list_hinweis = self._leer_hinweis(tv._card)

    def _groups(self):
        groups = {}
        for it in self.items:
            key = ("Vorrat prüfen" if it["vorrat"] else
                   it["angebot"]["haendler"] if it["angebot"] else "Ohne Angebot")
            groups.setdefault(key, []).append(it)
        return groups

    # Haken: angehakt = kommt auf die Einkaufsliste. Vorrats-Zutaten sind anfangs nicht angehakt.
    def _an_item(self, it):
        return self.week["liste"]["haken"].get(it["name"], not it["vorrat"])

    @staticmethod
    def _extra_preis(e):
        a = e.get("angebot")
        if not a or a.get("preis") is None:
            return None
        return {"preis": a["preis"], "vorher": a.get("vorher"), "geschaetzt": bool(a.get("geschaetzt"))}

    def _an(self, entry):
        return self._an_item(entry["ref"]) if entry["k"] == "i" else entry["ref"]["haken"]

    def _fill_list(self, keep=False):
        """Liste komplett neu aufbauen (nach Plan-/Angebotsänderungen). keep=True behält die Scrollposition."""
        tv = self.list_tree
        y = tv.yview()[0] if keep else 0
        tv.delete(*tv.get_children())
        self._li_rows.clear()
        self._li_names.clear()
        self._li_grp.clear()
        self._li_alle = []
        cfg = self._pcfg()
        self.items = pl.shopping_list(self.recipes, self.food, cfg, self._plan_aktiv())
        gruppen = list(self._groups().items())
        extras = self.week["liste"]["extras"]
        if extras:
            gruppen.append((self.EXTRA_GRUPPE, extras))
        for g, its in gruppen:
            img = ui.emoji_img(GROUP_ICONS.get(g, "🏪"), self._grp_icon, C["surface"])
            gid = tv.insert("", "end", text=f" {g}", image=img or "", open=True, tags=("grp",),
                            values=("", "", "", ""))
            self._li_grp[gid] = (g, [])
            for n, it in enumerate(its):
                if g == self.EXTRA_GRUPPE:
                    entry = {"k": "e", "ref": it, "p": self._extra_preis(it), "gid": gid}
                    vals = self._extra_werte(it)
                else:
                    o = it["angebot"]
                    p, v, est = it["preis"], it["vorher"], it["geschaetzt"]
                    entry = {"k": "i", "ref": it, "p": it, "gid": gid}
                    vals = (it["menge"], it["name"],
                            f"{o['produkt']} – {o['info']}" if o else "",
                            _eur(p) if o else "", pl.eur(v, est) if v else "",
                            pl.eur(v - p, est) if v else "", pl.treue_text(o, cfg) if o else "",
                            ", ".join(sorted(set(it["gerichte"]))))
                an = self._an(entry)
                tags = (["odd"] if n % 2 else []) + ([] if an else ["aus"])
                iid = tv.insert(gid, "end", image=ui.haken_img(an) or "", tags=tags, values=vals)
                entry["iid"] = iid
                self._li_rows[iid] = entry
                self._li_grp[gid][1].append(entry)
                self._li_alle.append(entry)
                if entry["k"] == "i":
                    self._li_names.setdefault(it["name"], []).append(iid)
            self._li_gruppe(gid)
        self._li_sums()
        self._li_leer()
        if keep:
            tv.yview_moveto(y)

    @staticmethod
    def _extra_werte(e):
        a = e.get("angebot")
        if e["typ"] == "notiz":
            return ("Notiz", "", e["text"], "", "", "", "", "")
        if not a:
            return ("Extra", e["text"], "", "", "", "", "", "")
        p, v, est = a.get("preis"), a.get("vorher"), a.get("geschaetzt")
        return ("Extra", e["text"], f"{a['haendler']}: {a['produkt']}" + (f" – {a['info']}" if a.get("info") else ""),
                _eur(p) if p is not None else "", pl.eur(v, est) if v else "",
                pl.eur(v - p, est) if v and p is not None else "", "", "")

    def _li_gruppe(self, gid):
        """Kopfzeile einer Gruppe: Anzahl und Zwischensumme der angehakten Zeilen."""
        g, entries = self._li_grp[gid]
        an = [e for e in entries if self._an(e)]
        sub = pl.totals([e["p"] for e in an if e["p"]])[0]
        wort = "Einträge" if g == self.EXTRA_GRUPPE else "Artikel"
        n = f"{len(entries)} {wort}" if len(an) == len(entries) else f"{len(an)} von {len(entries)} {wort}"
        tv = self.list_tree
        tv.item(gid, values=("", n, "", _eur(sub) if sub else ""))

    def _summen_items(self):
        return [e["p"] for e in self._li_alle if e["p"] and self._an(e)]

    def _li_sums(self):
        """Summe, Normalpreis und Ersparnis über die angehakten Zeilen."""
        its = self._summen_items()
        now, before, saved, est, unknown = pl.totals(its)
        n = sum(1 for e in self._li_alle if self._an(e))
        self.ls_sum.set(_eur(now) if now else f"{n} Artikel")
        self.ls_before.set(pl.eur(before, est) if now else "–")
        self.ls_saved.set(f"{pl.eur(saved, est)}  ({saved / before * 100:.0f} %)" if now and before else "–",
                          C["green"] if saved > 0 else None)
        hint = pl.sum_hint(est, unknown)
        self.list_hint.config(text="Häkchen = kommt auf die Einkaufsliste, ohne Häkchen = habe ich schon  ·  "
                                   "Je 1 Packung pro Artikel  ·  Preise inkl. deiner Treue-Programme"
                                   + (f"  ·  {hint}" if hint else ""))

    def _li_leer(self):
        """Leer-Zustand der Einkaufsliste."""
        h = self.list_hinweis
        if self._li_alle:
            return h.verbergen()
        plz, offers = self.cfg.get("plz"), self.week.get("offers")
        if self._plan_aktiv():
            h.zeigen("🛒", "Die Einkaufsliste ist leer",
                     "Zu den geplanten Gerichten gibt es keine Zutaten. Du kannst oben trotzdem eigene "
                     "Produkte und Notizen hinzufügen.")
        elif not plz and not offers:
            h.zeigen("📍", "Zuerst die Postleitzahl eintragen",
                     "Die Einkaufsliste entsteht aus dem Wochenplan, der auf den Angeboten deiner Region "
                     "beruht. Dafür braucht Essens-Plan deine Postleitzahl.",
                     "Zu den Einstellungen", lambda: self._zu_einstellungen(
                         "Postleitzahl eintragen, dann „Speichern & Angebote laden“"), knopf_icon="⚙️")
        else:
            h.zeigen("🛒", "Noch kein Plan",
                     "Die Einkaufsliste entsteht aus dem Wochenplan: alle Zutaten der geplanten Gerichte, "
                     "mit dem günstigsten Angebot dazu. Du kannst oben auch eigene Produkte und Notizen "
                     "hinzufügen.", "Plan generieren (F6)", self.generate, knopf_icon="✨")

    # ── Haken umschalten ──────────────────────────────────────────────────────
    def _li_setzen(self, entry, an):
        """Haken einer Zeile setzen (bei Zutaten gilt er für alle Zeilen mit gleichem Namen)."""
        tv = self.list_tree
        if entry["k"] == "i":
            name = entry["ref"]["name"]
            self.week["liste"]["haken"][name] = an
            iids = self._li_names.get(name, [entry["iid"]])
        else:
            entry["ref"]["haken"] = an
            iids = [entry["iid"]]
        img = ui.haken_img(an) or ""
        gids = set()
        for iid in iids:
            tags = [t for t in tv.tk.splitlist(tv.item(iid, "tags")) if t != "aus"]
            if not an:
                tags.append("aus")
            tv.item(iid, image=img, tags=tags)       # Hover-Tags bleiben erhalten
            gids.add(self._li_rows[iid]["gid"])
        for gid in gids:
            self._li_gruppe(gid)

    def _li_umschalten(self, iids):
        rows = [self._li_rows[i] for i in iids if i in self._li_rows]
        if not rows:
            return
        an = not self._an(rows[0])
        for e in rows:
            self._li_setzen(e, an)
        self._li_sums()
        self._save_later()

    def _li_klick(self, e):
        tv = self.list_tree
        row = tv.identify_row(e.y)
        if row in self._li_rows and tv.identify_column(e.x) == "#0":
            self._li_umschalten([row])

    def _li_doppel(self, e):
        tv = self.list_tree
        row = tv.identify_row(e.y)
        if row in self._li_rows and tv.identify_column(e.x) != "#0":   # im Kästchen-Bereich zählt der Klick
            self._li_umschalten([row])

    def _li_leertaste(self, e):
        self._li_umschalten(self.list_tree.selection())
        return "break"

    def _li_menue(self, e):
        tv = self.list_tree
        row = tv.identify_row(e.y)
        if row not in self._li_rows:
            return
        if row not in tv.selection():
            tv.selection_set(row)
        sel = [r for r in tv.selection() if r in self._li_rows]
        if getattr(self, "_li_menu", None) is not None:
            self._li_menu.destroy()
        m = self._li_menu = tk.Menu(self, tearoff=0)
        m.add_command(label="Haken umschalten", command=lambda: self._li_umschalten(sel))
        if any(self._li_rows[r]["k"] == "e" for r in sel):
            m.add_command(label="Entfernen", command=lambda: self._li_entf())
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ── Extras & Notizen ──────────────────────────────────────────────────────
    def extra_hinzufuegen(self, typ, text, angebot=None):
        """Extra-Produkt (mit Angebots-Schnappschuss) oder Notiz anhängen. False = gab es schon."""
        extras = self.week["liste"]["extras"]
        for x in extras:
            a = x.get("angebot")
            if typ == "produkt" and x["typ"] == "produkt" and (
                    (angebot and a and a.get("id") == angebot.get("id") and a.get("id") is not None)
                    or (not angebot and not a and x["text"].lower() == text.lower())):
                return False
        neu = {"typ": typ, "text": text, "haken": True}
        if angebot:
            neu["angebot"] = angebot
        extras.append(neu)
        self._fill_list(keep=True)
        self._save_later()
        e = next((x for x in self._li_alle if x["ref"] is neu), None)
        if e:
            self.list_tree.see(e["iid"])
        return True

    def extra_suchen(self, text=None):
        """Fenster „Artikel hinzufügen“ öffnen (oder nach vorn holen) – optional mit Suchbegriff."""
        w = getattr(self, "_extra_suche", None)
        if w is not None and not w._zu:
            try:
                w.win.deiconify()
                w.win.lift()
                if text is not None:
                    w.suche_setzen(text)
                w.entry.focus_set()
                return
            except tk.TclError:
                pass
        self._extra_suche = ext.ArtikelSuche(self, text or "")

    def artikel_hinzufuegen(self):
        """Schnelleingabe der Einkaufsliste: gibt es Angebote, zeigt das Fenster „Artikel hinzufügen“
        sie zur Auswahl; sonst Rückfrage (abschaltbar) und der Artikel kommt ohne Preis auf die Liste."""
        if getattr(self, "_frage_dialog", None) is not None:
            return
        text = " ".join(self.artikel_var.get().split())
        if not text:
            return self.extra_suchen()
        daten = ext.angebote(self)
        such = sb.Suche(text)
        if any(such.passt(d[1]) for d in daten) or (
                daten and sb.vorschlag(text, (d[1] for d in daten)) is not None):
            self.artikel_var.set("")
            return self.extra_suchen(text)
        name = ext._gross(text)

        def aufschreiben():
            neu = self.extra_hinzufuegen("produkt", name, None)
            self.artikel_var.set("")
            self.set_status(f"✔ {name} steht ohne Preis auf der Einkaufsliste" if neu
                            else f"{name} steht schon auf der Einkaufsliste")
            try:
                self.artikel_entry.focus_set()
            except tk.TclError:
                pass
        if not ext.fragen(self):
            return aufschreiben()
        grund = ("Es sind noch keine Angebote geladen (F5 lädt sie)." if not self.week.get("offers") else
                 ext.leer_text(self) if not daten else
                 f"Bei deinen Händlern ist diese Woche nichts zu „{name}“ im Angebot.")
        self._frage_dialog = ext.FrageDialog(self, name, grund, aufschreiben)

    def notiz_hinzufuegen(self):
        w = getattr(self, "_notiz_dialog", None)
        if w is not None and not w._zu:
            try:
                w.win.lift()
                w.entry.focus_set()
                return
            except tk.TclError:
                pass

        def ok(text):
            self.extra_hinzufuegen("notiz", text)
            self.set_status("✔ Notiz hinzugefügt")
        self._notiz_dialog = ext.NotizDialog(self, ok)

    def _li_entf(self, e=None):
        """Markierte Extras/Notizen entfernen (Entf-Taste oder Kontextmenü)."""
        tv = self.list_tree
        weg = [self._li_rows[r]["ref"] for r in tv.selection()
               if r in self._li_rows and self._li_rows[r]["k"] == "e"]
        if not weg:
            if tv.selection():
                self.set_status("Zutaten aus dem Plan lassen sich nur abhaken – entfernen kannst du "
                                "eigene Extras und Notizen")
            return "break"
        extras = self.week["liste"]["extras"]
        extras[:] = [x for x in extras if not any(x is w for w in weg)]
        self._fill_list(keep=True)
        self._save_later()
        self.set_status(f"{len(weg)} Eintrag entfernt" if len(weg) == 1 else f"{len(weg)} Einträge entfernt")
        return "break"

    # ── Speichern (gebündelt: die Wochendatei ist groß, ein Klick soll nicht warten) ──
    def _save_later(self):
        self._save_pending = (self.year, self.kw, self.week)
        if self._save_id is None:
            self._save_id = self.after(700, self._save_flush)

    def _save_flush(self):
        if self._save_id is not None:
            try:
                self.after_cancel(self._save_id)
            except tk.TclError:
                pass
            self._save_id = None
        p, self._save_pending = self._save_pending, None
        if p:
            try:
                off.save_week(*p)
            except OSError as ex:
                self.set_status(f"Speichern fehlgeschlagen: {ex}")

    def _sum_text(self):
        now, before, saved, est, unknown = pl.totals(self._summen_items())
        if not now:
            return f"{sum(1 for e in self._li_alle if self._an(e))} Artikel"
        txt = (f"Summe {_eur(now)}   ·   vorher {pl.eur(before, est)}   ·   gespart {pl.eur(saved, est)}"
               f" ({saved / before * 100:.0f} %)")
        hint = pl.sum_hint(est, unknown)
        return txt + (f"\n{hint}" if hint else "")

    def copy_list(self):
        if not self._li_alle:
            self.set_status("Die Einkaufsliste ist noch leer – zuerst „Plan generieren“ (F6)")
            return
        lines = [f"Einkaufsliste {off.week_label(self.year, self.kw)}"]
        for g, entries in self._li_grp.values():
            an = [e for e in entries if self._an(e)]      # nur, was gekauft werden soll
            if not an:
                continue
            lines.append(f"\n{g}:")
            for e in an:
                if e["k"] == "i":
                    it = e["ref"]
                    lines.append(f"  ☐ {it['menge']} {it['name']}" +
                                 (f"  ({_eur(it['preis'])}" if it["angebot"] else "") +
                                 (f", statt {pl.eur(it['vorher'], it['geschaetzt'])})" if it["vorher"]
                                  else ")" if it["angebot"] else ""))
                    continue
                x, a = e["ref"], e["ref"].get("angebot")
                if x["typ"] == "notiz":
                    lines.append(f"  ✎ {x['text']}")
                elif a and a.get("preis") is not None:
                    lines.append(f"  ☐ {x['text']}  ({a['haendler']}, {_eur(a['preis'])}" +
                                 (f", statt {pl.eur(a['vorher'], a.get('geschaetzt'))})" if a.get("vorher")
                                  else ")"))
                else:
                    lines.append(f"  ☐ {x['text']}")
        lines.append("\n" + self._sum_text())
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.set_status("Einkaufsliste in die Zwischenablage kopiert")

    # ── Tab: Einstellungen ────────────────────────────────────────────────────
    def _build_settings_tab(self, page):
        sa = ScrollArea(page, bg=C["bg"], fill_height=True)
        sa.pack(fill="both", expand=True, padx=(S(8), 0), pady=(0, S(4)))
        f = sa.inner
        for c in range(3):
            f.columnconfigure(c, weight=1, uniform="set")
        f.rowconfigure(1, weight=1)     # Zeile 0: Willkommen (nur beim ersten Start), Zeile 1: drei Spalten

        wc = self.welcome = Card(f, pad=16)
        wc.grid(row=0, column=0, columnspan=3, sticky="ew")
        w = wc.body
        w.columnconfigure(0, weight=1)
        Section(w, "👋", "Willkommen bei Essens-Plan").grid(row=0, column=0, sticky="ew")
        ui.wrap_label(w, "Trage unten deine Postleitzahl ein, damit die Prospekte aus deiner Region geladen "
                         "werden. Hake danach deine Händler und Treue-Programme an (nichts angehakt = alle "
                         "Händler) und schalte bei Bedarf den Rabatt-Filter ein. Dann geht es mit "
                         "„Speichern & Angebote laden“ los.",
                      bg=C["surface"], fg=C["text"], font=F["base"]
                      ).grid(row=1, column=0, sticky="ew", pady=(S(10), 0))
        Btn(w, "Speichern & Angebote laden", self.first_start, kind="primary", icon="📥",
            font=F["big"], padx=26, pady=11,
            tip="Einstellungen speichern und die Angebote dieser Woche laden"
            ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(S(24), 0))
        if self.cfg.get("plz"):
            wc.grid_remove()

        links = tk.Frame(f, bg=C["bg"])
        links.grid(row=1, column=0, sticky="nsew")
        gc = Card(links, pad=16)
        gc.pack(fill="both", expand=True)
        g = gc.body
        Section(g, "📍", "Allgemein", "Region, Haushalt und Planung").pack(fill="x", pady=(0, S(16)))
        self.plz_var = tk.StringVar(value=self.cfg.get("plz", ""))
        self.pers_var = tk.IntVar(value=self.cfg.get("personen", 2))
        self.veg_var = tk.BooleanVar(value=self.cfg.get("vegetarisch", False))
        self.laeden_var = tk.IntVar(value=self.cfg.get("max_laeden", 2))

        def field(label, widget, hint=None, hilfe=None):
            self._field_label(g, label).pack(fill="x")
            widget.pack(anchor="w", pady=(S(3), S(3) if hint else S(14)))
            if hilfe:
                tip(widget, hilfe)
            if hint:
                h = ui.wrap_label(g, hint, bg=C["surface"], fg=C["subtext"], font=F["small"])
                h.pack(fill="x", pady=(0, S(14)))
                return h
        self.plz_entry = ttk.Entry(g, textvariable=self.plz_var, width=12)
        self.plz_hint = field("Postleitzahl", self.plz_entry,
                              PLZ_HINT,
                              "Deine Postleitzahl bestimmt, welche Märkte und Prospekte in der Nähe\n"
                              "geladen werden. Ohne sie lassen sich keine Angebote scannen.")
        field("Personen", ttk.Spinbox(g, from_=1, to=12, textvariable=self.pers_var, width=8),
              "Für wie viele Personen eingekauft wird – bestimmt die Mengen in der Einkaufsliste",
              "Anzahl Personen im Haushalt (1–12). Rezeptmengen und Einkaufsliste rechnen damit.")
        field("Max. Läden pro Woche", ttk.Spinbox(g, from_=0, to=10, textvariable=self.laeden_var, width=8),
              "0 = beliebig viele · gilt beim nächsten „Plan generieren“",
              "So viele verschiedene Märkte darf der Wochenplan höchstens nutzen.\n"
              "Weniger Läden = weniger Wege, mehr Läden = oft günstiger.")
        self.abw_var = tk.BooleanVar(value=self.cfg.get("abwechslung", True))
        self.pdfr_var = tk.BooleanVar(value=self.cfg.get("pdf_rezepte", True))
        self.frag_var = tk.BooleanVar(value=self.cfg.get("artikel_fragen", True))
        for text, var, hilfe in (
                ("Nur vegetarisch", self.veg_var,
                 "Es werden nur Gerichte mit „Vegetarisch“ oder „Vegan“ eingeplant"),
                ("Abwechslung beachten", self.abw_var,
                 "Gerichte der letzten zwei Wochen werden seltener vorgeschlagen"),
                ("Rezepte ins PDF", self.pdfr_var,
                 "Hängt Zutaten und Zubereitung der sieben Gerichte hinten an das PDF an"),
                ("Ohne Angebot nachfragen", self.frag_var,
                 "Einkaufsliste → „Artikel hinzufügen“: Findet sich kein Angebot, wird erst gefragt,\n"
                 "ob der Artikel ohne Preis auf die Liste soll. Aus = sofort aufschreiben.")):
            cb = ttk.Checkbutton(g, text=text, variable=var)
            cb.pack(anchor="w", pady=S(1))
            tip(cb, hilfe)
        ui.wrap_label(g, "💾 Änderungen werden automatisch gespeichert", bg=C["surface"],
                      fg=C["subtext"], font=F["small"]).pack(fill="x", pady=(S(12), 0))
        self._build_discount_card(links)

        mitte = tk.Frame(f, bg=C["bg"])
        mitte.grid(row=1, column=1, sticky="nsew")
        tc = Card(mitte, pad=16)
        tc.pack(fill="x")
        Section(tc.body, "💳", "Treue-Programme", "App-Preise und Bonus-Guthaben werden eingerechnet"
                ).pack(fill="x", pady=(0, S(12)))
        self.prog_vars = {}
        for name in off.PROGRAMME:
            var = tk.BooleanVar(value=name in self.cfg.get("programme", []))
            cb = ttk.Checkbutton(tc.body, text=name, variable=var)
            cb.pack(anchor="w", pady=S(1))
            tip(cb, f"Hast du {name}? Dann gelten die App-Preise und Aktionen dafür\n"
                    "und werden in Plan und Einkaufsliste eingerechnet.")
            self.prog_vars[name] = var
        self._build_size_card(mitte)

        rechts = tk.Frame(f, bg=C["bg"])
        rechts.grid(row=1, column=2, sticky="nsew")
        hc = Card(rechts, pad=16)
        hc.pack(fill="x")
        Section(hc.body, "🏪", "Erlaubte Händler", "Daraus werden die Läden für den Plan gewählt"
                ).pack(fill="x", pady=(0, S(12)))
        self.h_grid = tk.Frame(hc.body, bg=C["surface"])
        self.h_grid.pack(fill="x")
        for c in range(2):
            self.h_grid.columnconfigure(c, weight=1, uniform="haendler")
        # Zwei Spalten nur, wenn beide ganz nebeneinander passen (große Schrift, schmales Fenster)
        self._h_spalten = 2
        self.h_grid.bind("<Configure>", self._haendler_spalten, add="+")
        ui.wrap_label(hc.body, "Nichts angehakt = alle Händler", bg=C["surface"], fg=C["subtext"],
                      font=F["small"]).pack(fill="x", pady=(S(8), 0))
        # Warnung, wenn angehakte Händler diese Woche gar keine Angebote haben (z. B. weil die
        # Angebotsquelle ihren Prospekt gerade nicht führt) – sonst wundert man sich, dass nichts kommt
        self.h_warn = ui.wrap_label(hc.body, "", bg=C["surface"], fg=C["orange"], font=F["small_bold"])
        self._h_warn_text, self._h_zahl, self._h_lage = "", {}, {}
        # Händler ohne Angebote: was bei marktguru los ist und ein Knopf zum letzten Prospekt
        self._h_card, self.p_card, self._p_stand = hc, Card(rechts, pad=16), None

        self._build_update_card(rechts)

        # Jede Änderung speichert nach kurzer Pause von selbst (Händler-Häkchen: siehe _fill_haendler)
        for var in (self.plz_var, self.pers_var, self.laeden_var, self.veg_var, self.abw_var,
                    self.pdfr_var, self.frag_var, self.rf_var, self.mr_var, self.scale_var,
                    self.repo_var, self.uauto_var, *self.prog_vars.values()):
            var.trace_add("write", self._auto_speichern)

    def _build_discount_card(self, parent):
        """Rabatt-Schwelle: Angebote unter dem Mindest-Rabatt fallen aus Liste, Plan und Einkaufsliste."""
        rc = Card(parent, pad=16)
        rc.pack(fill="x")
        r = rc.body
        Section(r, "🏷️", "Rabatt-Filter", "Nur kräftige Angebote berücksichtigen"
                ).pack(fill="x", pady=(0, S(12)))
        self.rf_var = tk.BooleanVar(value=bool(self.cfg.get("rabatt_filter", False)))
        try:
            mr = max(5, min(90, int(self.cfg.get("min_rabatt", 20))))
        except (TypeError, ValueError):
            mr = 20
        self.mr_var = tk.IntVar(value=mr)
        reihe = tk.Frame(r, bg=C["surface"])
        reihe.pack(fill="x")
        cb = ttk.Checkbutton(reihe, text="Nur Angebote ab", variable=self.rf_var,
                             command=self._rabatt_state)
        cb.pack(side="left")
        tip(cb, "Aus: alle Angebote zählen. An: Angebote mit weniger Rabatt fallen aus der\n"
                "Angebotsliste, dem Plan und der Einkaufsliste heraus. Angebote ohne bekannten\n"
                "Vorher-Preis haben keinen Rabatt und fallen dann ebenfalls heraus.")
        self.mr_spin = ttk.Spinbox(reihe, from_=5, to=90, increment=5, textvariable=self.mr_var, width=5)
        self.mr_spin.pack(side="left", padx=(S(8), S(6)))
        tip(self.mr_spin, "Mindest-Rabatt in Prozent (5–90), in Fünferschritten")
        tk.Label(reihe, text="% Rabatt anzeigen", bg=C["surface"], fg=C["text"], font=F["base"]
                 ).pack(side="left")
        ui.wrap_label(r, "Gilt für Angebotsliste, Plan und Einkaufsliste.", bg=C["surface"],
                      fg=C["subtext"], font=F["small"]).pack(fill="x", pady=(S(8), 0))
        self._rabatt_state()

    def _rabatt_state(self):
        self.mr_spin.config(state="normal" if self.rf_var.get() else "disabled")

    def _build_size_card(self, parent):
        """Größe der Oberfläche – auf einem 4K-Schirm ist die Windows-Vorgabe oft zu klein."""
        dc = Card(parent, pad=16)
        dc.pack(fill="x")
        d = dc.body
        Section(d, "🔍", "Größe", "Schrift und Bedienelemente – wirkt nach einem Neustart"
                ).pack(fill="x", pady=(0, S(12)))
        self._scale_start = utils.gewuenschte_skalierung()
        namen = [n for n, _ in GROESSEN]
        self.scale_var = tk.StringVar(
            value=next((n for n, w in GROESSEN if abs(w - self._scale_start) < 0.01), namen[0]))
        self._field_label(d, "Größe der Oberfläche").pack(fill="x")
        cb = ttk.Combobox(d, textvariable=self.scale_var, values=namen, state="readonly", width=22)
        cb.pack(anchor="w", pady=(S(3), S(8)))
        tip(cb, "„Automatisch“ übernimmt die Windows-Skalierung.\n"
                    "Bei 4K mit 100 % ist alles sehr klein – dann hier 150 % oder mehr wählen.")
        ui.wrap_label(d, f"Gerade dargestellt: {round(utils.SCALE * 100)} %"
                         f"{'' if self._scale_start else ' (automatisch erkannt)'}",
                      bg=C["surface"], fg=C["subtext"], font=F["small"]).pack(fill="x")

    def _build_update_card(self, parent):
        """Programm-Update von GitHub und die wichtigen Bibliotheken."""
        uc = Card(parent, pad=16)
        uc.pack(fill="x")
        u = uc.body
        Section(u, "🔄", "Update", "Neue Version von GitHub – nur nach deiner Zustimmung"
                ).pack(fill="x", pady=(0, S(12)))
        self.repo_var = tk.StringVar(value=self.cfg.get("update_repo", ""))
        self.uauto_var = tk.BooleanVar(value=self.cfg.get("update_auto", True))
        self._field_label(u, "GitHub-Projekt").pack(fill="x")
        e = ttk.Entry(u, textvariable=self.repo_var, width=1)
        e.pack(fill="x", pady=(S(3), S(6)))
        tip(e, "Format: benutzer/projekt – eine GitHub-Adresse wird auch erkannt.\n"
                   "Leer lassen, wenn du keine Updates über GitHub beziehen willst.")
        cb = ttk.Checkbutton(u, text="Beim Start still nach Updates sehen", variable=self.uauto_var)
        cb.pack(anchor="w")
        tip(cb, "Fragt einmal beim Programmstart bei GitHub nach und meldet sich nur,\n"
                    "wenn es wirklich eine neuere Version gibt.")

        reihe = tk.Frame(u, bg=C["surface"])
        reihe.pack(fill="x", pady=(S(12), 0))
        self.up_btn = Btn(reihe, "Nach Updates suchen", self.check_update, icon="🔄",
                          tip="Fragt bei GitHub nach der neuesten Version")
        self.up_btn.pack(side="left")
        self.lib_btn = Btn(reihe, "Bibliotheken prüfen", self.check_libs, kind="light", icon="📦",
                           tip="Vergleicht die wichtigen Bibliotheken mit den neuesten Ausgaben")
        self.lib_btn.pack(side="left", padx=(S(8), 0))

        py = up.python_info()
        ui.wrap_label(u, f"Installiert: v{APP_VERSION}  ·  Python {py['version']}  ·  "
                         f"{'fertige EXE' if up.frozen() else 'Quelltext'}",
                      bg=C["surface"], fg=C["subtext"], font=F["small"]).pack(fill="x", pady=(S(10), 0))
        self.up_lbl = ui.wrap_label(u, "", bg=C["surface"], fg=C["text"], font=F["small_bold"])
        self.up_lbl.pack(fill="x", pady=(S(2), 0))
        self.up_prog = ttk.Progressbar(u, mode="determinate", maximum=100)

    def _up_status(self, text, laden=None):
        """Zeile in der Update-Karte. laden = Prozent, None blendet den Balken aus."""
        self.up_lbl.config(text=text)
        if laden is None:
            self.up_prog.pack_forget()
        else:
            self.up_prog.pack(fill="x", pady=(S(6), 0))
            self.up_prog.config(value=laden)

    def _haendler_stand(self):
        """[(Beschriftung, Lebensmittel-Angebote, alle Angebote)] für die Händler-Häkchen: alle Ketten,
        dazu gescannte Händler mit mindestens 10 Angeboten und alte Einstellungen ohne passende Kette."""
        zaehler, alle = {}, {}
        for o in self.week.get("offers", []):
            h = o["haendler"]
            alle[h] = alle.get(h, 0) + 1
            if off.is_food(o):
                zaehler[h] = zaehler.get(h, 0) + 1
        ketten = [(c, pl.erlaubt((c,))) for c in off.HAENDLER]
        extra = {n for n, z in zaehler.items() if z >= 10}
        extra |= set(self.cfg.get("haendler", []))
        extra = sorted(n for n in extra if not any(ok(n) for _, ok in ketten))
        stand = []
        for label in [c for c, _ in ketten] + extra:
            ok = pl.erlaubt((label,))
            stand.append((label, sum(z for n, z in zaehler.items() if ok(n)),
                          sum(z for n, z in alle.items() if ok(n))))
        return stand

    def _fill_haendler(self):
        """Händler-Häkchen anlegen oder – wenn sich die Auswahl nicht geändert hat – nur die Zahlen
        aktualisieren (läuft bei jedem Refresh)."""
        stand = self._haendler_stand()
        labels = [l for l, _, _ in stand]
        if labels != list(self.h_vars):
            alt = {l: v.get() for l, v in self.h_vars.items()}
            sel = self.cfg.get("haendler", [])
            for w in self.h_btns.values():
                w.destroy()
            self.h_vars, self.h_btns = {}, {}
            for i, label in enumerate(labels):
                ok = pl.erlaubt((label,))
                var = tk.BooleanVar(value=alt[label] if label in alt else any(ok(x) for x in sel))
                var.trace_add("write", lambda *_: self._haendler_warnung())
                var.trace_add("write", self._auto_speichern)
                btn = ttk.Checkbutton(self.h_grid, variable=var)
                tip(btn, f"{label}: nur Angebote dieses Händlers für den Plan berücksichtigen.\n"
                         "Nichts angehakt = alle Händler.")
                btn._text = None
                self.h_vars[label], self.h_btns[label] = var, btn
            self._haendler_raster()
        geladen = bool(self.week.get("offers"))
        self._h_lage = self._prospekt_lagen(stand) if geladen else {}
        for label, n, n_alle in stand:
            btn = self.h_btns[label]
            if n:
                text = f"{label}  ·  {n} Angebote"
            elif n_alle:
                text = f"{label}  ·  {n_alle} Drogerie u. a."
            elif geladen:
                art = self._h_lage.get(label, (None, None))[0]
                text = f"{label}  ·  {self._LAGE_KURZ.get(art, 'keine Angebote')}"
            else:
                text = label
            if text != btn._text:
                btn._text = text
                btn.config(text=text, style="Leer.TCheckbutton" if geladen and not n_alle else "TCheckbutton")
        self._h_zahl = {label: n_alle for label, _, n_alle in stand}
        self._haendler_spalten()
        self._haendler_warnung()

    # Kurzform hinter dem Händler-Häkchen, wenn er diese Woche keine Angebote hat (off.prospekt_lage)
    _LAGE_KURZ = {"fehlt": "kein Prospekt", "da": "Prospekt ohne Angebote", "bald": "Prospekt kommt noch"}

    def _prospekt_lagen(self, stand):
        """{Kette: (art, prospekt)} für Ketten ohne ein einziges Angebot in dieser Woche – nur, wenn der
        letzte Scan die Prospekte der Kette bei marktguru nachsehen konnte."""
        ketten = off.prospekte().get("ketten") or {}
        return {label: off.prospekt_lage(ketten[label], self.year, self.kw)
                for label, _, n_alle in stand if not n_alle and label in ketten}

    @staticmethod
    def _zeitraum(p):
        """„05.10. – 07.10.“; liegt der Prospekt nicht in diesem Jahr, mit Jahreszahl."""
        jahr = dt.date.today().year
        tage = [dt.date.fromisoformat(p[k]) for k in ("von", "bis")]
        return " – ".join(d.strftime("%d.%m.") + ("" if d.year == jahr else str(d.year)) for d in tage)

    def _lage_text(self, art, p):
        letzter = f"\nLetzter Prospekt: {self._zeitraum(p)}" if p else ""
        if art == "da":
            return (f"Es gibt einen Prospekt ({self._zeitraum(p)}), aber marktguru hat die Angebote daraus "
                    "nicht einzeln erfasst. Essens-Plan kann ihn darum nicht nutzen – schau selbst hinein.")
        if art == "bald":
            return "Der Prospekt für diese Woche ist noch nicht da (meist ab dem Sonntag davor)." + letzter
        if p and (dt.date.today() - dt.date.fromisoformat(p["bis"])).days > 90:
            return ("Bei marktguru gibt es schon lange keine Prospekte mehr von diesem Händler."
                    f" Der letzte war vom {self._zeitraum(p)}.")
        return "Laut marktguru gibt es gerade keinen aktuellen Prospekt." + letzter

    def _prospekt_karte(self):
        """Karte unter den Händlern: je Händler ohne Angebote, was bei marktguru los ist, dazu ein Knopf
        zum (letzten) Prospekt. Neu gebaut wird sie nur, wenn sich daran etwas geändert hat."""
        an = {l for l, v in self.h_vars.items() if v.get()}
        zeilen = [(l, art, p) for l, (art, p) in self._h_lage.items() if art in self._LAGE_KURZ]
        zeilen.sort(key=lambda z: z[0] not in an)        # angehakte Händler zuerst
        stand = [(l, art, p and p.get("id")) for l, art, p in zeilen]
        if stand == self._p_stand:
            return
        self._p_stand = stand
        b = self.p_card.body
        for w in b.winfo_children():
            w.destroy()
        if not zeilen:
            self.p_card.pack_forget()
            return
        Section(b, "📄", "Kein aktueller Prospekt", "Diese Händler haben in dieser Woche keine Angebote"
                ).pack(fill="x", pady=(0, S(8)))
        if any(art == "fehlt" for _, art, _ in zeilen):
            ui.wrap_label(b, "Essens-Plan bekommt die Angebote von marktguru.de. Fehlt dort ein Prospekt, kann "
                             "das an marktguru liegen (dort fehlen manchmal Prospekte) oder der Händler hat "
                             "keinen veröffentlicht. Den letzten Prospekt kannst du dir trotzdem ansehen – "
                             "seine Preise gelten aber meist nicht mehr.",
                          bg=C["surface"], fg=C["subtext"], font=F["small"]).pack(fill="x")
        for label, art, p in zeilen:
            z = tk.Frame(b, bg=C["surface"])
            z.pack(fill="x", pady=(S(12), 0))
            tk.Label(z, text=label, bg=C["surface"], fg=C["text"], font=F["bold"], anchor="w").pack(fill="x")
            ui.wrap_label(z, self._lage_text(art, p), bg=C["surface"], fg=C["text"], font=F["base"]
                          ).pack(fill="x")
            if p:
                url = off.prospekt_url(p)
                Btn(z, "Prospekt ansehen" if art == "da" else "Letzten Prospekt ansehen",
                    lambda u=url: webbrowser.open(u), kind="light", icon="📄", padx=10, pady=5,
                    tip=f"Öffnet den Prospekt von {label} bei marktguru.de im Browser"
                    ).pack(anchor="w", pady=(S(4), 0))
        self.p_card.pack(fill="x", after=self._h_card)

    def _haendler_raster(self):
        n = self._h_spalten
        for i, btn in enumerate(self.h_btns.values()):
            btn.grid(row=i // n, column=i % n, columnspan=1 if n == 2 else 2, sticky="w", pady=S(1))

    def _haendler_spalten(self, _=None):
        """Eine Spalte, wenn die längste Beschriftung („… · keine Angebote“) nicht zweimal nebeneinander
        passt – sonst würde sie rechts abgeschnitten."""
        if not self.h_btns:
            return
        breit = self.h_grid.winfo_width()
        if breit <= 1:
            return
        n = 2 if breit >= 2 * (max(b.winfo_reqwidth() for b in self.h_btns.values()) + S(8)) else 1
        if n != self._h_spalten:
            self._h_spalten = n
            self._haendler_raster()

    def _haendler_warnung(self):
        """Zeile unter den Händler-Häkchen: angehakte Händler ohne ein einziges Angebot diese Woche."""
        self._prospekt_karte()
        text = ""
        if self.week.get("offers"):
            an = [l for l, v in self.h_vars.items() if v.get()]
            leer = [l for l in an if not self._h_zahl.get(l)]
            namen = ", ".join(leer)
            hat = "hat" if len(leer) == 1 else "haben"
            unten = (" Mehr dazu unten." if any(self._h_lage.get(l, (None,))[0] in self._LAGE_KURZ for l in leer)
                     else "")
            if an and len(leer) == len(an):
                text = (f"⚠️ {namen} {hat} diese Woche keine Angebote bei marktguru, der Angebotsquelle. "
                        "So findet Essens-Plan nichts. Bitte weitere Händler anhaken oder alle Haken entfernen "
                        "(= alle Händler)." + unten)
            elif leer:
                text = f"ℹ️ {namen} {hat} diese Woche keine Angebote bei marktguru." + unten
        if text == self._h_warn_text:
            return
        self._h_warn_text = text
        if text:
            self.h_warn.config(text=text, fg=C["orange"] if text.startswith("⚠️") else C["subtext"])
            self.h_warn.pack(fill="x", pady=(S(8), 0), after=self.h_grid)
        else:
            self.h_warn.pack_forget()

    def _auto_abbrechen(self):
        """Wartenden Timer des automatischen Speicherns abbrechen."""
        if self._auto_id is not None:
            try:
                self.after_cancel(self._auto_id)
            except tk.TclError:
                pass
            self._auto_id = None

    def _auto_speichern(self, *_):
        """Eine Einstellung wurde geändert: 0,8 s nach der letzten Änderung automatisch speichern."""
        if self._auto_aus or self._schluss:
            return
        self._auto_abbrechen()
        self._auto_id = self.after(800, self._auto_flush)

    def _auto_flush(self):
        """Automatisches Speichern jetzt ausführen (Timer abgelaufen oder Fenster schließt)."""
        self._auto_abbrechen()
        self.save_settings(still=True)

    def save_all(self):
        """Knopf „Speichern“ oben: Einstellungen und Woche sofort sichern (sonst automatisch)."""
        self._auto_abbrechen()
        self._save_flush()
        self.save_settings()

    def save_settings(self, still=False):
        """Speichert alle Einstellungen. True bei Erfolg.
        still=True: automatisches Speichern nach einer Änderung – keine Meldungsfenster, halb
        eingetippte Felder behalten ihren alten gespeicherten Wert, die Felder selbst bleiben unberührt."""
        plz = self.plz_var.get().strip()
        if still:
            if not (plz.isdigit() and len(plz) == 5):
                if plz:
                    self.plz_hint.config(fg=C["orange"],
                                         text="Noch nicht übernommen – die Postleitzahl braucht 5 Ziffern")
                else:
                    self.plz_hint.config(fg=C["subtext"], text=PLZ_HINT)
                plz = self.cfg.get("plz", "")
            else:
                self.plz_hint.config(fg=C["subtext"], text=PLZ_HINT)
        elif plz and not (plz.isdigit() and len(plz) == 5):
            messagebox.showerror("Fehler", "Bitte eine gültige 5-stellige PLZ eingeben.", parent=self)
            return False
        if still:
            try:
                personen = int(self.pers_var.get())
            except (tk.TclError, ValueError):
                personen = self.cfg.get("personen", 2)
            try:
                laeden = int(self.laeden_var.get())
            except (tk.TclError, ValueError):
                laeden = self.cfg.get("max_laeden", 2)
            try:
                min_rabatt = int(self.mr_var.get())
                if not 5 <= min_rabatt <= 90:
                    raise ValueError
            except (tk.TclError, ValueError):
                min_rabatt = self.cfg.get("min_rabatt", 20)
        else:
            try:
                personen, laeden = int(self.pers_var.get() or 2), int(self.laeden_var.get() or 0)
            except (tk.TclError, ValueError):
                messagebox.showerror("Fehler", "Personen und Läden bitte als Zahl eingeben.", parent=self)
                return False
            try:
                min_rabatt = max(5, min(90, int(self.mr_var.get())))
            except (tk.TclError, ValueError):
                min_rabatt = 20
            self._var_setzen(self.mr_var, min_rabatt)
        repo = self.repo_var.get().strip()
        if repo and not up.repo_name(repo):
            if not still:
                messagebox.showerror("Fehler", "Das GitHub-Projekt muss „benutzer/projekt“ lauten "
                                               "(oder eine GitHub-Adresse sein).", parent=self)
                return False
            repo = self.cfg.get("update_repo", "")
        groesse = dict(GROESSEN).get(self.scale_var.get(), 0.0)
        vorher = dict(self.cfg)
        self.cfg.update(plz=plz, personen=personen, ui_scale=groesse,
                        vegetarisch=self.veg_var.get(), max_laeden=laeden,
                        update_repo=up.repo_name(repo), update_auto=self.uauto_var.get(),
                        abwechslung=self.abw_var.get(), pdf_rezepte=self.pdfr_var.get(),
                        artikel_fragen=self.frag_var.get(),
                        rabatt_filter=self.rf_var.get(), min_rabatt=min_rabatt,
                        programme=[n for n, v in self.prog_vars.items() if v.get()],
                        haendler=[l for l, v in self.h_vars.items() if v.get()])
        if still and self.cfg == vorher:
            return True                         # nichts geändert: nichts schreiben, nichts auffrischen
        if not self._save_cfg(still):
            return False
        if self._schluss:
            return True                         # Fenster schließt: nur sichern
        if not still:
            self._var_setzen(self.repo_var, self.cfg["update_repo"])
            self.plz_hint.config(fg=C["subtext"], text=PLZ_HINT)
            if plz:
                self.welcome.grid_remove()
        self._index_food()
        self._refresh()
        self.set_status("✔ Einstellungen automatisch gespeichert" if still else "Einstellungen gespeichert")
        if abs(groesse - self._scale_start) > 0.01:
            self._scale_start = groesse
            if messagebox.askyesno("Größe geändert",
                                   "Die neue Größe gilt ab dem nächsten Start.\n\nJetzt neu starten?",
                                   parent=self):
                self._neustart()
        return True

    def _var_setzen(self, var, wert):
        """Feld zurückschreiben, ohne dass das ein neues automatisches Speichern auslöst."""
        try:
            if var.get() == wert:
                return
        except tk.TclError:
            pass                                # Feld leer/kaputt: auf jeden Fall zurückschreiben
        self._auto_aus = True
        try:
            var.set(wert)
        finally:
            self._auto_aus = False

    def first_start(self):
        """Ersteinrichtung: PLZ prüfen, speichern, Angebote laden."""
        plz = self.plz_var.get().strip()
        if not (plz.isdigit() and len(plz) == 5):
            self.set_status("Bitte zuerst die Postleitzahl eintragen (5 Ziffern)")
            self.plz_hint.config(fg=C["red"], text="Bitte eine gültige 5-stellige Postleitzahl eintragen, z. B. 10115")
            self.plz_entry.focus_set()
            return
        self.plz_hint.config(fg=C["subtext"], text=PLZ_HINT)
        if not self.save_settings() or self._schluss:
            return
        self.welcome.grid_remove()
        self._erst_scan = True
        self.tabs.select(T_ANGEBOTE)
        self.scan()

    def _save_cfg(self, still=False):
        """Einstellungen sichern. False (mit Meldung), wenn der Datenordner nicht beschreibbar ist.
        still=True: nur in die Statuszeile statt in ein Meldungsfenster."""
        try:
            save_json(CONFIG_FILE, self.cfg)
            return True
        except OSError as e:
            if still:
                self.set_status(f"Einstellungen konnten nicht gespeichert werden: {e}")
                return False
            messagebox.showerror("Speichern fehlgeschlagen",
                                 f"Die Einstellungen konnten nicht gespeichert werden:\n\n{e}",
                                 parent=self)
            return False

    def _spaeter(self, fn, *args):
        """Aus einem Hintergrund-Thread etwas im Oberflächen-Thread ausführen lassen. Ist das
        Fenster inzwischen geschlossen, gibt es nichts mehr zu melden – der Thread soll dann
        still enden statt mit einer Fehlermeldung."""
        try:
            self.after(0, lambda: fn(*args))
        except (tk.TclError, RuntimeError):
            pass

    # ── Update ────────────────────────────────────────────────────────────────
    def check_update(self, still=False):
        """Fragt im Hintergrund bei GitHub nach. still=True meldet sich nur bei Neuigkeiten."""
        if self._up_busy:
            return
        repo = self.repo_var.get().strip() or self.cfg.get("update_repo", "")
        if not up.repo_name(repo):
            if still:
                return
            self.tabs.select(T_EINST)
            return messagebox.showinfo(
                "Update", "Dafür fehlt noch das GitHub-Projekt.\n\n"
                          "Trage es unten in der Karte „Update“ ein (z. B. benutzer/essens-plan) "
                          "(wird automatisch gespeichert).", parent=self)
        self._up_busy = True
        self.up_btn.set_enabled(False)
        self._up_status("Frage bei GitHub nach …")

        def run():
            try:
                info = up.check(repo, APP_VERSION)
            except Exception as e:
                return self._spaeter(self._update_geprueft, None, str(e), still)
            self._spaeter(self._update_geprueft, info, None, still)
        threading.Thread(target=run, daemon=True).start()

    def _update_geprueft(self, info, fehler, still):
        self._up_busy = False
        self.up_btn.set_enabled(True)
        if fehler:
            self._up_status(f"Keine Auskunft: {fehler}")
            if not still:
                messagebox.showerror("Update", fehler, parent=self)
            return
        if not info["neu"]:
            self._up_status(f"Alles aktuell – auf GitHub liegt v{info['version']}.")
            if not still:
                messagebox.showinfo("Update", f"Du hast schon die neueste Version (v{APP_VERSION}).",
                                    parent=self)
            return

        self._up_status(f"Neue Version v{info['version']} verfügbar.")
        self.set_status(f"Update v{info['version']} verfügbar")
        notiz = info["notizen"][:700].strip()
        if len(info["notizen"]) > 700:
            notiz += " …"
        kopf = f"Neue Version v{info['version']} verfügbar – du hast v{APP_VERSION}.\n\n"
        if notiz:
            kopf += notiz + "\n\n"
        if up.frozen() and info["asset"]:
            mb = info["asset"]["size"] / 1048576
            if messagebox.askyesno("Update", kopf + f"{info['asset']['name']} ({mb:.1f} MB) jetzt laden "
                                                    "und einspielen?\nDas Programm startet dabei neu.",
                                   parent=self):
                self._update_laden(info)
        elif messagebox.askyesno("Update", kopf + "Die Seite mit der neuen Version im Browser öffnen?",
                                 parent=self):
            webbrowser.open(info["seite"])

    def _update_laden(self, info):
        ordner = tempfile.mkdtemp(prefix="Essens-Plan-Update-")
        ziel = os.path.join(ordner, info["asset"]["name"])
        self._up_busy = True
        self.up_btn.set_enabled(False)
        self._up_status("Lade …", laden=0)

        def prog(geladen, gesamt):
            p = 100 * geladen / max(gesamt, 1)
            self._spaeter(lambda: self._up_status(
                f"Lade … {geladen / 1048576:.1f} von {gesamt / 1048576:.1f} MB", laden=p))

        def run():
            try:
                up.download(info["asset"], ziel, prog)
            except Exception as e:
                return self._spaeter(self._update_fertig, info, ziel, str(e))
            self._spaeter(self._update_fertig, info, ziel, None)
        threading.Thread(target=run, daemon=True).start()

    def _update_fertig(self, info, ziel, fehler):
        self._up_busy = False
        self.up_btn.set_enabled(True)
        if fehler:
            shutil.rmtree(os.path.dirname(ziel), ignore_errors=True)   # leeren Temp-Ordner nicht liegen lassen
            self._up_status(f"Download fehlgeschlagen: {fehler}")
            return messagebox.showerror("Update", fehler, parent=self)
        self._up_status(f"v{info['version']} geladen – bereit zum Einspielen.")
        if not messagebox.askyesno("Update",
                                   f"v{info['version']} ist geladen.\n\n"
                                   "Das Programm wird jetzt beendet, die neue Fassung eingesetzt "
                                   "und wieder gestartet. Fortfahren?", parent=self):
            return messagebox.showinfo("Update", f"Gut – die neue Fassung liegt hier:\n\n{ziel}",
                                       parent=self)
        try:
            up.tausche_und_starte(ziel)
        except OSError as e:
            return messagebox.showerror("Update", "Das Einspielen ließ sich nicht starten:\n\n"
                                        f"{e}\n\nDie neue Fassung liegt hier:\n\n{ziel}", parent=self)
        self.destroy()          # das Hilfsskript wartet genau darauf

    def check_libs(self):
        """Vergleicht die wichtigen Bibliotheken mit PyPI (nur im Quelltext-Betrieb sinnvoll)."""
        if self._up_busy:
            return
        if up.frozen():
            return messagebox.showinfo(
                "Bibliotheken",
                "Diese Fassung läuft als fertige EXE: Python und alle Bibliotheken stecken fest "
                "darin, ein pip gibt es hier nicht.\n\nSie werden zusammen mit einer neuen EXE "
                "aktualisiert – dafür ist „Nach Updates suchen“ da.", parent=self)
        self._up_busy = True
        self.lib_btn.set_enabled(False)
        self._up_status("Vergleiche mit PyPI …", laden=0)

        def run():
            try:
                stand = up.lib_status(lambda i, n: self._spaeter(lambda: self._up_status(
                    f"Vergleiche mit PyPI … {i}/{n}", laden=100 * i / n)))
            except Exception as e:
                return self._spaeter(self._libs_geprueft, None, str(e))
            self._spaeter(self._libs_geprueft, stand, None)
        threading.Thread(target=run, daemon=True).start()

    def _libs_geprueft(self, stand, fehler):
        self._up_busy = False
        self.lib_btn.set_enabled(True)
        if fehler:
            self._up_status(f"Vergleich fehlgeschlagen: {fehler}")
            return messagebox.showerror("Bibliotheken", fehler, parent=self)
        alt = [d["name"] for d in stand if d["veraltet"]]
        zeilen = "\n".join(f"{d['name']:<12} {d['da'] or '–'}"
                           + (f"   →  {d['neu']}" if d["veraltet"] else "   (aktuell)")
                           for d in stand)
        py = up.python_info()
        zeilen += f"\n\nPython       {py['version']}" + ("   (veraltet)" if py["alt"] else "   (aktuell)")
        self._up_status(("Veraltet: " + ", ".join(alt)) if alt else "Alle Bibliotheken sind aktuell.")
        if not alt:
            if py["alt"] and messagebox.askyesno(
                    "Bibliotheken", zeilen + f"\n\nPython {py['mindest']} oder neuer wird empfohlen. "
                                             "Die Download-Seite öffnen?", parent=self):
                webbrowser.open(py["url"])
            elif not py["alt"]:
                messagebox.showinfo("Bibliotheken", zeilen + "\n\nAlles auf dem neuesten Stand.",
                                    parent=self)
            return
        if messagebox.askyesno("Bibliotheken", zeilen + "\n\nDie veralteten jetzt aktualisieren?\n"
                                                        "(pip install --upgrade "
                               + " ".join(alt) + ")", parent=self):
            self._libs_aktualisieren(alt)

    def _libs_aktualisieren(self, namen):
        self._up_busy = True
        self.lib_btn.set_enabled(False)
        self._up_status("Aktualisiere " + ", ".join(namen) + " …", laden=0)
        self.up_prog.config(mode="indeterminate")
        self.up_prog.start(12)

        def run():
            ok, ausgabe = up.pip_upgrade(namen)
            self._spaeter(self._libs_fertig, ok, ausgabe)
        threading.Thread(target=run, daemon=True).start()

    def _libs_fertig(self, ok, ausgabe):
        self._up_busy = False
        self.lib_btn.set_enabled(True)
        self.up_prog.stop()
        self.up_prog.config(mode="determinate")
        self._up_status("Bibliotheken aktualisiert – bitte neu starten." if ok
                        else "Aktualisierung fehlgeschlagen.")
        if ok:
            messagebox.showinfo("Bibliotheken", "Fertig:\n\n" + ausgabe
                                + "\n\nStarte das Programm neu, damit die neuen Fassungen greifen.",
                                parent=self)
        else:
            messagebox.showerror("Bibliotheken", ausgabe, parent=self)

    # ── Woche / Daten ─────────────────────────────────────────────────────────
    def shift_week(self, delta):
        d = self._monday() + dt.timedelta(days=7 * delta)
        self.year, self.kw = d.isocalendar()[:2]
        self._load_week()

    def today_week(self):
        self.year, self.kw = planwoche()
        self._load_week()

    def _load_week(self, scan=False):
        p, liste = self._save_pending, None
        if p and scan and (p[0], p[1]) == (self.year, self.kw):
            liste = self.week.get("liste")       # während des Scans geändert: Haken/Extras behalten
        else:
            self._save_flush()
        self.week = off.load_week(self.year, self.kw)
        if liste is not None:
            self.week["liste"] = liste
            self._save_pending = (self.year, self.kw, self.week)
        self.week_lbl.config(text=off.week_label(self.year, self.kw))
        pl.rate_prices(self.week.get("offers", []))
        self._index_food()
        self._refresh()

    def _index_food(self):
        """Lebensmittel-Angebote für Plan und Einkaufsliste vorbereiten. Bei aktivem Rabatt-Filter
        (Einstellungen) kommen nur Angebote ab dem Mindest-Rabatt hinein."""
        offers = self.week.get("offers", [])
        mn = self._min_rabatt()
        if mn is not None:
            cfg, rabatt = self.cfg, pl.rabatt
            keep = []
            for o in offers:
                r = rabatt(o, cfg)
                if r is not None and r >= mn:
                    keep.append(o)
            offers = keep
        self.food = pl.index_offers(offers, self.recipes)

    def _refresh(self):
        self._fill_haendler()
        self._fill_offers()
        self._fill_plan()
        self._fill_list()
        self.dish_tab.daten_geaendert()
        self.such_tab.daten_geaendert()

    def _save_and_refresh(self):
        self._save_pending = None           # save_week schreibt unten ohnehin die ganze Woche
        try:
            off.save_week(self.year, self.kw, self.week)
        except OSError as e:
            messagebox.showerror("Speichern fehlgeschlagen",
                                 f"Der Plan konnte nicht gespeichert werden:\n\n{e}", parent=self)
        self._fill_plan()
        self._fill_list()
        self.dish_tab.daten_geaendert()     # „zuletzt geplant“ in der Detailansicht

    def _tab_gewechselt(self, i):
        if i == T_GERICHTE:
            self.dish_tab.tab_gewaehlt()
        elif i == T_SUCHE:
            self.such_tab.tab_gewaehlt()

    def scan(self):
        if self._busy:
            return
        if not self.cfg.get("plz"):
            return self._zu_einstellungen("Bitte zuerst die Postleitzahl eintragen")
        self._save_flush()                  # offene Änderungen sichern, bevor der Scan die Datei neu schreibt
        self._busy = True
        self.btn_scan.set_enabled(False)
        self.dot.itemconfigure("dot", fill=C["orange"])
        self.progress.config(value=0)
        self.progress.pack(side="right", padx=(S(8), S(16)))
        self.scan_lbl.pack(side="right")
        self.set_status(f"Lade alle Angebote aller Händler (PLZ {self.cfg['plz']})…")
        if not self.week.get("offers"):
            self._fill_offers()             # leere Liste: „Angebote werden geladen“ statt „keine Angebote“
            self._plan_leer()
            self._li_leer()
            self.such_tab.daten_geaendert()

        def prog(done, total):
            self._spaeter(lambda: (self.progress.config(maximum=total, value=done),
                                   self.scan_lbl.config(text=f"Seite {done}/{total}")))

        def run():
            try:
                res = off.scan(self.cfg["plz"], prog)
            except Exception as e:
                # Den Text sofort festhalten: „e“ gibt es nach dem except-Block nicht mehr, ein
                # später ausgeführtes lambda fände es nicht – der Scan-Knopf bliebe für immer grau.
                return self._spaeter(self._scan_done, 0, [str(e) or type(e).__name__])
            self._spaeter(self._scan_done, *res)
        threading.Thread(target=run, daemon=True).start()

    def _scan_done(self, count, errors):
        self._busy = False
        self.btn_scan.set_enabled(True)
        self.progress.pack_forget()
        self.scan_lbl.pack_forget()
        self.scan_lbl.config(text="")
        self.dot.itemconfigure("dot", fill=C["red"] if errors else C["green"])
        self._load_week(scan=True)
        n = len(self.week.get("offers", []))
        msg = f"{count} Angebote gefunden, {n} gültig in {off.week_label(self.year, self.kw)}"
        if errors:
            msg += f"  ·  {len(errors)} Fehler"
            if not count:
                messagebox.showerror("Scan fehlgeschlagen", "\n".join(errors[:8]), parent=self)
        elif not n:
            messagebox.showinfo("Keine Angebote", "Für diese Woche wurden (noch) keine Angebote "
                                "veröffentlicht. Prospekte erscheinen meist ab Sonntag davor.",
                                parent=self)
        if self._erst_scan and n and not errors:
            msg += "  ·  Jetzt Plan generieren (F6)"
        self._erst_scan = False
        self.set_status(msg)

    # ── Export / Sonstiges ────────────────────────────────────────────────────
    def export_pdf(self):
        plan = self._plan_aktiv()
        if not plan:
            self.tabs.select(T_PLAN)
            return self.set_status("Noch kein Plan für diese Woche – zuerst „Plan generieren“ (F6)")
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"Essensplan_{self.year}_KW{self.kw:02d}.pdf")
        if not path:
            return
        try:
            import pdf_export
            pdf_export.export(path, off.week_label(self.year, self.kw), self._monday(),
                              plan, self.recipes, self.food, self._pcfg(),
                              [e["ref"] for e in self._li_alle if e["k"] == "i" and self._an(e)],
                              tage=self._tage(),
                              extras=[e["ref"] for e in self._li_alle if e["k"] == "e" and self._an(e)])
        except PermissionError:
            return messagebox.showerror("Fehler", "PDF ist noch geöffnet – bitte schließen.",
                                        parent=self)
        except Exception as e:
            return messagebox.showerror("PDF-Fehler", str(e), parent=self)
        self.set_status(f"PDF gespeichert: {path}")
        try:
            utils.oeffne_datei(path)
        except OSError:
            pass                # kein PDF-Programm eingerichtet – gespeichert ist die Datei trotzdem

    # ── Gerichte ──────────────────────────────────────────────────────────────
    def recipes_changed(self, select=None):
        """Nach Änderungen an den Gerichten: Auswahllisten, Plan und Einkaufsliste angleichen."""
        self.recipes = self.store.all()
        names = self.store.names()
        for row in self.day_rows:
            row["cb"].config(values=names)
        self._index_food()
        self.dish_tab.refresh(select)
        self._fill_plan()
        self._fill_list()

    def plan_dish(self, i, name):
        """Gericht aus dem Tab „Gerichte“ auf einen Wochentag legen."""
        self.week.setdefault("plan", {})[self._day_key(i)] = name
        self.tabs.select(T_PLAN)        # erst wechseln: die Gerichte-Ansicht baut sich dann später neu
        self._save_and_refresh()
        self.set_status(f"„{name}“ für {pl.TAGE[i]} eingeplant")

    def show_dish(self, i):
        name = self.day_rows[i]["var"].get()
        if name:
            self.dish_tab.select(name)      # erst wählen, dann wechseln: so baut sich die
            self.tabs.select(T_GERICHTE)    # Detailansicht nur einmal auf

    def reload_recipes(self):
        self.store.reload()
        self.recipes_changed()
        self.set_status(f"{len(self.recipes)} Gerichte geladen")

    def open_data_dir(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            utils.oeffne_datei(DATA_DIR)
        except OSError as e:
            messagebox.showerror("Datenordner", f"Der Ordner lässt sich nicht öffnen:\n\n{DATA_DIR}\n\n{e}",
                                 parent=self)

    # ── Hilfe ─────────────────────────────────────────────────────────────────
    def show_help(self):
        messagebox.showinfo("Kurzanleitung",
                            "ERSTE EINRICHTUNG\n"
                            "1.  Tab „Einstellungen“: Postleitzahl eintragen (Pflicht), Personen und "
                            "Händler wählen. Nichts angehakt = alle Händler.\n"
                            "2.  „Speichern & Angebote laden“ holt die Prospekte (F5 lädt später neu).\n"
                            "3.  „Plan generieren“ (F6) sucht Gerichte, deren Zutaten im Angebot sind.\n\n"
                            "WOCHENPLAN\n"
                            "•  „Neu“ oder die Auswahlliste ändert einen Tag.\n"
                            "•  Das ✕ an der Tageskarte nimmt einen Tag aus dem Plan, „Tag hinzufügen“ "
                            "holt ihn zurück.\n\n"
                            "EINKAUFSLISTE\n"
                            "•  Häkchen = kommt auf die Liste, ohne Häkchen = habe ich schon (zählt nicht "
                            "zur Summe). Umschalten per Klick auf das Kästchen oder Leertaste.\n"
                            "•  „Artikel hinzufügen“: Sorte oder Marke eintippen (z. B. Duschgel, Deo, Axe) – "
                            "erst werden Angebote deiner Händler gesucht, sonst kommt der Artikel ohne Preis "
                            "auf die Liste. „Notiz hinzufügen“ für freien Text.\n"
                            "•  „Kopieren“ für WhatsApp & Co., „PDF drucken“ (Strg+P) für den Ausdruck.\n\n"
                            "ANGEBOT RAUSSUCHEN\n"
                            "•  Eigener Reiter: Sorte oder Marke eintippen (Duschgel, Deo, Axe …) – zeigt "
                            "alle passenden Angebote und darunter ähnliche Produkte, die gerade stark "
                            "reduziert sind. Auswählen und „Auf die Einkaufsliste“ drücken.\n"
                            "•  Gibt es nichts im Angebot, kannst du den Artikel trotzdem ohne Preis "
                            "aufschreiben.\n\n"
                            "RABATT-FILTER\n"
                            "Einstellungen → „Nur Angebote ab … % Rabatt“ zeigt nur starke Angebote – "
                            "in Angebotsliste, Plan und Einkaufsliste.\n\n"
                            "Tipp: Maus kurz über einen Knopf halten, dann erscheint eine Erklärung. "
                            "Die ausführliche Anleitung steht in der Datei „Anleitung.pdf“ neben dem Programm.",
                            parent=self)

    def show_keys(self):
        messagebox.showinfo("Tastenkürzel",
                            "F5\t\tAngebote scannen\n"
                            "F6\t\tWoche generieren\n"
                            "Strg+P\t\tPDF exportieren\n"
                            "Strg+←/→\tWoche zurück/vor\n"
                            f"Strg+1…{len(TABS)}\tTab wechseln\n"
                            "Leertaste\tHaken in der Einkaufsliste umschalten\n"
                            "Entf\t\tExtra oder Notiz entfernen", parent=self)

    def show_about(self):
        eigene = sum(1 for r in self.recipes if r.get("_art") != "basis")
        messagebox.showinfo("Über",
                            f"{APP_NAME}  v{APP_VERSION}\n\n"
                            f"{len(self.recipes)} Gerichte, davon {eigene} eigene oder geändert\n"
                            f"Daten: {DATA_DIR}\n\n"
                            "Angebotsdaten: marktguru.de\n"
                            "(Aldi, Lidl, Rewe, Edeka, Kaufland, Penny, Netto, …)", parent=self)

    def toggle_theme(self):
        if not self._neustart_ok():
            return
        alt = self.cfg.get("ui_theme")
        self.cfg["ui_theme"] = "light" if utils.ACTIVE_THEME == "dark" else "dark"
        if not self._save_cfg():
            self.cfg["ui_theme"] = alt          # sonst käme das Programm im alten Design zurück
            return
        self._neustart(gefragt=True)

    def _neustart_ok(self):
        """Ein offener Gerichte-Editor ginge beim Neustart verloren – vorher fragen."""
        if not self.dish_tab.editing:
            return True
        return messagebox.askyesno("Neu starten", "Du bearbeitest gerade ein Gericht – ungespeicherte "
                                   "Änderungen gehen beim Neustart verloren.\n\nTrotzdem neu starten?",
                                   parent=self)

    def _neustart(self, gefragt=False):
        """Neu starten – Design und Größe stehen beim Start fest und lassen sich nicht umschalten."""
        if not gefragt and not self._neustart_ok():
            return
        args = ([sys.executable] if getattr(sys, "frozen", False)
                else [sys.executable, os.path.abspath(__file__)])
        try:
            # Nie mit einfachem Popen: die EXE-Kopie würde sonst aus dem Temp-Ordner dieses
            # Programms laufen, den es beim Beenden wegräumt (siehe utils.saubere_umgebung).
            utils.starte_unabhaengig(args)
        except OSError as e:
            return messagebox.showerror("Neustart", "Das Programm konnte sich nicht neu starten:\n\n"
                                        f"{e}\n\nBitte von Hand schließen und wieder öffnen.",
                                        parent=self)
        self.destroy()


def _eur(v):
    return f"{v:.2f} €".replace(".", ",")


if __name__ == "__main__":
    enable_dpi_awareness()
    App().mainloop()
