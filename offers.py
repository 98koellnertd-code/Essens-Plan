"""Alle Angebote über marktguru.de abrufen (bündelt Prospekte von Aldi, Lidl, Rewe,
Edeka, Kaufland, Penny, Netto, Norma, Globus, HIT, ...) und pro KW speichern."""
import os
import re
import json
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from utils import DATA_DIR, WEEKS_DIR, load_json, save_json

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"}
API = "https://api.marktguru.de/api/v1/offers"
PAGE = 500  # API liefert max. ~512 pro Seite
FOOD_INDUSTRIES = ("Supermarkt", "Discounter", "Bio", "Lebensmittel", "Getränke")
# Wurzel-IDs des marktguru-Kategoriebaums, die Lebensmittel/Getränke sind
# (Supermärkte wie Kaufland führen auch Werkzeug, Kleidung ... als "Supermarkt")
FOOD_ROOTS = {16, 20, 23, 69, 70, 101, 102, 103, 104, 106, 107, 108, 110, 112, 113, 115,
              116, 119, 120, 147, 149, 174, 187, 191, 193, 363, 364, 454, 473, 497}
# Händlerketten zum Anhaken in den Einstellungen (Treffer per Wortanfang, siehe planner.erlaubt)
HAENDLER = ("ALDI", "Lidl", "REWE", "EDEKA", "Kaufland", "PENNY", "Netto", "NORMA", "nahkauf", "Globus",
            "Marktkauf", "tegut", "HIT", "famila", "budni", "ROSSMANN", "dm")
# Prospekt-Übersicht je Kette bei marktguru (www.marktguru.de/rp/<name>-prospekte): daraus der letzte
# Prospekt, wenn ein Händler diese Woche keine Angebote hat. ALDI: Nord und Süd, je nach Region.
PROSPEKT_SEITEN = {"ALDI": ("aldi-nord", "aldi-sued"), "Lidl": ("lidl",), "REWE": ("rewe",),
                   "EDEKA": ("edeka",), "Kaufland": ("kaufland",), "PENNY": ("penny",),
                   "Netto": ("netto-marken-discount",), "NORMA": ("norma",), "nahkauf": ("nahkauf",),
                   "Globus": ("globus",), "Marktkauf": ("marktkauf",), "tegut": ("tegut",), "HIT": ("hit",),
                   "famila": ("famila-nordost",), "budni": ("budnikowsky",), "ROSSMANN": ("rossmann",),
                   "dm": ("dm-drogerie-markt",)}
PROSPEKTE_FILE = os.path.join(DATA_DIR, "prospekte.json")
# Treue-/Kundenprogramme: Name -> Erkennung im Hinweistext des Angebots
PROGRAMME = {
    "Kaufland Card": r"kaufland card",
    "Lidl Plus": r"lidl plus",
    "Netto App": r"netto plus|netto app|deutschlandcard",
    "PENNY App": r"penny app|penny pay",
    "REWE Bonus": r"rewe bonus",
    "Payback": r"payback",
    "Rossmann App": r"rossmann app",
    "dm App": r"dm app|mydm",
    "budni App": r"budni app",
}
_RETAILER_PROG = {"Kaufland": "Kaufland Card", "Lidl": "Lidl Plus", "Netto Marken-Discount": "Netto App",
                  "PENNY": "PENNY App", "REWE": "REWE Bonus", "nahkauf": "REWE Bonus",
                  "ROSSMANN": "Rossmann App", "budni": "budni App"}
# Öffentliche Web-Keys (Fallback, falls sie nicht von der Startseite lesbar sind)
_FALLBACK_KEYS = ("8Kk+pmbf7TgJ9nVj2cXeA7P5zBGv8iuutVVMRfOfvNE=",
                  "WU/RH+PMGDi+gkZer3WbMelt6zcYHSTytNB7VpTia90=")


# ─── Wochen-Helfer ────────────────────────────────────────────────────────────
def week_start(year, kw):
    return dt.date.fromisocalendar(year, kw, 1)


def week_label(year, kw):
    s = week_start(year, kw)
    e = s + dt.timedelta(days=6)
    return f"KW {kw}  ·  {s:%d.%m.} – {e:%d.%m.%Y}"


def week_file(year, kw):
    return os.path.join(WEEKS_DIR, f"{year}-KW{kw:02d}.json")


def load_week(year, kw):
    leer = {"offers": [], "plan": {}, "scanned": ""}
    w = load_json(week_file(year, kw), leer)
    if not isinstance(w, dict):
        w = {}
    for k, v in leer.items():                  # beschädigte Datei: fehlende/falsche Teile ersetzen
        if not isinstance(w.get(k), type(v)):
            w[k] = v
    w["tage"] = _tage_ok(w.get("tage"))
    w["liste"] = _liste_ok(w.get("liste"))
    return w


ALLE_TAGE = [0, 1, 2, 3, 4, 5, 6]


def _tage_ok(t):
    """Aktive Wochentage (0 = Montag ... 6 = Sonntag): sortiert, eindeutig, nie leer."""
    if not isinstance(t, list):
        return list(ALLE_TAGE)
    ok = sorted({x for x in t if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 6})
    return ok or list(ALLE_TAGE)


def _liste_ok(li):
    """Einkaufsliste: {"haken": {name: bool}, "extras": [{typ, text, angebot?, haken}]}."""
    if not isinstance(li, dict):
        li = {}
    haken = li.get("haken")
    haken = ({str(k): v for k, v in haken.items() if isinstance(v, bool)}
             if isinstance(haken, dict) else {})
    extras = []
    for e in li.get("extras") if isinstance(li.get("extras"), list) else []:
        if not isinstance(e, dict) or e.get("typ") not in ("produkt", "notiz"):
            continue
        text = e.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        x = {"typ": e["typ"], "text": text.strip(),
             "haken": e["haken"] if isinstance(e.get("haken"), bool) else True}
        a = e.get("angebot")
        if x["typ"] == "produkt" and isinstance(a, dict):
            x["angebot"] = {"haendler": str(a.get("haendler") or ""), "produkt": str(a.get("produkt") or ""),
                            "info": str(a.get("info") or ""),
                            "preis": a["preis"] if isinstance(a.get("preis"), (int, float)) else None,
                            "vorher": a["vorher"] if isinstance(a.get("vorher"), (int, float)) else None,
                            "id": a.get("id"), "geschaetzt": a.get("geschaetzt") is True}
        extras.append(x)
    return {"haken": haken, "extras": extras}


def save_week(year, kw, data):
    save_json(week_file(year, kw), data, kompakt=True)


def is_food(o):
    if "food" in o:
        return o["food"]
    return any(k in o.get("branche", "") for k in FOOD_INDUSTRIES)


# ─── API ──────────────────────────────────────────────────────────────────────
def _api_headers():
    keys = _FALLBACK_KEYS
    try:
        html = requests.get("https://www.marktguru.de/", headers=UA, timeout=15).text
        for blob in re.findall(r'<script type="application/json">(.*?)</script>', html, re.S):
            cfg = json.loads(blob).get("config", {})
            if cfg.get("apiKey"):
                keys = (cfg["apiKey"], cfg["clientKey"])
                break
    except Exception:
        pass
    return {**UA, "x-apikey": keys[0], "x-clientkey": keys[1]}


def _local_date(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().date()


def _page(plz, offset, headers):
    r = requests.get(API, headers=headers, timeout=30,
                     params={"as": "web", "zipCode": plz, "limit": PAGE, "offset": offset})
    r.raise_for_status()
    return r.json()


def _category_roots(headers):
    """{kategorie_id: wurzel_id} aus dem Kategoriebaum; {} bei Fehler."""
    try:
        r = requests.get("https://api.marktguru.de/api/v1/categories", headers=headers,
                         params={"limit": 1000}, timeout=20)
        cats = {c["id"]: c for c in r.json()["results"]}
    except Exception:
        return {}
    roots = {}
    for c in cats.values():
        x = c
        while x.get("parentId") in cats:
            x = cats[x["parentId"]]
        roots[c["id"]] = x.get("parentId") or x["id"]
    return roots


def _parse(o, roots):
    vd = o.get("validityDates") or []
    if not vd or o.get("price") is None:
        return None
    unit = (o.get("unit") or {}).get("shortName") or ""
    ref = o.get("referencePrice")
    cat = (o.get("categories") or [{}])[0]
    p = {
        "id": o["id"],
        "haendler": ((o.get("advertisers") or [{}])[0]).get("name", "?"),
        "branche": ", ".join(i.get("name", "") for i in o.get("industries") or []),
        "kategorie": cat.get("name", ""),
        "produkt": (o.get("product") or {}).get("name") or "",
        "marke": (o.get("brand") or {}).get("name", ""),
        "info": o.get("description") or "",
        "preis": o["price"],
        "alt": o.get("oldPrice"),
        "grundpreis": f"{ref:.2f} €/{unit}".replace(".", ",") if ref and unit else "",
        "grund": ref or None,
        "einheit": unit,
        "von": min(_local_date(v["from"]) for v in vd).isoformat(),
        "bis": max(_local_date(v["to"]) for v in vd).isoformat(),
    }
    root = roots.get(cat.get("id")) or cat.get("parentId")
    if root:
        p["food"] = root in FOOD_ROOTS
    _loyalty(o, p)
    return p


def _num(s):
    return float(s.replace(",", "."))


def _loyalty(o, p):
    """Normalpreis und Treue-Aktion (App-/Kartenpreis, Bonus-Guthaben) aus dem Text lesen.
    Setzt ggf. normal, treue, treue_preis, bonus."""
    low = (o.get("description") or "").lower()
    req = bool(o.get("requiresLoyalityMembership"))
    prog = next((n for n, rx in PROGRAMME.items() if re.search(rx, low)), "")
    if req and not prog:
        prog = _RETAILER_PROG.get(p["haendler"], "Kundenkarte/App")
    m = re.search(r"(?:normalpreis|preis ohne app|ohne [\w-]+ app).{0,15}?(\d+[.,]\d{2})", low)
    if m and _num(m.group(1)) > p["preis"]:
        p["normal"] = _num(m.group(1))
    if not prog:
        return
    p["treue"] = prog
    m = re.search(r"(\d+[.,]\d{2})\s*€?\s*rewe bonus", low)
    if m:
        p["bonus"] = _num(m.group(1))
    elif req:
        p["treue_preis"] = p["preis"]          # Angebotspreis gilt nur mit Programm
    else:
        m = re.search(r"hinweis:\s*mit\s+[^\d€]{3,40}?\s(\d+[.,]\d{2})\s*€?", low)
        if m and _num(m.group(1)) < p["preis"]:
            p["treue_preis"] = _num(m.group(1))  # zusätzlicher Karten-/App-Preis


def scan(plz, progress=None):
    """Alle Angebote der PLZ seitenweise (parallel) laden. progress(done, total).
    Speichert die Angebote in jede KW-Datei, in der sie gültig sind.
    Gibt (anzahl_angebote, fehler_liste) zurück."""
    headers = _api_headers()
    first = _page(plz, 0, headers)
    total = first.get("totalResults") or 0
    pages = max(1, -(-total // PAGE))
    raw, errors = list(first.get("results") or []), []
    if progress:
        progress(1, pages)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_page, plz, i * PAGE, headers): i for i in range(1, pages)}
        for n, f in enumerate(as_completed(futs), 2):
            try:
                raw += f.result().get("results") or []
            except Exception as e:
                errors.append(f"Seite {futs[f] + 1}: {e}")
            if progress:
                progress(n, pages)

    roots = _category_roots(headers)
    offers = {}
    kaputt = 0
    for o in raw:
        try:
            p = _parse(o, roots)
        except Exception:                      # ein unlesbares Angebot darf nicht den Scan kosten
            kaputt += 1
            continue
        if p:
            offers[p["id"]] = p
    if kaputt:
        errors.append(f"{kaputt} Angebote waren unlesbar und wurden übersprungen")

    # Nach Kalenderwochen verteilen (aktuelle + 3 folgende Wochen; manche
    # Dauer-Angebote laufen offiziell bis in Jahre voraus)
    cur = week_start(*dt.date.today().isocalendar()[:2])
    horizon = cur + dt.timedelta(days=4 * 7 - 1)
    by_week = {}
    for o in offers.values():
        d = max(dt.date.fromisoformat(o["von"]), cur)
        end = min(dt.date.fromisoformat(o["bis"]), horizon)
        while d <= end:
            y, k = d.isocalendar()[:2]
            by_week.setdefault((y, k), []).append(o)
            d = week_start(y, k) + dt.timedelta(days=7)
    now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    for (y, k), offs in by_week.items():
        w = load_week(y, k)
        w["offers"] = sorted(offs, key=lambda o: (o["haendler"], o["produkt"]))
        w["scanned"] = now
        save_week(y, k, w)
    try:
        prospekte_laden(plz, headers)
    except Exception:                          # nur Zusatz-Hinweise – darf den Scan nie kosten
        pass
    return len(offers), errors


# ─── Letzte Prospekte (für Händler ohne Angebote) ─────────────────────────────
def prospekt_url(p):
    """Link zum Blättern im Prospekt bei marktguru."""
    return f"https://www.marktguru.de/leaflets/{p['id']}/page/0"


def _in_json(o, key):
    """Erste Liste unter dem Schlüssel key irgendwo in o (None, wenn keine da ist)."""
    if isinstance(o, dict):
        if isinstance(o.get(key), list):
            return o[key]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            x = _in_json(v, key)
            if x is not None:
                return x
    return None


def _prospekte_seite(slug):
    """Rohe Prospektliste (aktuelle und abgelaufene) der Seite www.marktguru.de/rp/<slug>-prospekte."""
    r = requests.get(f"https://www.marktguru.de/rp/{slug}-prospekte", headers=UA, timeout=20)
    r.raise_for_status()
    for blob in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', r.text, re.S):
        try:
            lf = _in_json(json.loads(blob), "leaflets")
        except ValueError:
            continue
        if lf is not None:
            return lf
    return []


def _prospekt(l):
    return {"id": l["mainLeafletId"], "name": (l.get("advertiser") or {}).get("name", ""),
            "von": _local_date(l["validFrom"]).isoformat(), "bis": _local_date(l["validTo"]).isoformat(),
            "seiten": l.get("pageCount") or 0, "angebote": l.get("offerCount") or 0}


def prospekte_laden(plz, headers):
    """Prospekte je Kette (neueste zuerst) nach PROSPEKTE_FILE – für den Hinweis „kein aktueller
    Prospekt, der letzte war …“. marktguru führt nicht jeden Prospekt (Kaufland fehlte z. B. wochenlang),
    darum zählt hier auch, welche Prospekte für die PLZ gerade laufen (leafletflights)."""
    try:
        r = requests.get("https://api.marktguru.de/api/v1/leafletflights", headers=headers, timeout=20,
                         params={"as": "web", "zipCode": plz, "limit": 500})
        lokal = r.json().get("results") or []
    except Exception:
        lokal = []
    lokal_ids = {f.get("mainLeafletId") for f in lokal}
    lokal_namen = {(f.get("advertiser") or {}).get("name", "") for f in lokal}
    roh = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_prospekte_seite, s): s for v in PROSPEKT_SEITEN.values() for s in v}
        for f in as_completed(futs):
            try:
                roh[futs[f]] = [_prospekt(l) for l in f.result()]
            except Exception:
                pass
    ketten = {}
    for kette, slugs in PROSPEKT_SEITEN.items():
        if not any(s in roh for s in slugs):
            continue
        ps = [p for s in slugs for p in roh.get(s, [])]
        namen = {p["name"] for p in ps}
        if namen & lokal_namen:                 # ALDI: nur Nord oder Süd, je nachdem, was hier läuft
            namen &= lokal_namen
            ps = [p for p in ps if p["name"] in namen]
        ids = {p["id"] for p in ps}
        for fl in lokal:
            if (fl.get("advertiser") or {}).get("name") in namen and fl.get("mainLeafletId") not in ids:
                try:
                    ps.append(_prospekt(fl))
                except Exception:
                    pass
        for p in ps:
            p["hier"] = p["id"] in lokal_ids
        ketten[kette] = sorted(ps, key=lambda p: (p["von"], p["bis"]), reverse=True)
    if ketten:
        save_json(PROSPEKTE_FILE, {"stand": dt.datetime.now().isoformat(timespec="minutes"),
                                   "plz": plz, "ketten": ketten})


def prospekte():
    """Gespeicherte Prospekt-Übersicht ({} vor dem ersten Scan)."""
    return load_json(PROSPEKTE_FILE, {})


def prospekt_lage(prospekte_der_kette, year, kw, heute=None):
    """Lage bei marktguru für eine Kette ohne Angebote in dieser KW: (art, prospekt).
    art "da":    ein Prospekt gilt in der Woche, marktguru hat aber keine Angebote daraus (für die PLZ);
        "bald":  die Woche liegt noch weiter vorn – ihre Prospekte erscheinen erst noch;
        "fehlt": kein Prospekt für die Woche;
        "vorbei": die Woche ist schon um (sonntags gilt sie als um, die Prospekte enden samstags).
    prospekt: der passende bzw. der letzte davor (None, wenn keiner bekannt ist)."""
    mo = week_start(year, kw)
    so = mo + dt.timedelta(days=6)
    ps = []
    for p in prospekte_der_kette or []:
        try:
            ps.append((dt.date.fromisoformat(p["von"]), dt.date.fromisoformat(p["bis"]), p))
        except (KeyError, TypeError, ValueError):
            continue
    heute = heute or dt.date.today()
    gilt = [x for x in ps if x[0] <= so and x[1] >= mo]
    if gilt:                                    # bevorzugt der, der für die PLZ läuft
        p = max(gilt, key=lambda x: (x[2].get("hier", False), x[0]))[2]
        return ("vorbei" if so <= heute else "da"), p
    frueher = [x for x in ps if x[0] <= so]
    letzter = max(frueher, key=lambda x: (x[1], x[0]))[2] if frueher else None
    if so <= heute:
        return "vorbei", letzter
    return ("bald" if (mo - heute).days > 1 else "fehlt"), letzter
