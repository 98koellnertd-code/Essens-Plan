"""Regelbasierter Essensplaner: Rezepte werden nach passenden Angeboten bewertet."""
import re
import random
import itertools
import statistics
import datetime as dt

import recipes as db
from offers import is_food

TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def load_recipes():
    """Alle Gerichte (Grunddatenbank + eigene Änderungen)."""
    return db.Store().all()


def _terms(z):
    """Suchbegriffe einer Zutat; [] = Vorrat."""
    if len(z) > 3:
        return [t.strip() for t in z[3].split("|") if t.strip()]
    return [z[0].lower()]


def scan_terms(recipes):
    return {t for r in recipes for z in r["z"] for t in _terms(z)}


# Kategorien/Wörter, die nie eine Kochzutat sind (Fertigware, Süßes, Deko ...)
BAD_CATS = ("Tiefkühlgerichte", "Kekse", "Wurstsalate", "Veganes", "Instantgerichte",
            "Kuchen", "Desserts", "Chips", "Pflanzen", "Schokoladen", "Fischsalate",
            "Dips", "Fruchtgummi", "Knabbereien", "Reinigen", "Aufbewahrung", "Snacks",
            "Sekt", "Warme Speisen", "Feinkostsalate", "Tiefkühlpizza", "Tiefkühlbackwaren",
            "Brötchen", "Streichwurst", "Essensgutscheine", "Präsentkörbe",
            "Nahrungsergänzung", "Kaffee", "Tee")
BAD_WORDS = re.compile(r"marzipan|croissant|snack|getrocknet|russisch|vegan|veggie|saure"
                       r"|milch ?reis|kicher|lauchzwiebel|frühlingszwiebel|röstzwiebel"
                       r"|schoko|salat mit|chips|aspik|süßkartoffel|spaghetti ?kürbis"
                       r"|milch ?quark|sahne ?joghurt|zier-", re.I)
# Zutat → Produkte, die trotz passendem Suchbegriff nicht gemeint sind
_FRISCH = r"rispe|cocktail|cherry|strauch|romatomate|fleischtomate|kl\. ?i\b"
INGR_EXCLUDE = {k: re.compile(v, re.I) for k, v in {
    "passierte tomaten": _FRISCH, "stückige tomaten": _FRISCH,
    "milch": r"buttermilch|dickmilch|kokosmilch|sojamilch|hafer|müllermilch|mischgetränk|kakao|shake|kondensmilch|kaffee",
    "tomaten": r"passiert|stückig|getrocknet|ketchup|tomatenmark",
}.items()}


def _term_pattern(term):
    # Begriff muss am Wortende stehen (Komposita: "Rinderhackfleisch" ja,
    # "Eierkocher"/"Frischeier-Nudeln" nein); kurze Endung für Plural erlaubt.
    stem = term[:-1] if term.endswith("n") and len(term) > 5 else term
    return re.compile(re.escape(stem) + r"\w{0,2}(?![\w-])", re.I)


def index_offers(offers, recipes):
    """Lebensmittel-Angebote mit passenden Rezept-Suchbegriffen versehen.
    Ergebnis (nur im Speicher) wird von best_offer() genutzt."""
    pats = [(t, _term_pattern(t)) for t in scan_terms(recipes)]
    out = []
    for o in offers:
        if not is_food(o) or BAD_WORDS.search(o["produkt"]) \
                or any(c in o.get("kategorie", "") for c in BAD_CATS):
            continue
        terms = [t for t, p in pats if p.search(o["produkt"])]
        if terms:
            out.append({**o, "terms": terms})
    return out


# ─── Preise ───────────────────────────────────────────────────────────────────
def rate_prices(offers):
    """Grundpreis (€/kg, €/l …) mit dem Median der Kategorie vergleichen.
    Setzt o["rel"]: -0.3 = 30 % günstiger als üblich in dieser Woche."""
    groups = {}
    for o in offers:
        if o.get("grund") and o.get("kategorie"):
            groups.setdefault((o["kategorie"], o.get("einheit")), []).append(o["grund"])
    med = {k: statistics.median(v) for k, v in groups.items() if len(v) >= 4}
    for o in offers:
        m = med.get((o.get("kategorie"), o.get("einheit")))
        if m and o.get("grund"):
            o["rel"] = o["grund"] / m - 1


def eff_price(o, cfg):
    """Preis, den man tatsächlich zahlt – mit den Treue-Programmen aus cfg."""
    p = o["preis"]
    if o.get("treue"):
        if o["treue"] in cfg.get("programme", []):
            p = (o.get("treue_preis") or p) - (o.get("bonus") or 0)
        elif o.get("treue_preis") == o["preis"]:   # gilt nur mit App/Karte
            p = o.get("normal") or p
    return round(p, 2)


def schaetzung(o):
    """Üblicher Preis aus dem Kategorie-Median des Grundpreises (nur wenn deutlich günstiger)."""
    rel = o.get("rel")
    if rel is None or rel > -0.05:
        return None
    return round(o["preis"] * min(2.0, 1 / (1 + rel)), 2)


def vorher(o, cfg, schaetzen=True):
    """Normalpreis: echt (Prospekt/App) oder – falls schaetzen – geschätzt; sonst None."""
    p = eff_price(o, cfg)
    v = o.get("alt") or o.get("normal")
    if not v and p < o["preis"]:
        v = o["preis"]                             # Karten-/App-Vorteil ggü. Prospektpreis
    if (not v or v <= p) and schaetzen:
        v = schaetzung(o)
    return v if v and v > p else None


def geschaetzt(o, cfg):
    """True, wenn vorher() nur eine Schätzung liefert."""
    return vorher(o, cfg) is not None and vorher(o, cfg, schaetzen=False) is None


def rabatt(o, cfg):
    """Rabatt in Prozent (ganze Zahl) gegenüber dem Normalpreis, auch geschätzt; None ohne Normalpreis."""
    v = vorher(o, cfg)
    return round((1 - eff_price(o, cfg) / v) * 100) if v else None


def saving(o, cfg):
    """Relative Ersparnis 0..1 – echter Rabatt, sonst halbe Kategorie-Einstufung."""
    v = vorher(o, cfg)
    if v:
        return 1 - eff_price(o, cfg) / v
    return min(0.5, max(0.0, -o.get("rel", 0.0))) * 0.5


def treue_text(o, cfg):
    t = o.get("treue")
    if not t:
        return ""
    mark = "✔ " if t in cfg.get("programme", []) else ""
    if o.get("bonus"):
        return f"{mark}{t} +{o['bonus']:.2f} € Guthaben".replace(".", ",")
    if o.get("treue_preis") == o["preis"]:
        return f"{mark}nur mit {t}"
    if o.get("treue_preis"):
        return f"{mark}{t} {o['treue_preis']:.2f} €".replace(".", ",")
    return f"{mark}{t}"


# ─── Händler-Auswahl ──────────────────────────────────────────────────────────
_ERLAUBT = {}


def _woerter(s):
    return tuple(re.findall(r"[^\W_]+", s.lower()))


def erlaubt(auswahl):
    """Prüffunktion name -> bool für eine Händler-Auswahl. Ein Händler passt, wenn seine Wörter mit
    den Wörtern eines Auswahl-Eintrags beginnen: „Netto“ passt zu „Netto Marken-Discount“, „HIT“
    nicht zu „Hitzler“. Leere Auswahl = alles erlaubt."""
    key = tuple(auswahl or ())
    ok = _ERLAUBT.get(key)
    if ok is None:
        if len(_ERLAUBT) > 2000:                    # choose_stores probiert viele Kombinationen
            _ERLAUBT.clear()
        pref = [w for w in map(_woerter, key) if w]
        if not pref:
            def ok(name):
                return True
        else:
            memo = {}

            def ok(name):
                r = memo.get(name)
                if r is None:
                    w = _woerter(name)
                    r = memo[name] = any(w[:len(p)] == p for p in pref)
                return r
        _ERLAUBT[key] = ok
    return ok


# ─── Planung ──────────────────────────────────────────────────────────────────
_IDX_SRC, _IDX = None, {}


def _offer_index(offers):
    """Suchbegriff → Angebote. Wird je Angebotsliste einmal gebaut, damit die Suche
    auch bei vielen Rezepten und Händler-Kombinationen schnell bleibt."""
    global _IDX_SRC, _IDX
    if offers is not _IDX_SRC:
        idx = {}
        for o in offers:
            for t in o.get("terms", ()):
                idx.setdefault(t, []).append(o)
        _IDX_SRC, _IDX = offers, idx
    return _IDX


def best_offer(z, offers, cfg):
    terms = _terms(z)
    if not terms:
        return None
    idx = _offer_index(offers)
    ok = erlaubt(cfg.get("haendler"))
    bad = INGR_EXCLUDE.get(z[0].lower())
    seen, hits = set(), []
    for t in terms:
        for o in idx.get(t, ()):
            if id(o) in seen:
                continue
            seen.add(id(o))
            if not ok(o["haendler"]):
                continue
            if bad and bad.search(f"{o['produkt']} {o['info']}"):
                continue
            hits.append(o)
    # Treffer auf den ersten (spezifischsten) Suchbegriff bevorzugen, dann Preis
    return min(hits, key=lambda o: (terms[0] not in o["terms"], eff_price(o, cfg)), default=None)


def score(recipe, offers, cfg):
    need = [z for z in recipe["z"] if _terms(z)]
    if not need:
        return 0.0
    s = 0.0
    for z in need:
        o = best_offer(z, offers, cfg)
        if o:
            s += 1 + saving(o, cfg) * 2
    return s / len(need) * 10


def _candidates(recipes, cfg):
    """Planbare Gerichte: pausierte raus, bei Bedarf nur vegetarische/vegane."""
    pool = [r for r in recipes if not r.get("_pause")] or list(recipes)
    if cfg.get("vegetarisch"):
        veg = [r for r in pool if {"veg", "vegan"} & set(db.tags(r))]
        return veg or pool
    return pool


def _kind(r):
    """Sättigungsbeilage bzw. erster Tag – zweimal hintereinander wäre eintönig."""
    t = db.tags(r)
    return next((k for k in t if k in db.SIDE_TAGS), t[0] if t else "")


def _main(r):
    """Hauptzutat = erste gekaufte Zutat. Zweimal Lachs in einer Woche wäre langweilig,
    auch wenn es einmal mit Nudeln und einmal mit Kartoffeln auf den Tisch kommt."""
    return next((z[0].lower() for z in r.get("z", []) if _terms(z)), "")


# Aus wie vielen Vorschlägen gewürfelt wird: Pool // PICK_WIDTH, mindestens 8. Ein starres
# Fenster von 8 ließe bei 130 Gerichten immer dieselbe Handvoll Sieger gewinnen.
PICK_WIDTH = 6


def choose_stores(recipes, offers, cfg):
    """Beste Kombination aus max. cfg["max_laeden"] Händlern für die Woche."""
    n = int(cfg.get("max_laeden") or 0)
    sel = cfg.get("haendler")
    ok = erlaubt(sel)
    allowed = sorted({o["haendler"] for o in offers if ok(o["haendler"])})
    if sel and not allowed:
        return list(sel)                    # gewählte Ketten haben keine Angebote: nichts anderes nehmen
    if not n or len(allowed) <= n:
        return allowed if sel else []
    pool = _candidates(recipes, cfg)
    best, best_s = [], -1.0
    for combo in itertools.combinations(allowed, n):
        c = {**cfg, "haendler": list(combo)}
        s = sum(sorted((score(r, offers, c) for r in pool), reverse=True)[:7])
        if s > best_s:
            best, best_s = list(combo), s
    return best


def _pick(pool, offers, cfg, exclude, avoid=None, recent=(), mains=()):
    """Gewichtete Zufallsauswahl aus den besten Treffern: Favoriten bekommen einen
    Bonus, kürzlich geplante Gerichte einen Abzug."""
    pool = [r for r in pool if r["n"] not in exclude] or pool
    scored = []
    for r in pool:
        s = score(r, offers, cfg)
        if r.get("_fav"):
            s += 3.0
        if r["n"] in recent:
            s -= 2.5
        scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    if mains:
        frisch = [x for x in scored if _main(x[1]) not in mains]
        scored = frisch or scored
    if avoid:
        alt = [x for x in scored if _kind(x[1]) != avoid]
        scored = alt or scored
    top = scored[:max(8, len(scored) // PICK_WIDTH)]
    lo = min(s for s, _ in top)
    return random.choices([r for _, r in top], weights=[s - lo + 1 for s, _ in top])[0]


def generate_week(recipes, offers, cfg, monday, tage=None):
    """Gibt (plan, läden) zurück; läden = [] bedeutet alle Händler.
    tage = Liste der Wochentag-Indizes (0 = Montag), die geplant werden; None = alle sieben."""
    stores = choose_stores(recipes, offers, cfg)
    cfg = {**cfg, "haendler": stores}
    pool = _candidates(recipes, cfg)
    letzte = db.recent(monday) if cfg.get("abwechslung", True) else set()
    plan, used, last, mains = {}, set(), None, set()
    for i in (range(7) if tage is None else sorted(set(tage))):
        r = _pick(pool, offers, cfg, used, last, letzte, mains)
        plan[(monday + dt.timedelta(days=i)).isoformat()] = r["n"]
        used.add(r["n"])
        if _main(r):
            mains.add(_main(r))
        last = _kind(r)
    return plan, stores


def regenerate_day(recipes, offers, cfg, plan, day):
    pool = _candidates(recipes, cfg)
    exclude = set(plan.values())
    nachbarn = {d: n for d, n in plan.items() if d != day}
    vor = nachbarn.get((dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat())
    avoid = _kind(next((r for r in recipes if r["n"] == vor), {})) if vor else None
    mains = {_main(r) for r in recipes if r["n"] in set(nachbarn.values())} - {""}
    plan[day] = _pick(pool, offers, cfg, exclude, avoid, mains=mains)["n"]
    return plan


def fmt_amount(v, unit):
    if unit == "x":
        return ""
    v = round(v, 1)
    txt = str(int(v)) if v == int(v) else str(v).replace(".", ",")
    return f"{txt} {unit}"


def shopping_list(recipes, offers, cfg, plan):
    """Zutaten der Woche zusammenfassen und bestes Angebot zuordnen."""
    by_name = {r["n"]: r for r in recipes}
    factor = max(1, int(cfg.get("personen", 2))) / 2
    items = {}
    for name in plan.values():
        r = by_name.get(name)
        if not r:
            continue
        for z in r["z"]:
            key = (z[0], z[2])
            it = items.setdefault(key, {"name": z[0], "einheit": z[2], "menge": 0.0,
                                        "z": z, "gerichte": []})
            it["menge"] += z[1] * factor
            it["gerichte"].append(name)
    out = []
    for it in items.values():
        vorrat = not _terms(it["z"])
        o = None if vorrat else best_offer(it["z"], offers, cfg)
        out.append({"name": it["name"], "menge": fmt_amount(it["menge"], it["einheit"]),
                    "vorrat": vorrat, "angebot": o, "gerichte": it["gerichte"],
                    "preis": eff_price(o, cfg) if o else None,
                    "vorher": vorher(o, cfg) if o else None,
                    "geschaetzt": geschaetzt(o, cfg) if o else False})
    return sorted(out, key=lambda x: (x["vorrat"], x["angebot"] is None,
                                      (x["angebot"] or {}).get("haendler", ""), x["name"]))


def totals(items):
    """(jetzt, vorher, gespart, anzahl_geschätzt, anzahl_ohne_normalpreis) über alle
    Angebotsartikel. Artikel ohne Normalpreis zählen vorher = jetzt."""
    priced = [i for i in items if i["preis"] is not None]
    now = sum(i["preis"] for i in priced)
    before = sum(i["vorher"] or i["preis"] for i in priced)
    est = sum(1 for i in priced if i.get("geschaetzt"))
    unknown = sum(1 for i in priced if not i["vorher"])
    return now, before, before - now, est, unknown


def eur(v, est=False):
    return ("~" if est else "") + f"{v:.2f} €".replace(".", ",")


def sum_hint(est, unknown):
    parts = ([f"{est}× Normalpreis geschätzt (Ø Kategorie)"] if est else []) + \
            ([f"{unknown}× kein Rabatt erkennbar"] if unknown else [])
    return " · ".join(parts)


def recipe_offers(recipe, offers, cfg):
    """[(zutat, angebot|None)] für Anzeige im Plan."""
    return [(z, best_offer(z, offers, cfg)) for z in recipe["z"]]


# Emoji je Gericht: erst Stichwörter im Namen (Reihenfolge = Vorrang), dann die Tags.
# Nur Emojis, die auch ältere Windows-Versionen kennen; keine zu kurzen Stichwörter,
# weil sie als Teilwort auch in anderen Gerichten stecken würden.
_NAME_ICONS = (("pizza", "🍕"), ("flammkuchen", "🍕"), ("burger", "🍔"), ("frikadelle", "🍔"),
               ("wrap", "🌯"), ("burrito", "🌯"), ("taco", "🌮"), ("döner", "🥙"),
               ("falafel", "🥙"), ("curry", "🍛"), ("dal", "🍛"), ("risotto", "🍚"),
               ("paella", "🥘"), ("chili", "🌶️"), ("suppe", "🍲"), ("eintopf", "🍲"),
               ("ramen", "🍜"), ("linsen", "🍲"), ("bohnen", "🍲"), ("rührei", "🍳"),
               ("omelett", "🍳"), ("frittata", "🍳"), ("pfannkuchen", "🥞"), ("waffel", "🥞"),
               ("porridge", "🥣"), ("müsli", "🥣"), ("milchreis", "🍚"), ("grießbrei", "🍮"),
               ("schnitzel", "🥩"), ("steak", "🥩"), ("gulasch", "🥩"), ("roulade", "🥩"),
               ("hackbraten", "🥩"), ("braten", "🥩"), ("bratwurst", "🌭"), ("hotdog", "🌭"),
               ("hähnchen", "🍗"), ("hühner", "🍗"), ("pute", "🍗"), ("ente", "🍗"),
               ("lachs", "🐟"), ("forelle", "🐟"), ("kabeljau", "🐟"), ("thunfisch", "🐟"),
               ("backfisch", "🐟"), ("fisch", "🐟"), ("garnelen", "🍤"), ("sushi", "🍣"),
               ("salat", "🥗"), ("bowl", "🥗"), ("spaghetti", "🍝"), ("nudel", "🍝"),
               ("lasagne", "🍝"), ("spätzle", "🍝"), ("penne", "🍝"), ("gnocchi", "🥟"),
               ("maultaschen", "🥟"), ("knödel", "🥟"), ("auflauf", "🥘"), ("gratin", "🥘"),
               ("pfanne", "🥘"), ("wok", "🥡"), ("quiche", "🥧"), ("kuchen", "🍰"),
               ("toast", "🥪"), ("sandwich", "🥪"), ("baguette", "🥖"), ("pommes", "🍟"),
               ("kartoffel", "🥔"), ("rösti", "🥔"), ("kürbis", "🎃"), ("pilz", "🍄"),
               ("champignon", "🍄"), ("tofu", "🥗"), ("couscous", "🍚"), ("bulgur", "🍚"),
               ("reis", "🍚"), ("käse", "🧀"))
_TAG_ICONS = (("fisch", "🐟"), ("suppe", "🍲"), ("süß", "🥞"), ("salat", "🥗"), ("pasta", "🍝"),
              ("reis", "🍛"), ("kartoffel", "🥔"), ("ofen", "🥘"), ("fleisch", "🥩"),
              ("vegan", "🥗"), ("veg", "🥗"))


def dish_icon(recipe):
    if not recipe:
        return "🍽️"
    name = recipe["n"].lower()
    tags = db.tags(recipe)
    return (next((i for k, i in _NAME_ICONS if k in name), None)
            or next((i for k, i in _TAG_ICONS if k in tags), "🍽️"))
