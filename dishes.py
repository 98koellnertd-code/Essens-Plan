"""Tab „Gerichte“: Gerichte durchsuchen, ansehen, bearbeiten, anlegen und einplanen.

Links die Liste mit Suche und Filter, rechts entweder die Detailansicht (mit den
aktuellen Angeboten je Zutat) oder der Editor. Gespeichert wird über recipes.Store,
die mitgelieferte Grunddatenbank bleibt dabei unverändert.
"""
import datetime as dt
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

import recipes as db
import planner as pl
import ui
from ui import Card, Btn, RoundIcon, ScrollArea, Section, wrap_label
from utils import C, F, S, ToolTip

ART = {"basis": "Grunddatenbank", "geändert": "Geändert", "eigen": "Eigenes Gericht",
       "gelöscht": "Gelöscht"}
# Kurzzeichen in der Liste – Favorit (grüner Kreis) und pausiert (graue Schrift) sieht man schon
MARK = {"geändert": " ✎", "eigen": " ✚"}
F_ALLE, F_FAV, F_PAUSE, F_EIGEN, F_TRASH = ("Alle Gerichte", "Nur Favoriten", "Nur pausierte",
                                            "Eigene und geänderte", "Papierkorb")
FILTERS = [F_ALLE, F_FAV, F_PAUSE, F_EIGEN, F_TRASH] + [lbl for _, lbl, _ in db.TAGS]
BY_LABEL = {lbl: key for key, lbl, _ in db.TAGS}


class DishTab:
    def __init__(self, app, page):
        self.app = app
        self.page = page
        self.sel = None
        self.items = []
        self.editing = False
        self._veraltet = False      # Detailansicht muss neu aufgebaut werden, sobald man sie sieht
        self._menu = None
        self._after = None
        self._f = tkfont.Font(font=F["base"])
        self.ih = self._f.metrics("linespace") + S(4)
        self._room = 0

        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=S(8), pady=(0, S(4)))
        left = tk.Frame(wrap, bg=C["bg"], width=S(362))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.right = tk.Frame(wrap, bg=C["bg"])
        self.right.pack(side="left", fill="both", expand=True)
        self._build_left(left)
        self.refresh()

    # ── Liste ────────────────────────────────────────────────────────────────
    def _build_left(self, left):
        card = Card(left, pad=12, padx=14)
        card.pack(fill="x")
        b = card.body
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._later())
        self.app._field_label(b, "Suche").pack(fill="x")
        ent = ttk.Entry(b, textvariable=self.q, width=1)
        ent.pack(fill="x", pady=(S(3), S(10)))
        ToolTip(ent, "Nach Gerichtnamen suchen – die Liste filtert beim Tippen", delay=600)
        self.app._field_label(b, "Filter").pack(fill="x")
        self.filt = tk.StringVar(value=F_ALLE)
        cb = ttk.Combobox(b, textvariable=self.filt, values=FILTERS, state="readonly", width=1)
        cb.pack(fill="x", pady=(S(3), 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ToolTip(cb, "Nur bestimmte Gerichte zeigen, z. B. Favoriten, eigene oder pausierte", delay=600)

        bar = tk.Frame(left, bg=C["bg"])
        bar.pack(side="bottom", fill="x", padx=S(10), pady=(S(4), S(10)))
        Btn(bar, "Neues Gericht", self.new, kind="primary", icon="➕",
            tip="Ein eigenes Gericht anlegen").pack(side="left")
        Btn(bar, "", self.do_import, kind="light", icon="📥", padx=10,
            tip="Rezepte aus einer Datei importieren").pack(side="right")
        Btn(bar, "", self.do_export, kind="light", icon="📤", padx=10,
            tip="Alle Rezepte in eine Datei sichern").pack(side="right", padx=(0, S(6)))
        self.count = tk.Label(left, text="", bg=C["bg"], fg=C["subtext"], font=F["small_bold"],
                              anchor="w", padx=S(12))
        self.count.pack(side="bottom", fill="x")
        ToolTip(self.count, "Anzahl der gezeigten Gerichte. Ein Klick auf ein Gericht zeigt Details, "
                            "ein Doppelklick öffnet es zum Bearbeiten.", delay=600)

        self.tree = self.app._tree(left, [], show="tree")
        self.tree.column("#0", width=S(240), minwidth=S(120), stretch=True)
        self.tree.bind("<Configure>", lambda e: self._fit_names(e.width), add="+")
        self.tree.tag_configure("pause", foreground=C["subtext"])
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.sel and self._show(self.sel, edit=True))

    def _later(self):
        if self._after:
            self.app.after_cancel(self._after)
        self._after = self.app.after(220, self.refresh)

    def _filtered(self):
        store = self.app.store
        f = self.filt.get()
        if f == F_TRASH:
            return [dict(r, _art="gelöscht", _fav=False, _pause=False) for r in store.deleted()]
        items = store.all()
        if f == F_FAV:
            items = [r for r in items if r["_fav"]]
        elif f == F_PAUSE:
            items = [r for r in items if r["_pause"]]
        elif f == F_EIGEN:
            items = [r for r in items if r["_art"] != "basis"]
        elif f in BY_LABEL:
            items = [r for r in items if BY_LABEL[f] in db.tags(r)]
        q = self.q.get().lower().strip()
        if q:
            items = [r for r in items if q in r["n"].lower()
                     or any(q in str(z[0]).lower() for z in r.get("z", []))]
        return items

    # Lange Namen enden mit „…“, statt mitten im Buchstaben abgeschnitten zu werden.
    def _space(self, width=None):
        w = self.tree.winfo_width() if width is None else width
        return max(S(60), w - S(24) - self.ih - S(22))

    def _label(self, r, room):
        mark = MARK.get(r["_art"], "")
        name = r["n"]
        if self._f.measure(name + mark) <= room:
            return f" {name}{mark}"
        while name and self._f.measure(f"{name}…{mark}") > room:
            name = name[:-1]
        return f" {name.rstrip()}…{mark}"

    def _fit_names(self, width):
        room = self._space(width)
        if room == self._room:
            return
        self._room = room
        for r in self.items:
            if self.tree.exists(r["n"]):
                self.tree.item(r["n"], text=self._label(r, room))

    def refresh(self, select=None):
        if self._after:                  # wartet noch ein verzögerter Aufruf, wäre er jetzt doppelt
            self.app.after_cancel(self._after)
        self._after = None
        self.items = self._filtered()
        tv = self.tree
        tv.delete(*tv.get_children())
        self._room = room = self._space()
        for n, r in enumerate(self.items):
            circle = C["green_soft"] if r.get("_fav") else C["surface"]
            img = ui.emoji_img(pl.dish_icon(r), self.ih, circle)
            tags = (["pause"] if r.get("_pause") else []) + (["odd"] if n % 2 else [])
            tv.insert("", "end", iid=r["n"], text=self._label(r, room), image=img or "",
                      tags=tags)
        self.count.config(text=f"{len(self.items)} von {len(self.app.store.all())} Gerichten")
        want = select or self.sel
        if want not in tv.get_children(""):
            want = self.items[0]["n"] if self.items else None
        if self.editing and select is None:
            return                       # Editor offen: rechte Seite nicht wegwerfen
        self.sel = want
        if want:
            tv.selection_set(want)
            tv.see(want)
        if self._sichtbar() or self.editing:
            self._show(want)
        else:
            self._veraltet = True

    # Die Detailansicht ist das Teure an diesem Tab (Karten, Knöpfe, je Zutat das beste Angebot).
    # Sie wird deshalb nur aufgebaut, wenn man sie auch sieht – sonst erst beim Öffnen des Tabs.
    def _sichtbar(self):
        t = self.app.tabs
        return 0 <= t.current < len(t.pages) and t.pages[t.current] is self.page

    def daten_geaendert(self):
        """Andere Woche, neuer Plan oder neue Einstellungen: Die Liste hängt nur an den Rezepten
        und bleibt stehen. Neu aufzubauen ist allein die Detailansicht (Angebote, Mengen,
        „zuletzt geplant“) – und ein offener Editor wird dafür nicht weggeworfen."""
        if self._sichtbar() and not self.editing:
            self._show(self.sel)
        else:
            self._veraltet = True

    def tab_gewaehlt(self):
        if self._veraltet and not self.editing:
            self._show(self.sel)

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if sel and sel[0] != self.sel:
            self.sel = sel[0]
            self._show(self.sel)

    def select(self, name):
        """Von außen: Gericht anzeigen (z. B. aus dem Plan heraus)."""
        self.q.set("")
        self.filt.set(F_ALLE)
        self.refresh(name)

    # ── rechte Seite ─────────────────────────────────────────────────────────
    def _clear(self):
        for w in self.right.winfo_children():
            w.destroy()

    def _show(self, name, edit=False):
        self.editing = edit
        self._veraltet = False
        self._clear()
        r = next((x for x in self.items if x["n"] == name), None) or self.app.store.get(name)
        if edit:
            self._editor(r or {"n": "", "t": "", "z": [], "a": []})
        elif r:
            self._detail(r)
        else:
            card = Card(self.right, pad=18)
            card.pack(fill="x")
            Section(card.body, "🍽️", "Kein Gericht gewählt",
                    "Links ein Gericht auswählen oder ein neues anlegen.").pack(fill="x")

    def _detail(self, r):
        sa = ScrollArea(self.right, bg=C["bg"])
        sa.pack(fill="both", expand=True)
        f = sa.inner
        head = Card(f, pad=16)
        head.pack(fill="x")
        b = head.body
        top = tk.Frame(b, bg=C["surface"])
        top.pack(fill="x")
        RoundIcon(top, pl.dish_icon(r), 56,
                  C["green_soft"] if r.get("_fav") else None).pack(side="left", padx=(0, S(14)))
        box = tk.Frame(top, bg=C["surface"])
        box.pack(side="left", fill="x", expand=True)
        wrap_label(box, r["n"], bg=C["surface"], fg=C["text"], font=F["big"]).pack(fill="x")
        letzt, mal = db.last_planned(r["n"])
        teile = [ART[r["_art"]], f"{len(r.get('z', []))} Zutaten"]
        if r.get("d"):
            teile.append(f"ca. {r['d']} Min")
        if r.get("_fav"):
            teile.append("Favorit")
        if r.get("_pause"):
            teile.append("pausiert – wird nicht eingeplant")
        if letzt:
            teile.append(f"zuletzt {letzt:%d.%m.%Y} ({mal}×)")
        wrap_label(box, "  ·  ".join(teile), bg=C["surface"], fg=C["subtext"],
                   font=F["small_bold"]).pack(fill="x", pady=(S(2), 0))
        chips = self._chips(box, r)
        if chips:
            chips.pack(fill="x", pady=(S(8), 0))

        if r["_art"] == "gelöscht":
            bar = tk.Frame(b, bg=C["surface"])
            bar.pack(fill="x", pady=(S(14), 0))
            Btn(bar, "Wiederherstellen", lambda: self._undelete(r["n"]), kind="green", icon="♻️",
                tip="Gericht wieder in die Liste aufnehmen").pack(side="left")
            return
        self._buttons(b, r)
        self._ingredients(f, r)
        if r.get("a"):
            self._steps(f, r)

    def _chips(self, parent, r):
        tags = db.tags(r)
        if not tags:
            return None
        row = tk.Frame(parent, bg=C["surface"])
        for t in tags:
            tk.Label(row, text=db.TAG_LABEL.get(t, t), bg=C["accent_soft"], fg=C["accent"],
                     font=F["small_bold"], padx=S(9), pady=S(3)).pack(side="left", padx=(0, S(6)))
        return row

    def _buttons(self, b, r):
        n = r["n"]
        store = self.app.store
        r1 = tk.Frame(b, bg=C["surface"])
        r1.pack(fill="x", pady=(S(14), 0))
        Btn(r1, "Bearbeiten", lambda: self._show(n, edit=True), kind="primary", icon="✏️",
            tip="Zutaten, Kategorien und Zubereitung ändern").pack(side="left")
        plan = Btn(r1, "Einplanen", None, kind="light", icon="📅",
                   tip="Gericht auf einen Tag dieser Woche legen")
        plan.command = lambda: self._plan_menu(plan, n)
        plan.pack(side="left", padx=S(6))
        Btn(r1, "Favorit entfernen" if r["_fav"] else "Favorit", lambda: self._toggle(n, "fav"),
            kind="light", icon="⭐", tip="Favoriten werden beim Planen bevorzugt").pack(side="left")
        Btn(r1, "Fortsetzen" if r["_pause"] else "Pausieren", lambda: self._toggle(n, "pause"),
            kind="light", icon="▶️" if r["_pause"] else "⏸️", padx=10,
            tip="Pausierte Gerichte werden nicht eingeplant").pack(side="left", padx=(S(6), 0))
        r2 = tk.Frame(b, bg=C["surface"])
        r2.pack(fill="x", pady=(S(6), 0))
        Btn(r2, "Duplizieren", lambda: self._duplicate(n), kind="light", icon="📋", padx=10,
            tip="Kopie anlegen und abwandeln").pack(side="left")
        if store.changed(n):
            Btn(r2, "Original", lambda: self._restore(n), kind="light", icon="↩️", padx=10,
                tip="Eigene Änderungen verwerfen und die Fassung aus der Grunddatenbank nehmen"
                ).pack(side="left", padx=S(6))
        Btn(r2, "Löschen", lambda: self._delete(n), kind="light", icon="🗑️", padx=10,
            tip="Gericht aus der Liste entfernen").pack(side="left")

    def _ingredients(self, f, r):
        card = Card(f, pad=14)
        card.pack(fill="x")
        b = card.body
        Section(b, "🧺", "Zutaten", f"Mengen für {self.app.cfg.get('personen', 2)} Personen  ·  "
                "Angebote dieser Woche").pack(fill="x", pady=(0, S(10)))
        grid = tk.Frame(b, bg=C["surface"])
        grid.pack(fill="x")
        for col, w in ((0, 1), (1, 3), (2, 6), (3, 1)):
            grid.columnconfigure(col, weight=w, minsize=S(70) if col in (0, 3) else S(90))
        for c, t in enumerate(("Menge", "Zutat", "Angebot", "Preis")):
            tk.Label(grid, text=t.upper(), bg=C["surface"], fg=C["subtext"], font=F["small_bold"],
                     anchor="e" if c == 3 else "w").grid(row=0, column=c, sticky="ew",
                                                         padx=S(4), pady=(0, S(4)))
        cfg = self.app._pcfg()
        faktor = max(1, int(self.app.cfg.get("personen", 2))) / 2
        treffer, summe = 0, 0.0
        for i, z in enumerate(r.get("z", [])):
            o = None if not pl._terms(z) else pl.best_offer(z, self.app.food, cfg)
            bg = C["row_stripe"] if i % 2 else C["surface"]
            vals = [pl.fmt_amount(z[1] * faktor, z[2]) or "–", z[0]]
            if o:
                treffer += 1
                p = pl.eff_price(o, cfg)
                summe += p
                vals += [f"{o['haendler']}: {o['produkt']} {o['info']}".strip(), pl.eur(p)]
                fg = C["green"]
            else:
                vals += ["Vorrat prüfen" if not pl._terms(z) else "kein Angebot", ""]
                fg = C["subtext"]
            for c, v in enumerate(vals):
                lbl = tk.Label(grid, text=v, bg=bg, anchor="e" if c == 3 else "w",
                               fg=fg if c in (2, 3) else C["text"],
                               font=F["small_bold"] if c in (1, 3) else F["small"])
                lbl.grid(row=i + 1, column=c, sticky="ew", padx=S(4), ipady=S(3))
                if c == 2:
                    lbl.configure(wraplength=1)
                    ui.auto_wrap(lbl, rand=6, mindest=80)
        tk.Label(b, text=f"{treffer} von {len(r.get('z', []))} Zutaten im Angebot"
                      + (f"  ·  ca. {pl.eur(summe)}" if treffer else ""),
                 bg=C["surface"], fg=C["text"], font=F["small_bold"], anchor="w"
                 ).pack(fill="x", pady=(S(10), 0))

    def _steps(self, f, r):
        card = Card(f, pad=14)
        card.pack(fill="x")
        b = card.body
        Section(b, "🍳", "Zubereitung", f"{len(r['a'])} Schritte").pack(fill="x", pady=(0, S(8)))
        for i, s in enumerate(r["a"], 1):
            row = tk.Frame(b, bg=C["surface"])
            row.pack(fill="x", pady=(0, S(6)))
            tk.Label(row, text=str(i), bg=C["accent_soft"], fg=C["accent"], font=F["small_bold"],
                     width=2, pady=S(2)).pack(side="left", padx=(0, S(10)), anchor="n")
            wrap_label(row, s, bg=C["surface"], fg=C["text"], font=F["base"]).pack(
                side="left", fill="x", expand=True)

    # ── Aktionen ─────────────────────────────────────────────────────────────
    def _plan_menu(self, btn, name):
        # Das vorige Menü erst jetzt wegräumen: unter Windows läuft der gewählte Befehl erst,
        # nachdem tk_popup zurückgekehrt ist – ein sofort zerstörtes Menü würde ihn verschlucken.
        if self._menu is not None:
            self._menu.destroy()
        m = self._menu = tk.Menu(self.app, tearoff=0)
        monday = self.app._monday()
        for i in self.app.week.get("tage", range(7)):      # nur Tage, die im Plan sind
            d = monday + dt.timedelta(days=i)
            m.add_command(label=f"{pl.TAGE[i]}, {d:%d.%m.}",
                          command=lambda i=i: self.app.plan_dish(i, name))
        try:
            m.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            m.grab_release()

    def _toggle(self, name, was):
        an = self.app.store.toggle(name, was)
        self.app.recipes_changed(name)
        wort = ("Favorit" if was == "fav" else "Pausiert") if an else \
               ("kein Favorit mehr" if was == "fav" else "wieder aktiv")
        self.app.set_status(f"„{name}“: {wort}")

    def _duplicate(self, name):
        neu = self.app.store.duplicate(name)
        self.app.recipes_changed(neu)
        self._show(neu, edit=True)

    def _restore(self, name):
        neu = self.app.store.restore(name)
        self.app.recipes_changed(neu)
        self.app.set_status(f"„{neu}“ auf die Grunddatenbank zurückgesetzt")

    def _delete(self, name):
        if not messagebox.askyesno("Gericht löschen", f"„{name}“ wirklich entfernen?\n\n"
                                   "Gerichte der Grunddatenbank kannst du im Papierkorb "
                                   "wieder zurückholen.", parent=self.app):
            return
        self.sel = None
        self.app.store.delete(name)
        self.app.recipes_changed()
        self.app.set_status(f"„{name}“ gelöscht")

    def _undelete(self, name):
        self.app.store.undelete(name)
        self.filt.set(F_ALLE)
        self.app.recipes_changed(name)
        self.app.set_status(f"„{name}“ wiederhergestellt")

    def new(self):
        self.sel = None
        self._show(None, edit=True)

    def do_export(self):
        p = filedialog.asksaveasfilename(parent=self.app, defaultextension=".json",
                                         filetypes=[("Rezepte (JSON)", "*.json")],
                                         initialfile="rezepte_export.json")
        if not p:
            return
        try:
            self.app.store.export(p)
        except OSError as e:
            return messagebox.showerror("Sichern fehlgeschlagen", str(e), parent=self.app)
        self.app.set_status(f"{len(self.app.store.all())} Rezepte gesichert: {p}")

    def do_import(self):
        p = filedialog.askopenfilename(parent=self.app, filetypes=[("Rezepte (JSON)", "*.json")])
        if not p:
            return
        try:
            neu, ersetzt, fehler = self.app.store.import_file(p)
        except Exception as e:
            return messagebox.showerror("Import fehlgeschlagen", str(e), parent=self.app)
        self.app.recipes_changed()
        msg = f"{neu} neue und {ersetzt} ersetzte Gerichte übernommen."
        if fehler:
            msg += "\n\nÜbersprungen:\n" + "\n".join(fehler[:8])
        messagebox.showinfo("Import", msg, parent=self.app)

    # ── Editor ───────────────────────────────────────────────────────────────
    def _zgrid(self, fr):
        for col, weight, minsize in ((0, 3, S(110)), (1, 0, S(62)), (2, 0, S(78)),
                                     (3, 2, S(90)), (4, 0, S(58)), (5, 0, S(46))):
            fr.columnconfigure(col, weight=weight, minsize=minsize)

    def _editor(self, r):
        alt = r.get("n") or None
        self.e = {"old": alt, "tags": {}, "rows": []}
        sa = ScrollArea(self.right, bg=C["bg"], fill_height=True)
        sa.pack(fill="both", expand=True)
        f = sa.inner

        card = Card(f, pad=16)
        card.pack(fill="x")
        b = card.body
        Section(b, "✏️" if alt else "➕", "Gericht bearbeiten" if alt else "Neues Gericht",
                "Mengen bitte für 2 Personen angeben – die App rechnet sie hoch."
                ).pack(fill="x", pady=(0, S(12)))
        self.e["name"] = tk.StringVar(value=r.get("n", ""))
        self.e["dauer"] = tk.StringVar(value=str(r.get("d") or ("" if alt else 30)))
        self.app._field_label(b, "Name des Gerichts").pack(fill="x")
        ent = ttk.Entry(b, textvariable=self.e["name"], font=F["combo"])
        ent.pack(fill="x", pady=(S(3), S(12)))
        ent.focus_set()
        self.app._field_label(b, "Zubereitungszeit (Minuten)").pack(fill="x")
        ttk.Spinbox(b, from_=5, to=240, increment=5, textvariable=self.e["dauer"], width=8
                    ).pack(anchor="w", pady=(S(3), S(12)))
        self.app._field_label(b, "Kategorien").pack(fill="x")
        tg = tk.Frame(b, bg=C["surface"])
        tg.pack(fill="x", pady=(S(3), 0))
        for c in range(3):
            tg.columnconfigure(c, weight=1, uniform="tg")
        cur = db.tags(r)
        for i, (key, label, _) in enumerate(db.TAGS):
            var = tk.BooleanVar(value=key in cur)
            ttk.Checkbutton(tg, text=label, variable=var).grid(row=i // 3, column=i % 3, sticky="w")
            self.e["tags"][key] = var

        zc = Card(f, pad=14)
        zc.pack(fill="x")
        zb = zc.body
        Section(zb, "🧺", "Zutaten", "„Suchbegriffe“ bestimmen, wonach in den Angeboten gesucht "
                "wird (leer = Name). „Vorrat“ = zu Hause, wird nicht gesucht.").pack(
                    fill="x", pady=(0, S(10)))
        hdr = tk.Frame(zb, bg=C["surface"])
        hdr.pack(fill="x", pady=(0, S(4)))
        self._zgrid(hdr)
        for c, t in enumerate(("Zutat", "Menge", "Einheit", "Suchbegriffe", "Vorrat", "")):
            tk.Label(hdr, text=t.upper(), bg=C["surface"], fg=C["subtext"], font=F["small_bold"],
                     anchor="w").grid(row=0, column=c, sticky="w", padx=(0, S(6)))
        self.zbox = tk.Frame(zb, bg=C["surface"])
        self.zbox.pack(fill="x")
        for z in r.get("z", []) or [["", 1, "g"]]:
            self._add_row(z)
        Btn(zb, "Zutat hinzufügen", lambda: self._add_row(), kind="light", icon="➕", padx=10,
            pady=5).pack(anchor="w", pady=(S(10), 0))

        ac = Card(f, pad=14)
        ac.pack(fill="x")
        ab = ac.body
        Section(ab, "🍳", "Zubereitung", "Ein Schritt je Zeile – erscheint auch im PDF."
                ).pack(fill="x", pady=(0, S(10)))
        box = tk.Frame(ab, bg=C["border"])
        box.pack(fill="x")
        self.e["steps"] = txt = tk.Text(box, height=8, bg=C["surface2"], fg=C["text"], font=F["base"],
                                        relief="flat", bd=0, highlightthickness=0, wrap="word",
                                        padx=S(8), pady=S(6), insertbackground=C["text"])
        txt.pack(fill="both", expand=True, padx=max(1, S(1)), pady=max(1, S(1)))
        txt.insert("1.0", "\n".join(r.get("a", [])))

        bar = tk.Frame(f, bg=C["bg"])
        bar.pack(fill="x", padx=S(10), pady=(S(6), S(12)))
        Btn(bar, "Speichern", self._save, kind="green", icon="💾",
            tip="Gericht in „meine_rezepte.json“ speichern").pack(side="left")
        Btn(bar, "Abbrechen", lambda: self._show(self.sel), kind="light", icon="✖️"
            ).pack(side="left", padx=S(8))

    def _add_row(self, z=None):
        z = list(z or ["", 1, "g"])
        fr = tk.Frame(self.zbox, bg=C["surface"])
        fr.pack(fill="x", pady=(0, S(5)))
        self._zgrid(fr)
        row = {"frame": fr, "name": tk.StringVar(value=str(z[0])),
               "menge": tk.StringVar(value=pl.fmt_amount(z[1], "").strip() if len(z) > 1 else "1"),
               "einheit": tk.StringVar(value=z[2] if len(z) > 2 else "g"),
               "such": tk.StringVar(value=z[3] if len(z) > 3 and z[3] else ""),
               "vorrat": tk.BooleanVar(value=len(z) > 3 and z[3] == "")}
        ttk.Entry(fr, textvariable=row["name"], width=1).grid(row=0, column=0, sticky="ew",
                                                              padx=(0, S(6)))
        ttk.Entry(fr, textvariable=row["menge"], width=5, justify="right").grid(
            row=0, column=1, sticky="ew", padx=(0, S(6)))
        ttk.Combobox(fr, textvariable=row["einheit"], values=db.UNITS, width=5).grid(
            row=0, column=2, sticky="ew", padx=(0, S(6)))
        such = ttk.Entry(fr, textvariable=row["such"], width=1)
        such.grid(row=0, column=3, sticky="ew", padx=(0, S(6)))
        ToolTip(such, "Mehrere Begriffe mit | trennen, z. B. hackfleisch|rinderhack")

        def upd(*_):
            such.configure(state="disabled" if row["vorrat"].get() else "normal")
        chk = ttk.Checkbutton(fr, variable=row["vorrat"], command=upd)
        chk.grid(row=0, column=4, sticky="w")
        ToolTip(chk, "Habe ich zu Hause – nicht in den Angeboten suchen")
        Btn(fr, "", lambda: self._del_row(row), kind="light", icon="🗑️", padx=7, pady=4,
            tip="Zutat entfernen").grid(row=0, column=5, sticky="e")
        upd()
        self.e["rows"].append(row)

    def _del_row(self, row):
        row["frame"].destroy()
        self.e["rows"] = [r for r in self.e["rows"] if r is not row]
        if not self.e["rows"]:
            self._add_row()

    def _save(self):
        e = self.e
        z = []
        for row in e["rows"]:
            name = row["name"].get().strip()
            if not name:
                continue
            it = [name, row["menge"].get().strip() or "1", row["einheit"].get().strip() or "x"]
            if row["vorrat"].get():
                it.append("")
            elif row["such"].get().strip():
                it.append(row["such"].get().strip())
            z.append(it)
        try:
            dauer = int(float(e["dauer"].get() or 0))
        except ValueError:
            dauer = 0
        rec = {"n": e["name"].get().strip(),
               "t": ",".join(k for k, v in e["tags"].items() if v.get()),
               "d": dauer, "z": z,
               "a": [s.strip() for s in e["steps"].get("1.0", "end").splitlines() if s.strip()]}
        benutzt = [n for n in self.app.store.names() if n != e["old"]]
        fehler = db.check(rec, benutzt)
        if fehler:
            return messagebox.showerror("Bitte prüfen", "\n".join(fehler), parent=self.app)
        try:
            name = self.app.store.put(rec, e["old"])
        except OSError as err:
            return messagebox.showerror("Speichern fehlgeschlagen", str(err), parent=self.app)
        self.sel = name
        self.app.recipes_changed(name)
        self.app.set_status(f"Gericht „{name}“ gespeichert")
