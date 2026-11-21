"""Rezept-Datenbank: gebündelte Grunddatenbank + eigene Änderungen.

Die mitgelieferte res/rezepte.json bleibt unangetastet; alles, was in der App bearbeitet
wird, landet in meine_rezepte.json im Datenordner. So überschreibt ein Update der App
keine eigenen Gerichte, und „Original wiederherstellen“ ist jederzeit möglich.

Format von meine_rezepte.json:
  {"version": 2,
   "eigene":   [rezept, …],   # neue und geänderte Gerichte (ersetzen Basis über den Namen)
   "entfernt": ["Name", …],   # ausgeblendete Gerichte der Grunddatenbank
   "favoriten":["Name", …],   # werden beim Planen bevorzugt
   "pausiert": ["Name", …]}   # werden beim Planen übersprungen

Rezept: {"n": Name, "t": "tag,tag", "d": Minuten, "z": [[Zutat, Menge, Einheit, "suche|suche"]],
         "a": ["Schritt", …], "basis": Name in der Grunddatenbank (nur nach Umbenennen)}
"""
import os
import glob
import json
import datetime as dt

from utils import (RECIPES_BASE, RECIPES_USER, RECIPES_OLD, WEEKS_DIR, load_json, save_json)

# Erlaubte Tags: Schlüssel, Beschriftung, Symbol
TAGS = [("fleisch", "Fleisch", "🥩"), ("fisch", "Fisch", "🐟"), ("veg", "Vegetarisch", "🥗"),
        ("vegan", "Vegan", "🌱"), ("pasta", "Pasta", "🍝"), ("reis", "Reis", "🍛"),
        ("kartoffel", "Kartoffel", "🥔"), ("suppe", "Suppe", "🍲"), ("salat", "Salat", "🥬"),
        ("ofen", "Ofen", "🔥"), ("schnell", "Schnell", "⏱️"), ("süß", "Süß", "🥞")]
TAG_KEYS = [t[0] for t in TAGS]
TAG_LABEL = {k: lbl for k, lbl, _ in TAGS}
TAG_ICON = {k: ic for k, _, ic in TAGS}
# Beilagen-/Sättigungs-Tags – zwei Tage hintereinander wäre langweilig
SIDE_TAGS = ("pasta", "reis", "kartoffel", "suppe", "salat")

UNITS = ["g", "kg", "ml", "l", "Stk", "Zehe", "Dose", "Glas", "Pck", "Bund", "EL", "TL",
         "Scheibe", "x"]


def tags(r):
    return [t.strip() for t in (r or {}).get("t", "").split(",") if t.strip()]


def has_tag(r, tag):
    return tag in tags(r)


def clean(r):
    """Rezept ohne Laufzeit-Felder (_fav …) und mit sauberen Typen – so wird gespeichert."""
    out = {"n": str(r.get("n", "")).strip(),
           "t": ",".join(t for t in tags(r) if t in TAG_KEYS)}
    if r.get("d"):
        try:
            out["d"] = max(1, int(r["d"]))
        except (TypeError, ValueError):
            pass
    z = []
    for it in r.get("z", []):
        it = list(it)
        name = str(it[0]).strip()
        try:
            menge = round(float(str(it[1]).replace(",", ".")), 3)
        except (TypeError, ValueError, IndexError):
            menge = 1.0
        einheit = str(it[2]).strip() if len(it) > 2 and str(it[2]).strip() else "x"
        row = [name, menge, einheit]
        if len(it) > 3 and it[3] is not None:
            such = "|".join(s.strip().lower() for s in str(it[3]).split("|") if s.strip())
            if such != name.lower():
                row.append(such)
        z.append(row)
    out["z"] = z
    a = [str(s).strip() for s in r.get("a", []) if str(s).strip()]
    if a:
        out["a"] = a
    if r.get("basis"):
        out["basis"] = r["basis"]
    return out


def check(rec, used_names=()):
    """Liste von Fehlermeldungen – leer heißt speicherbar."""
    errs = []
    name = str(rec.get("n", "")).strip()
    if not name:
        errs.append("Bitte einen Namen eingeben.")
    elif name.lower() in {n.lower() for n in used_names}:
        errs.append(f"Es gibt schon ein Gericht namens „{name}“.")
    z = [it for it in rec.get("z", []) if str(it[0]).strip()]
    if not z:
        errs.append("Bitte mindestens eine Zutat mit Namen angeben.")
    for it in z:
        try:
            if float(str(it[1]).replace(",", ".")) <= 0:
                errs.append(f"Menge bei „{it[0]}“ muss größer als 0 sein.")
        except (TypeError, ValueError):
            errs.append(f"Menge bei „{it[0]}“ ist keine Zahl.")
    bad = [t for t in tags(rec) if t not in TAG_KEYS]
    if bad:
        errs.append("Unbekannte Kategorie: " + ", ".join(bad))
    return errs


class Store:
    """Gemischte Sicht auf Grunddatenbank und eigene Änderungen."""

    def __init__(self):
        self.reload()

    # ── laden / speichern ────────────────────────────────────────────────────
    def reload(self):
        self.base = [r for r in load_json(RECIPES_BASE, {}).get("rezepte", []) if r.get("n")]
        self._base = {r["n"]: r for r in self.base}
        data = load_json(RECIPES_USER, {})
        if not data and os.path.exists(RECIPES_OLD) \
                and os.path.abspath(RECIPES_OLD) != os.path.abspath(RECIPES_BASE):
            data = self._migrate_old()
        self.own = [r for r in data.get("eigene", []) if r.get("n")]
        self.removed = {n for n in data.get("entfernt", []) if n in self._base}
        self.fav = set(data.get("favoriten", []))
        self.paused = set(data.get("pausiert", []))
        self._build()

    def _covered(self, r):
        """True, wenn die Grunddatenbank dieses Gericht schon enthält: gleicher Name und in
        allen Feldern, die die alte Fassung kennt, derselbe Inhalt. Dass die neue Fassung
        zusätzlich Zeit und Zubereitung mitbringt, ist keine Änderung des Nutzers."""
        b = self._base.get(r.get("n"))
        if not b:
            return False
        alt, neu = clean(r), clean(b)
        return all(neu.get(k) == v for k, v in alt.items() if v not in ("", [], None))

    def _migrate_old(self):
        """rezepte.json aus v1.1 (dort wurde direkt editiert) in eigene Änderungen überführen."""
        old = [r for r in load_json(RECIPES_OLD, {}).get("rezepte", []) if r.get("n")]
        if not old:
            return {}
        eigene = [r for r in old if not self._covered(r)]
        fehlt = [n for n in self._base if n not in {r["n"] for r in old}]
        # Fehlen nur einzelne Gerichte, hat der Nutzer sie gelöscht. Fehlt die halbe Datenbank,
        # ist sie seit der alten Fassung gewachsen – das sind neue Gerichte, kein Papierkorb.
        entfernt = fehlt if len(fehlt) <= max(3, len(self._base) // 10) else []
        data = {"version": 2, "eigene": [clean(r) for r in eigene], "entfernt": entfernt,
                "favoriten": [], "pausiert": []}
        save_json(RECIPES_USER, data)
        try:
            os.replace(RECIPES_OLD, RECIPES_OLD.replace(".json", "_alt.json"))
        except OSError:
            pass
        return data

    def _build(self):
        own = {r["n"]: r for r in self.own}
        merged = []
        for src in (self.own, [r for r in self.base
                               if r["n"] not in own and r["n"] not in self.removed]):
            for r in src:
                r = dict(r)
                n = r["n"]
                ist_basis = n in self._base or r.get("basis") in self._base
                r["_art"] = ("basis" if n not in own else "geändert" if ist_basis else "eigen")
                r["_fav"] = n in self.fav
                r["_pause"] = n in self.paused
                merged.append(r)
        self.recipes = sorted(merged, key=lambda r: r["n"].lower())
        self.by_name = {r["n"]: r for r in self.recipes}

    def _save(self):
        save_json(RECIPES_USER, {"version": 2, "eigene": [clean(r) for r in self.own],
                                 "entfernt": sorted(self.removed),
                                 "favoriten": sorted(self.fav), "pausiert": sorted(self.paused)})
        self._build()

    # ── lesen ────────────────────────────────────────────────────────────────
    def all(self):
        return self.recipes

    def names(self):
        return [r["n"] for r in self.recipes]

    def get(self, name):
        return self.by_name.get(name)

    def original(self, name):
        """Fassung aus der Grunddatenbank (oder None)."""
        r = self.by_name.get(name) or {}
        return self._base.get(r.get("basis") or name)

    def changed(self, name):
        """True, wenn sich das Gericht von der Grunddatenbank unterscheidet."""
        orig = self.original(name)
        r = self.by_name.get(name)
        return bool(orig and r and clean(orig) != clean(r))

    def deleted(self):
        """Ausgeblendete Gerichte der Grunddatenbank (für den Papierkorb)."""
        umbenannt = {r.get("basis") for r in self.own if r.get("basis")}
        return [self._base[n] for n in sorted(self.removed) if n not in umbenannt]

    # ── ändern ───────────────────────────────────────────────────────────────
    def put(self, rec, old_name=None):
        rec = clean(rec)
        old = old_name or rec["n"]
        if old != rec["n"]:
            vorher = self.by_name.get(old) or {}
            basis = vorher.get("basis") or (old if old in self._base else None)
            if basis:
                rec["basis"] = basis
                self.removed.add(basis)
        elif old in self._base:
            rec.pop("basis", None)
        self.own = [r for r in self.own if r["n"] not in (old, rec["n"])]
        self.own.append(rec)
        self.removed.discard(rec["n"])
        for s in (self.fav, self.paused):
            if old in s and old != rec["n"]:
                s.discard(old)
                s.add(rec["n"])
        self._save()
        return rec["n"]

    def delete(self, name):
        r = self.by_name.get(name)
        if not r:
            return
        basis = r.get("basis") or (name if name in self._base else None)
        self.own = [x for x in self.own if x["n"] != name]
        if basis:
            self.removed.add(basis)
        self.fav.discard(name)
        self.paused.discard(name)
        self._save()

    def undelete(self, name):
        self.removed.discard(name)
        self._save()

    def restore(self, name):
        """Eigene Änderungen an einem Gericht der Grunddatenbank verwerfen."""
        r = self.by_name.get(name)
        if not r:
            return name
        basis = r.get("basis") or name
        if basis not in self._base:
            return name
        self.own = [x for x in self.own if x["n"] != name]
        self.removed.discard(basis)
        for s in (self.fav, self.paused):
            if name in s and name != basis:
                s.discard(name)
                s.add(basis)
        self._save()
        return basis

    def toggle(self, name, was):
        s = self.fav if was == "fav" else self.paused
        s.discard(name) if name in s else s.add(name)
        self._save()
        return name in s

    def duplicate(self, name):
        r = self.by_name.get(name)
        if not r:
            return None
        neu = clean(r)
        neu.pop("basis", None)
        vorhanden = set(self.by_name)
        i, base = 2, neu["n"]
        while neu["n"] in vorhanden:
            neu["n"] = f"{base} ({i})"
            i += 1
        self.own.append(neu)
        self._save()
        return neu["n"]

    # ── Import / Export ──────────────────────────────────────────────────────
    def export(self, path):
        save_json(path, {"app": "Essens-Plan", "stand": dt.date.today().isoformat(),
                         "rezepte": [clean(r) for r in self.recipes]})

    def import_file(self, path):
        """(neu, ersetzt, fehler) – importierte Gerichte landen in den eigenen Änderungen."""
        data = load_json(path, {})
        liste = data.get("rezepte") if isinstance(data, dict) else data
        if not isinstance(liste, list):
            raise ValueError("Datei enthält keine Rezeptliste.")
        neu = ersetzt = 0
        fehler = []
        for r in liste:
            if not isinstance(r, dict) or not r.get("n") or not r.get("z"):
                continue
            errs = check(r)
            if errs:
                fehler.append(f"{r.get('n', '?')}: {errs[0]}")
                continue
            rec = clean(r)
            if rec["n"] in self.by_name:
                ersetzt += 1
            else:
                neu += 1
            self.own = [x for x in self.own if x["n"] != rec["n"]]
            self.own.append(rec)
            self.removed.discard(rec["n"])
        self._save()
        return neu, ersetzt, fehler


# ── Verlauf: wann war ein Gericht zuletzt eingeplant? ─────────────────────────
_HIST = {"stamp": None, "data": {}}


def history(force=False):
    """{Gericht: [Datum, …]} aus den gespeicherten Wochen (gecacht)."""
    files = sorted(glob.glob(os.path.join(WEEKS_DIR, "*.json")))
    stamp = tuple((f, os.path.getmtime(f)) for f in files)
    if force or stamp != _HIST["stamp"]:
        data = {}
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    plan = json.load(fh).get("plan", {})
            except (OSError, ValueError, AttributeError):
                continue
            if not isinstance(plan, dict):
                continue
            for tag, name in plan.items():
                if name:
                    data.setdefault(name, []).append(tag)
        for v in data.values():
            v.sort()
        _HIST.update(stamp=stamp, data=data)
    return _HIST["data"]


def recent(monday, weeks=2):
    """Namen, die in den letzten Wochen vor monday schon dran waren."""
    grenze = (monday - dt.timedelta(weeks=weeks)).isoformat()
    ende = monday.isoformat()
    return {n for n, tage in history().items() if any(grenze <= t < ende for t in tage)}


def last_planned(name):
    tage = history().get(name) or []
    return (dt.date.fromisoformat(tage[-1]), len(tage)) if tage else (None, 0)
