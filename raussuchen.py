"""Reiter „Angebot raussuchen“: gezielt nach einem Artikel suchen – Sorte oder Marke, Schreibweise egal.

Oben stehen die passenden Angebote der angehakten Händler, darunter ähnliche Produkte, die gerade stark
reduziert sind (gleiche Sorte einer anderen Marke, verwandte Sorte, gleiche Abteilung). Gibt es nichts,
kommt der Artikel auf Wunsch ohne Preis auf die Einkaufsliste – mit Rückfrage, solange „Nicht mehr
fragen“ nicht angehakt ist (dieselbe Einstellung wie im Fenster „Artikel hinzufügen“).

Geschrieben für Menschen, die sich mit Computern nicht auskennen: große Schrift, drei nummerierte
Schritte, Alltagssprache und nach jedem Klick eine klare Rückmeldung unten im Reiter."""
import collections
import datetime as dt
import re
import tkinter as tk
from tkinter import font as tkfont, ttk, messagebox

import extras as ext
import offers as off
import planner as pl
import suchbegriffe as sb
import ui
from ui import Btn
from utils import C, F, S, ToolTip, GESEHEN_FILE, load_json, save_json

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


# ─── Kategorien, Top-Deals, Grundpreis (ohne Oberfläche, testbar) ────────────
# Die Leiste oben im Reiter: Schlüssel, Icon, Name, Tooltip. „alle“ ist die freie Suche wie bisher.
KATEGORIEN = (
    ("alle", "🔎", "Alle / Suche", "Freie Suche – oben eintippen, was du brauchst"),
    ("top", "⭐", "Top-Deals", "Schnäppchen-Radar: Kisten, Großpackungen, deine Marken und starke Rabatte"),
    ("getraenke", "🥤", "Getränke", "Bier, Wein, Wasser, Saft, Limo, Energy …"),
    ("kaffee", "☕", "Kaffee & Tee", "Kaffee, Tee und Kakao"),
    ("suess", "🍫", "Süßes & Snacks", "Schokolade, Kekse, Gummibärchen, Chips, Nüsse"),
    ("fleisch", "🥩", "Fleisch & Wurst", "Fleisch, Geflügel, Hack, Wurst und Aufschnitt"),
    ("fisch", "🐟", "Fisch", "Frischer Fisch, Räucherfisch, Meeresfrüchte, Fischkonserven"),
    ("obst", "🍎", "Obst & Gemüse", "Frisches Obst und Gemüse"),
    ("kraeuter", "🌿", "Kräuter & Gewürze", "Basilikum, Petersilie, Schnittlauch, Kräutertöpfe, TK-Kräuter, "
                                          "Gewürze und Salz"),
    ("milch", "🧀", "Milch & Käse", "Milch, Käse, Joghurt, Butter, Sahne, Eier, Pudding"),
    ("brot", "🍞", "Brot & Backwaren", "Brot, Brötchen, Kuchen und Gebäck"),
    ("tk", "🧊", "Tiefkühl", "Tiefkühlkost und Eis"),
    ("drogerie", "🧴", "Drogerie", "Duschgel, Shampoo, Deo, Zahnpasta, Windeln, Kosmetik …"),
    ("haushalt", "🧻", "Haushalt", "Klopapier, Küchenrolle, Wasch- und Spülmittel, Müllbeutel, Putzmittel"),
    ("tier", "🐱", "Tier", "Katzenstreu, Katzen- und Hundefutter, Tierbedarf"),
)
KAT_NAME = {k: n for k, _i, n, _t in KATEGORIEN}
KAT_ICON = {k: i for k, i, _n, _t in KATEGORIEN}

_W = "Wein|Rotweine|Weissweine|Roseweine|Likörweine|Weinmischgetränke|Sekt|Champagner|Cava|Prosecco|Glühwein"
_SP = "Brände|Cocktails|Gin|Kornbrand|Liköre|Tequila|Weinbrand|Whiskey|Wodka|Brauner Rum|Weißer Rum|Spirituosen"
# Marktguru-Kategorien je Kachel (mit „|“ getrennt – manche Namen enthalten Kommas)
_KATS = {
    "getraenke": f"Bier|Craft Beer|Alkoholfreies Bier|Wasser|Softdrinks|Säfte|Energydrinks|{_W}|{_SP}",
    "kaffee": "Kaffee|Tee|Kakao",
    "suess": "Schokoladen|Fruchtgummi|Kekse|Chips|Knabbereien|Nüsse|Salzgebäck|Popcorn|Müsliriegel|"
             "Schokoaufstrich|Bonbons|Pralinen|Süßwaren",
    "fleisch": "Geflügel|Hackfleisch|Kalbfleisch|Lammfleisch|Rindfleisch|Schweinefleisch|Wildfleisch|"
               "Koch- und Streichwurst|Salami|Schinken|Wurstaufschnitt|Würste|gemischte Fleischwaren|"
               "mariniertes Fleisch|Wurst- und Fleischkonserven|Tiefkühlfleisch",
    "fisch": "Frischfisch|Meeresfrüchte|Räucherfisch|marinierter Fisch|Tiefkühlfisch und Meeresfrüchte|"
             "Fischkonserven|Fischsalate",
    "obst": "Beeren|Birnen|Exotische Früchte|Melonen|Steinobst|Trockenobst|Weintrauben|Zitrusfrüchte|Äpfel|"
            "Brokkoli und Kohl|Exotisches Gemüse|Gurke|Hülsenfrüchte|Mais|Paprika|Salate und Blattgemüse|"
            "Sonstiges Gemüse|Spargel|Tomaten|Wurzelgemüse|Zucchini & Kürbis|Zwiebeln und Knoblauch|Pilze|"
            "Kartoffeln|Bohnen|Bananen",
    "kraeuter": "Kräuter|Gewürzmischungen|Pfeffer|Salz|Röstzwiebel|Gewürze",
    "milch": "Butter|Eier|Joghurt|Käse|Milch|Sahne, Schmand und Crème fraîche|Desserts|Quark",
    "brot": "Brot|Brötchen|Kuchen & Feinbackwaren|Tiefkühlbackwaren & -feingebäck",
    "tk": "Eis|Tiefkühlbackwaren & -feingebäck|Tiefkühlfisch und Meeresfrüchte|Tiefkühlfleisch|"
          "Tiefkühlgemüse|Tiefkühlgerichte|Tiefkühlkartoffeln|Tiefkühlobst|Tiefkühlpizza & -flammkuchen",
    "drogerie": "Duschgel|Haarpflege|Deo|Zahngesundheit|Elektrische Zahnpflege|Gesichtspflege|"
                "Cremes und Lotionen|Seife|Rasierer|Haarentfernung|Damenhygiene|Babypflege|Windeln|"
                "Makeup Zubehör|Augen Makeup|Lippenstifte|Nagellack|Teints Tönungen|Damen Düfte|Herren Düfte|"
                "Duftsets|Taschentücher|Sonnenschutz|Maniküre Pediküre|Pflaster & Verbandsmaterial|"
                "Erkältungsmittel & Abwehrstärkung|Nahrungsergänzung|Babynahrung",
    "haushalt": "Toilettenpapier|Küchenrolle|Waschmittel|Spülmittel|Müllbeutel|Reinigen|Lufterfrischer|"
                "Haushaltshandschuhe|Folienbeutel|Servietten",
    "tier": "Hundefutter|Katzenfutter|Kleintierfutter|Vogelfutter|Pferdefutter|Katzenzubehör|Hundezubehör|"
            "Vogelzubehör|Kleintierzubehör|Aquaristik",
}
_KAT_INDEX = {}
for _k, _v in _KATS.items():
    for _n in _v.split("|"):
        _KAT_INDEX.setdefault(_n.strip(), set()).add(_k)

# Suchbegriffe für Angebote ohne passende Marktguru-Kategorie (im Produktnamen, Schreibweise egal)
_WORT_RX = {
    "getraenke": r"\b(bier|pils|pilsener|pilsner|radler|weissbier|weizenbier|mineralwasser|saft|schorle|"
                 r"limonade|limo|eistee|cola|energy|energydrink|wein|rotwein|weisswein|sekt|prosecco|likor|"
                 r"whisky|whiskey|wodka|vodka|gin|rum)\b",
    "kaffee": r"\b(kaffee|espresso|cafe crema|caffe crema|kaffeepads|kaffeekapseln|tee|teebeutel|kakao)\b",
    "suess": r"(schokolade|pralinen|bonbons|fruchtgummi|gummibarchen|kekse|chips|lebkuchen|spekulatius)",
    "haushalt": r"(toilettenpapier|klopapier|kuchenrolle|kuchentucher|haushaltsrolle|waschmittel|"
                r"waschpulver|waschgel|weichspuler|spulmittel|spultabs|spulmaschinentabs|geschirrspultabs|"
                r"mullbeutel|mullsacke|abfallbeutel|allzweckreiniger|wc reiniger|glasreiniger)",
    "tier": r"(katzenstreu|klumpstreu|katzenfutter|hundefutter|katzensnack|hundesnack|nassfutter|"
            r"trockenfutter|tierfutter|katzenmilch)",
    "drogerie": r"(duschgel|shampoo|zahnpasta|zahncreme|deospray|deoroller|bodylotion|windeln|"
                r"taschentucher)",
}
_WORT_RX = {k: re.compile(v) for k, v in _WORT_RX.items()}
# Kräuter: immer prüfen (auch TK-Kräuter in „Tiefkühlgemüse“, Kräutertopf bei „Pflanzen“) – aber nicht
# Kräuterbutter, Kräuterquark, Kräuterlikör, Kräutertee, Kräuterbonbons …
_KRAUT_RX = re.compile(r"(krauter|basilikum|petersilie|schnittlauch|minze|rosmarin|thymian|koriander|"
                       r"salbei|oregano|\bdill\b)")
_KRAUT_NICHT = re.compile(r"(butter|quark|likor|tee|bonbon|kase|schnaps|bitter|dip|creme|shampoo|dusch|"
                          r"seife|pesto|gurke|honig|salami|schinken|wurst|brot|baguette|chips|"
                          r"olivenol|\bol\b|lachs|hering|marinade|steak|sauce|sosse|\bbad\b|kaugummi|"
                          r"schokolade|limonade|sirup|zahn|deo|lotion|balsam|kissen|deko)")
_KRAUT_KATS = {"Kräuter", "Gewürzmischungen", "Tiefkühlgemüse", "Salate und Blattgemüse", "Sonstiges Gemüse",
               "Pflanzen", "Dekopflanzen", "Feinkostgemüse", "Salz", ""}
_DROGERIE_NICHT = {"suess", "getraenke", "kaffee", "haushalt", "tier", "milch", "brot", "fleisch", "fisch",
                   "obst", "tk", "kraeuter"}

_KAT_CACHE = {}


def _texte(o):
    """(Produkt normalisiert, Marke+Produkt normalisiert, Produkt+Info klein) – je Angebot einmal."""
    hit = _KAT_CACHE.get(("t", id(o)))
    if hit is not None and hit[0] is o:
        return hit[1]
    if len(_KAT_CACHE) > 60000:
        _KAT_CACHE.clear()
    prod = sb.norm(o.get("produkt") or "")
    pm = sb.norm(f"{o.get('marke') or ''} {o.get('produkt') or ''}")
    roh = f"{o.get('produkt') or ''} {o.get('info') or ''}".lower()
    t = (prod, pm, roh)
    _KAT_CACHE[("t", id(o))] = (o, t)
    return t


def kategorien(o):
    """Alle Kacheln, zu denen ein Angebot gehört (eins darf in mehreren stehen: TK-Kräuter sind Tiefkühl
    und Kräuter). Erst die Marktguru-Kategorie, dann Suchbegriffe im Produktnamen."""
    hit = _KAT_CACHE.get(("k", id(o)))
    if hit is not None and hit[0] is o:
        return hit[1]
    kat = (o.get("kategorie") or "").strip()
    prod, _pm, _roh = _texte(o)
    keys = set(_KAT_INDEX.get(kat, ()))
    fremd = _fremd(o)
    if not keys and not fremd:
        keys = {k for k, rx in _WORT_RX.items() if rx.search(prod)}
    if kat in _KRAUT_KATS and _KRAUT_RX.search(prod) and not _KRAUT_NICHT.search(prod):
        keys.add("kraeuter")
    if fremd:
        keys &= {"tier", "kraeuter"}     # Futter im Zoohandel, Kräutertopf im Gartencenter
    if not keys and any(b.startswith("Drogerie") for b in _branchen(o)) and not o.get("food"):
        keys.add("drogerie")
    if "drogerie" in keys and keys & _DROGERIE_NICHT:
        keys.discard("drogerie")
    keys = frozenset(keys)
    _KAT_CACHE[("k", id(o))] = (o, keys)
    return keys


# Getränke: Unterauswahl und Alkohol
GETRAENKE_ARTEN = (
    ("", "Alle Getränke"), ("bier", "Bier"), ("wein", "Wein & Sekt"), ("spirit", "Spirituosen"),
    ("wasser", "Wasser"), ("soft", "Softdrinks & Saft"), ("energy", "Energy"),
    ("alkfrei", "Alkoholfreies Bier"))
ALKOHOL = (("beides", "Beides"), ("mit", "Mit Alkohol"), ("ohne", "Ohne Alkohol"))
_ALKOHOL_ARTEN = ("bier", "wein", "spirit")
_ART_KATS = {"bier": {"Bier", "Craft Beer"}, "alkfrei": {"Alkoholfreies Bier"},
             "wein": set(_W.split("|")), "spirit": set(_SP.split("|")), "wasser": {"Wasser"},
             "soft": {"Softdrinks", "Säfte"}, "energy": {"Energydrinks"}}
_ENERGY_RX = re.compile(r"(energy|red ?bull|monster|rockstar|\beffect\b|booster|28 black)")
_ALKFREI_RX = re.compile(r"(alkoholfrei|\b0 0\b)")
_ART_RX = (("alkfrei", re.compile(r"(alkoholfrei\w* (bier|pils|weizen|radler|helles)|"
                                  r"(bier|pils|weizen|radler|helles)\w* alkoholfrei)")),
           ("bier", re.compile(r"\b(bier|pils|pilsener|pilsner|radler|weissbier|weizen|helles|export|lager)\b")),
           ("wein", re.compile(r"\b(wein|rotwein|weisswein|rosewein|sekt|prosecco|champagner|cava|gluhwein)\b")),
           ("spirit", re.compile(r"\b(likor|whisky|whiskey|wodka|vodka|gin|rum|korn|brandy|weinbrand|tequila)\b")),
           ("wasser", re.compile(r"\b(mineralwasser|wasser|tafelwasser)\b")),
           ("soft", re.compile(r"(saft|schorle|limonade|limo|eistee|cola|fanta|sprite|nektar|smoothie)")))


def getraenk_art(o):
    """bier · alkfrei · wein · spirit · wasser · soft · energy – oder None (kein Getränk)."""
    if "getraenke" not in kategorien(o):
        return None
    kat = (o.get("kategorie") or "").strip()
    prod, pm, _roh = _texte(o)
    if kat in ("Bier", "Craft Beer") and _ALKFREI_RX.search(prod):
        return "alkfrei"
    if kat in _ART_KATS["energy"] or (kat not in _ART_KATS["bier"] | _ART_KATS["spirit"] | _ART_KATS["wein"]
                                      and _ENERGY_RX.search(pm)):
        return "energy"
    for art, kats in _ART_KATS.items():
        if kat in kats:
            return art
    for art, rx in _ART_RX:
        if rx.search(prod):
            return art
    return "soft"


def mit_alkohol(o):
    return getraenk_art(o) in _ALKOHOL_ARTEN


# Kisten, Träger und Großpackungen: „20 x 0,5-l-Fl.“, „je Ka.“, „Kasten“, „6er“, „12x1“, „Sixpack“ …
_MULTI_RX = re.compile(r"(\d{1,2})\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*-?\s*(l|liter|ml|cl|g|kg|blatt|st|rollen)\b")
_KISTE_RX = re.compile(r"(\bka\.|kasten|\bkiste)")
_TRAEGER_RX = re.compile(r"(träger|\btray\b|sixpack|six-pack|\b\d{1,2}er(?:[- ]?(?:pack|packung|träger))?\b|"
                         r"multipack|vorratspack|großpack|grosspack)")
_XXL_RX = re.compile(r"(\bxxl\b|\bmega\b|vorteilspack|sparpack)")
# Nur hier zählt eine Großpackung als Schnäppchen (bei Möhren oder Gouda heißt „XXL“ nur große Schale)
_PACK_KATS = {"getraenke", "kaffee", "haushalt", "tier", "drogerie", "suess"}


def kiste(o):
    """Großpackung erkannt? → „Kiste“, „Träger“, „Multipack“ oder „Großpackung“, sonst None."""
    hit = _KAT_CACHE.get(("x", id(o)))
    if hit is not None and hit[0] is o:
        return hit[1]
    roh = _texte(o)[2].replace("hinweis:", " ")
    m = _MULTI_RX.search(roh)
    n = int(m.group(1)) if m else 0
    fluessig = bool(m) and m.group(3) in ("l", "liter", "ml", "cl")
    art = None
    kats = kategorien(o)
    if not kats & _PACK_KATS:
        pass
    elif "getraenke" in kats:
        if _KISTE_RX.search(roh) or (fluessig and n >= 12):
            art = "Kiste"
        elif (m and n >= 4) or _TRAEGER_RX.search(roh):
            art = "Träger" if n in (4, 6, 8, 10) or "träger" in roh else "Multipack"
    elif (m and n >= 4) or _TRAEGER_RX.search(roh) or (kats & {"haushalt", "tier"} and _XXL_RX.search(roh)):
        art = "Multipack" if m and m.group(3) in ("l", "liter", "ml", "cl", "g", "kg") else "Großpackung"
    _KAT_CACHE[("x", id(o))] = (o, art)
    return art


# Grundpreis: marktguru nennt ihn fast immer (grund + einheit, bezogen auf den Prospektpreis); er wird
# auf den tatsächlich gezahlten Preis (Karte/App) umgerechnet. Fehlt er, aus der Mengenangabe rechnen.
_MENGE_RX = re.compile(r"(?:(\d{1,2})\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*-?\s*(l|liter|ml|cl|kg|g)\b")
_EINHEIT = {"l": ("l", 1), "liter": ("l", 1), "ml": ("l", 0.001), "cl": ("l", 0.01), "kg": ("kg", 1),
            "g": ("kg", 0.001)}


def menge(o):
    """(Menge, Einheit) aus Produkt/Info – „20 x 0,5 l“ → (10.0, "l"), „500 g“ → (0.5, "kg"); sonst None."""
    m = _MENGE_RX.search(_texte(o)[2])
    if not m:
        return None
    try:
        wert = float(m.group(2).replace(",", "."))
    except ValueError:
        return None
    einheit, faktor = _EINHEIT[m.group(3)]
    gesamt = int(m.group(1) or 1) * wert * faktor
    return (gesamt, einheit) if gesamt > 0 else None


def grundpreis(o, p=None):
    """(Preis je Einheit, Einheit) zum gezahlten Preis p – z. B. (1.05, "l") – oder None."""
    p = o.get("preis") if p is None else p
    g, e, preis = o.get("grund"), o.get("einheit"), o.get("preis")
    if g and e and preis and p:
        return round(g * p / preis, 2), e
    mg = menge(o)
    if mg and p:
        return round(p / mg[0], 2), mg[1]
    return None


def grund_text(gp):
    return f"{gp[0]:.2f} €/{gp[1]}".replace(".", ",") if gp else ""


# „Meine Marken“: Vorgabe (lässt sich im Reiter abwählen) – je Gruppe die Kachel, in der die Marke zählt.
# Eigene Marken zählen überall (außer Möbelhaus, Baumarkt & Co.).
MARKEN_VORGABE = (
    ("Bier", "getraenke", ("Krombacher", "Beck's", "Bitburger", "Warsteiner", "Veltins", "Radeberger",
                           "Paulaner", "Erdinger", "Jever", "Köstritzer", "Hasseröder")),
    ("Softdrinks, Energy & Wasser", "getraenke", ("Coca-Cola", "Pepsi", "Fanta", "Sprite", "Red Bull",
                                                  "Monster", "Gerolsteiner", "Volvic", "Vio")),
    ("Kaffee", "kaffee", ("Jacobs", "Tchibo", "Dallmayr", "Lavazza")),
    ("Papier & Waschmittel", "haushalt", ("Zewa", "Hakle", "Cottonelle", "Persil", "Ariel")),
    ("Katze", "tier", ("Catsan", "Cat's Best", "Whiskas", "Felix", "Sheba")),
)
MARKE_KAT = {sb.kompakt(m): kat for _g, kat, ms in MARKEN_VORGABE for m in ms}


def vorgabe_marken():
    return [m for _g, _k, ms in MARKEN_VORGABE for m in ms]


def meine_marken(cfg):
    """Die Marken aus der Einstellung – solange nie bearbeitet, die Vorgabe-Liste."""
    m = cfg.get("meine_marken")
    return list(m) if isinstance(m, list) else vorgabe_marken()


_MARKEN_RX = {}


def _marken_rx(marke):
    rx = _MARKEN_RX.get(marke)
    if rx is None:
        n = sb.norm(marke)
        k = n.replace(" ", "")
        if not k:
            rx = re.compile(r"(?!x)x")
        elif len(k) <= 4:           # kurze Marken nur als ganzes Wort („Vio“ nicht in „Violett“)
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])")
        else:                       # „Beck's“ = „Becks“, „Coca-Cola“ = „Coca Cola“
            rx = re.compile(r"(?<![a-z0-9])" + r" ?".join(map(re.escape, k)))
        _MARKEN_RX[marke] = rx
    return rx


def hat_marke(o, marke):
    return _marken_rx(marke).search(_texte(o)[1]) is not None


def marke_von(o, marken):
    """Welche der Marken steckt im Angebot? Vorgabe-Marken nur in ihrer Kachel (Felix-Katzenfutter, nicht
    Felix-Ketchup); eigene überall außer bei Möbelhaus & Co."""
    kats = kategorien(o)
    for m in marken:
        kat = MARKE_KAT.get(sb.kompakt(m))
        if kat and kat not in kats:
            continue
        if not kat and not kats and _fremd(o):
            continue
        if hat_marke(o, m):
            return m
    return None


def in_kategorie(d, key, art="", alkohol="beides", marke=None):
    """Gehört der Eintrag d (aus extras.angebote()) in die Kachel – samt Getränke-Unterauswahl?"""
    o = d[1]
    if key in ("alle", "top"):
        return True
    if key not in kategorien(o):
        return False
    if key == "getraenke":
        ga = getraenk_art(o)
        if art and ga != art:
            return False
        if alkohol == "mit" and ga not in _ALKOHOL_ARTEN:
            return False
        if alkohol == "ohne" and ga in _ALKOHOL_ARTEN:
            return False
        if marke and not hat_marke(o, marke):
            return False
    return True


def filtern(daten, haendler=(), min_rabatt=0, nur=None):
    """Händler-Auswahl des Reiters (leer = alle), Mindest-Rabatt (0 = aus; sonst fallen auch Angebote ohne
    erkennbaren Rabatt weg) und optional nur bestimmte Angebots-IDs (die neuen)."""
    ok = pl.erlaubt(haendler)
    out = []
    for d in daten:
        if not ok(d[1]["haendler"]):
            continue
        if min_rabatt and (d[0] is None or d[0] < min_rabatt):
            continue
        if nur is not None and d[1].get("id") not in nur:
            continue
        out.append(d)
    return out


SORTIERUNGEN = (("rabatt", "Rabatt"), ("preis", "Preis"), ("grundpreis", "Preis je Liter/Kilo"),
                ("haendler", "Händler"))


def sortieren(daten, art="rabatt"):
    """Einträge wie in extras.angebote() sortieren. Rabatt: höchster zuerst, ein echter Vorher-Preis zählt
    mehr als ein geschätzter; ohne Rabatt ans Ende. Preis je Liter/Kilo: je Einheit aufsteigend."""
    if art == "preis":
        def key(d):
            return d[3], d[2]
    elif art == "grundpreis":
        def key(d):
            gp = grundpreis(d[1], d[3])
            return (0, gp[1], gp[0], d[3]) if gp else (1, "", 0, d[3])
    elif art == "haendler":
        def key(d):
            return d[1]["haendler"].lower(), -(d[0] or -1), d[3]
    else:
        def key(d):
            return (1, 0, d[3]) if d[0] is None else (0, -_gewicht(d), d[3])
    return sorted(daten, key=key)


def _gruppe(o):
    """Vergleichsgruppe für den Grundpreis: Getränkeart bzw. Marktguru-Kategorie."""
    return getraenk_art(o) or (o.get("kategorie") or "").strip()


def _mediane(daten):
    werte = collections.defaultdict(list)
    for d in daten:
        gp = grundpreis(d[1], d[3])
        if gp:
            werte[(_gruppe(d[1]), gp[1])].append(gp[0])
    out = {}
    for k, v in werte.items():
        if len(v) >= 3:
            v.sort()
            out[k] = v[len(v) // 2]
    return out


def rab_text(d):
    rab, est = d[0], d[5]
    return f"{'ca. ' if est else ''}−{rab} %" if rab is not None else ""


def top_deals(daten, marken, kachel=None):
    """Schnäppchen-Radar: Kisten/Träger/Großpackungen (mit Rabatt oder bekannter Marke), Angebote deiner
    Marken und stark reduzierte Ware. Jeder Vorschlag mit Grund („Kiste Krombacher −32 %“).
    Güte: Rabatt zuerst (ein geschätzter zählt weniger), dazu ein kleiner Bonus für deine Marke, für Kisten
    und für einen günstigen Preis je Liter/Kilo im Vergleich zu ähnlichen Angeboten.
    Rückgabe: [(grund, d, punkte)], beste zuerst."""
    mediane = _mediane(daten)
    out = []
    for d in daten:
        o = d[1]
        kats = kategorien(o)
        if not kats or (kachel and kachel not in kats):
            continue
        rab = d[0]
        m = marke_von(o, marken)
        k = kiste(o)
        if k and (m or (rab is not None and rab >= 15)):
            grund, bonus = (f"{k} {m}" if m else k), 4
        elif m:
            grund, bonus = "Meine Marke", 0
        elif stark(d):
            grund, bonus = "Stark reduziert", -2
        else:
            continue
        if m:
            bonus += 6
            if not k:
                grund = f"Meine Marke {m}"
        gp = grundpreis(o, d[3])
        med = mediane.get((_gruppe(o), gp[1])) if gp else None
        if med and gp[0] > 0:
            bonus += max(-5.0, min(5.0, 10 * (med / gp[0] - 1)))
        punkte = (_gewicht(d) if rab is not None else 0) + bonus
        r = rab_text(d)
        out.append((f"{grund} · {r}" if r else grund, d, punkte))
    out.sort(key=lambda t: (-t[2], t[1][3]))
    return out


# „Neu seit dem letzten Besuch“: IDs der Angebote, die der Reiter schon gezeigt hat (eigene kleine Datei,
# nicht die config). Beim allerersten Mal ist nichts „neu“ – sonst stünde es an allem.
GESEHEN_MAX = 20000


def gesehen_laden(pfad):
    daten = load_json(pfad, {})
    ids = daten.get("ids") if isinstance(daten, dict) else None
    return set(ids) if isinstance(ids, list) else None


def gesehen_merken(pfad, alt, jetzt):
    """Aktuelle IDs dazuschreiben; die ältesten fallen heraus, wenn es zu viele werden."""
    jetzt = [i for i in jetzt if i is not None]
    schon = set(jetzt)
    ids = (jetzt + [i for i in (alt or ()) if i not in schon])[:GESEHEN_MAX]
    try:
        save_json(pfad, {"ids": ids}, kompakt=True)
    except OSError:
        pass


def neue(daten, gesehen):
    """IDs, die beim letzten Besuch noch nicht da waren (leer, wenn es noch keinen Besuch gab)."""
    if gesehen is None:
        return set()
    return {d[1]["id"] for d in daten if d[1].get("id") is not None and d[1]["id"] not in gesehen}


# ─── Oberfläche ──────────────────────────────────────────────────────────────
_UNGELADEN = object()
MIN_RABATTE = (0, 10, 20, 30, 40, 50)
MAX_KAT = 500                   # Zeilen in einer Kategorie / bei den Top-Deals


def _markieren(btn, an):
    """Umschalt-Knopf: gewählt = dunkelgrau gefüllt, sonst hell."""
    kind = "primary" if an else "light"
    if btn.kind != kind:
        btn.kind = kind
        btn._draw()


class _Fluss(tk.Frame):
    """Knöpfe und Felder, die in so viele Zeilen fließen, wie die Breite verlangt (200 %, schmales Fenster)."""

    def __init__(self, parent, gap=6, bg=None):
        super().__init__(parent, bg=bg or C["surface"], height=1)
        self.gap, self.teile, self._stand = gap, [], None
        self.bind("<Configure>", lambda e: self.ordnen(), add="+")

    def setze(self, teile):
        for w in self.teile:
            if w not in teile:
                try:
                    w.place_forget()
                except tk.TclError:
                    pass
        self.teile = list(teile)
        self._stand = None
        self.ordnen()

    def ordnen(self):
        try:
            breite = self.winfo_width()
            if breite < 50:
                return
            groessen = [(w.winfo_reqwidth(), w.winfo_reqheight()) for w in self.teile]
            stand = (breite, tuple(map(id, self.teile)), tuple(groessen))
            if stand == self._stand:
                return
            self._stand = stand
            gap = S(self.gap)
            zeilen, x = [[]], 0
            for w, (bw, bh) in zip(self.teile, groessen):
                if zeilen[-1] and x + bw > breite:
                    zeilen.append([])
                    x = 0
                zeilen[-1].append((w, x, bw, bh))
                x += bw + gap
            y = 0
            for zeile in zeilen:
                if not zeile:
                    continue
                hoch = max(t[3] for t in zeile)
                for w, x, _bw, bh in zeile:
                    w.place(x=x, y=y + (hoch - bh) // 2)
                y += hoch + S(4)
            self.configure(height=max(1, y - S(4)))
        except tk.TclError:             # Fenster wird gerade geschlossen
            pass


class _MarkenFenster:
    """„Meine Marken“: Vorgabe-Marken abwählen, eigene dazuschreiben. Speichert cfg["meine_marken"]."""

    def __init__(self, app, fertig):
        self.app, self.fertig, self._zu = app, fertig, False
        aktiv = meine_marken(app.cfg)
        vorgabe = {sb.kompakt(m) for m in vorgabe_marken()}
        an = {sb.kompakt(m) for m in aktiv}
        win = self.win = ext._fenster(app, "Meine Marken", 780, 760)
        win.protocol("WM_DELETE_WINDOW", self.schliessen)
        win.bind("<Escape>", lambda e: self.schliessen())
        kopf = tk.Frame(win, bg=C["bg"])
        kopf.pack(fill="x", padx=S(16), pady=(S(14), S(4)))
        ui.RoundIcon(kopf, "⭐", 40, bg=C["bg"]).pack(side="left", anchor="n", padx=(0, S(12)))
        t = tk.Frame(kopf, bg=C["bg"])
        t.pack(side="left", fill="x", expand=True)
        tk.Label(t, text="Meine Marken", bg=C["bg"], fg=C["text"], font=F["h3"], anchor="w").pack(fill="x")
        ui.wrap_label(t, "Angebote dieser Marken zeigt der Schnäppchen-Radar (⭐ Top-Deals) immer – mit dem "
                         "Grund „Meine Marke“. Haken weg: Die Marke zählt nicht mehr.",
                      bg=C["bg"], fg=C["subtext"], font=F["base"]).pack(fill="x")
        unten = tk.Frame(win, bg=C["bg"])
        unten.pack(side="bottom", fill="x", padx=S(16), pady=(S(6), S(12)))
        Btn(unten, "Abbrechen", self.schliessen, kind="light", padx=16,
            tip="Nichts ändern (Esc)").pack(side="right", padx=(S(8), 0))
        Btn(unten, "Speichern", self.speichern, kind="primary", icon="💾", padx=14,
            tip="Die angehakten Marken übernehmen").pack(side="right")
        Btn(unten, "Vorgabe", self.vorgabe, kind="light", icon="↩️", padx=12,
            tip="Alle vorgeschlagenen Marken wieder anhaken (deine eigenen bleiben)").pack(side="left")

        sa = ui.ScrollArea(win, bg=C["bg"])
        sa.pack(fill="both", expand=True, padx=S(6))
        body = sa.inner
        self.vars = []
        for gruppe, _k, ms in MARKEN_VORGABE:
            card = ui.Card(body, pad=8, padx=14, margin=6)
            card.pack(fill="x", padx=S(4))
            tk.Label(card.body, text=gruppe, bg=C["surface"], fg=C["text"], font=F["bold"],
                     anchor="w").pack(fill="x")
            fl = _Fluss(card.body, gap=16)
            fl.pack(fill="x")
            teile = []
            for m in ms:
                v = tk.BooleanVar(value=sb.kompakt(m) in an)
                teile.append(ttk.Checkbutton(fl, text=m, variable=v))
                self.vars.append((m, v))
            fl.setze(teile)
        card = ui.Card(body, pad=8, padx=14, margin=6)
        card.pack(fill="x", padx=S(4))
        tk.Label(card.body, text="Eigene Marken (zählen in allen Kategorien)", bg=C["surface"], fg=C["text"],
                 font=F["bold"], anchor="w").pack(fill="x")
        self.eigen_fl = _Fluss(card.body, gap=16)
        self.eigen_fl.pack(fill="x")
        self.eigene = [(m, tk.BooleanVar(value=True)) for m in aktiv if sb.kompakt(m) not in vorgabe]
        reihe = tk.Frame(card.body, bg=C["surface"])
        reihe.pack(fill="x", pady=(S(8), 0))
        self.neu_var = tk.StringVar()
        e = self.entry = ttk.Entry(reihe, textvariable=self.neu_var, font=F["base"], width=1)
        Btn(reihe, "Dazu", self.dazu, kind="primary", icon="➕", padx=12,
            tip="Marke in die Liste aufnehmen (Enter)").pack(side="right", padx=(S(8), 0))
        e.pack(side="left", fill="x", expand=True)
        ui.Platzhalter(e, self.neu_var, "Marke eintippen, z. B. Milka")
        e.bind("<Return>", lambda ev: self.dazu())
        e.bind("<KP_Enter>", lambda ev: self.dazu())
        self._eigene_zeigen()
        win.deiconify()
        win.lift()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        e.focus_set()

    def _eigene_zeigen(self):
        for w in self.eigen_fl.teile:
            w.destroy()
        teile = [ttk.Checkbutton(self.eigen_fl, text=m, variable=v) for m, v in self.eigene]
        if not teile:
            teile = [tk.Label(self.eigen_fl, text="Noch keine – unten eintippen.", bg=C["surface"],
                              fg=C["subtext"], font=F["base"])]
        self.eigen_fl.setze(teile)

    def dazu(self):
        m = " ".join(self.neu_var.get().split())
        k = sb.kompakt(m)
        if not k:
            return
        for name, v in self.vars + self.eigene:
            if sb.kompakt(name) == k:
                v.set(True)
                break
        else:
            self.eigene.append((m, tk.BooleanVar(value=True)))
            self._eigene_zeigen()
        self.neu_var.set("")
        self.entry.focus_set()

    def vorgabe(self):
        for _m, v in self.vars:
            v.set(True)

    def speichern(self):
        if self._zu:
            return
        self.app.cfg["meine_marken"] = [m for m, v in self.vars + self.eigene if v.get()]
        self.app._save_cfg(still=True)
        self.schliessen()
        self.fertig()

    def schliessen(self):
        if self._zu:
            return
        self._zu = True
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass


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
        self.kat = "alle"               # gewählte Kachel der Kategorie-Leiste
        self.art, self.marke_wahl = "", None    # Getränke: Sorte und Marke
        self.nur_neu = False
        self._neu = set()               # IDs der Angebote, die beim letzten Besuch noch nicht da waren
        self._gesehen = _UNGELADEN      # beim Start gemerkte IDs (None = allererster Besuch)
        self._gesehen_alle = set()
        self._haendler_kand = []        # Händler, die diese Woche Angebote haben (für die Händler-Knöpfe)
        self._marken_stand = None
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
        self.unterzeile = ui.wrap_label(txt, "Tipp ein, was du brauchst – oder klick eine Kategorie an. "
                                             "⭐ Top-Deals zeigt Kisten, deine Marken und starke Rabatte.",
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
        self._leisten(b)

    def _leisten(self, b):
        """Kategorie-Leiste, Filterzeile, Händler-Auswahl und die Getränke-Leiste."""
        cfg = self.app.cfg
        self.katfluss = _Fluss(b)
        self.katfluss.pack(fill="x", pady=(S(10), 0))
        self.kat_btns = {}
        for key, icon, name, tip in KATEGORIEN:
            self.kat_btns[key] = Btn(self.katfluss, name, lambda k=key: self._kat_setzen(k),
                                     kind="primary" if key == self.kat else "light", icon=icon,
                                     font=F["small_bold"], padx=9, pady=3, tip=f"{name}: {tip}")
        self.katfluss.setze(list(self.kat_btns.values()))

        # Filterzeile: Händler, Mindest-Rabatt, Sortierung, „Nur neue“, „Meine Marken“
        ff = self.filterfluss = _Fluss(b)
        ff.pack(fill="x", pady=(S(8), 0))
        self.haendler_btn = Btn(ff, "Händler: alle", self._haendler_umschalten, kind="light", icon="🏪",
                                font=F["small_bold"], padx=9, pady=3,
                                tip="Bei welchen Händlern suchen? Klick klappt die Auswahl auf und zu.\n"
                                    "Gilt für alles in diesem Reiter.")
        rab = tk.Frame(ff, bg=C["surface"])
        tk.Label(rab, text="Mindestens", bg=C["surface"], fg=C["subtext"], font=F["small_bold"]).pack(
            side="left", padx=(0, S(4)))
        self.min_var = tk.StringVar(value=self._min_text(cfg.get("raussuchen_min_rabatt", 0)))
        self.min_cb = ttk.Combobox(rab, textvariable=self.min_var, state="readonly", width=12, font=F["base"],
                                   values=[self._min_text(n) for n in MIN_RABATTE])
        self.min_cb.pack(side="left")
        self.min_cb.bind("<<ComboboxSelected>>", lambda e: self._min_gewaehlt())
        ToolTip(self.min_cb, "Nur Angebote mit mindestens so viel Rabatt zeigen.\n"
                             "„aus“ zeigt alles, auch Angebote ohne erkennbaren Rabatt.", delay=TIP)
        sor = tk.Frame(ff, bg=C["surface"])
        tk.Label(sor, text="Sortieren nach", bg=C["surface"], fg=C["subtext"], font=F["small_bold"]).pack(
            side="left", padx=(0, S(4)))
        self.sort_var = tk.StringVar(value=dict(SORTIERUNGEN).get(cfg.get("raussuchen_sortierung"), "Rabatt"))
        self.sort_cb = ttk.Combobox(sor, textvariable=self.sort_var, state="readonly", width=17, font=F["base"],
                                    values=[n for _k, n in SORTIERUNGEN])
        self.sort_cb.pack(side="left")
        self.sort_cb.bind("<<ComboboxSelected>>", lambda e: self._sort_gewaehlt())
        ToolTip(self.sort_cb, "Reihenfolge in den Kategorien und bei den Top-Deals.\n"
                              "Bei der freien Suche steht das Passendste oben.", delay=TIP)
        self.neu_btn = Btn(ff, "Nur neue", self._neu_umschalten, kind="light", icon="🆕", font=F["small_bold"],
                           padx=9, pady=3, tip="Nur Angebote zeigen, die seit deinem letzten Besuch dazugekommen "
                                               "sind.\nIn den Listen stehen sie mit „NEU“ vor dem Namen.")
        self.marken_btn = Btn(ff, "Meine Marken", self._marken_bearbeiten, kind="light", icon="⭐",
                              font=F["small_bold"], padx=9, pady=3,
                              tip="Marken, die der Schnäppchen-Radar (Top-Deals) immer zeigen soll – "
                                  "ändern, abwählen, eigene dazu")
        ff.setze([self.haendler_btn, rab, sor, self.neu_btn, self.marken_btn])

        # Aufklappbar: Händler zum Anhaken
        self.unterbox = tk.Frame(b, bg=C["surface"])
        self.unterbox.pack(fill="x")
        self.haendlerfluss = _Fluss(self.unterbox)
        self._haendler_offen = False

        # Getränke: Alkohol, Sorte, Marke
        g = self.getraenke = tk.Frame(self.unterbox, bg=C["surface"])
        self.getr_fluss = _Fluss(g)
        self.getr_fluss.pack(fill="x")
        teile = [tk.Label(self.getr_fluss, text="Alkohol:", bg=C["surface"], fg=C["subtext"],
                          font=F["small_bold"])]
        self.alk_btns = {}
        for key, name in ALKOHOL:
            self.alk_btns[key] = Btn(self.getr_fluss, name, lambda k=key: self._alkohol_setzen(k), kind="light",
                                     font=F["small_bold"], padx=9, pady=3,
                                     tip={"beides": "Getränke mit und ohne Alkohol",
                                          "mit": "Nur Bier, Wein, Sekt und Spirituosen",
                                          "ohne": "Nur Wasser, Saft, Limo, Energy und alkoholfreies Bier"}[key])
            teile.append(self.alk_btns[key])
        teile.append(tk.Label(self.getr_fluss, text="   Sorte:", bg=C["surface"], fg=C["subtext"],
                              font=F["small_bold"]))
        self.art_btns = {}
        for key, name in GETRAENKE_ARTEN:
            self.art_btns[key] = Btn(self.getr_fluss, name, lambda k=key: self._art_setzen(k), kind="light",
                                     font=F["small_bold"], padx=9, pady=3, tip=f"Nur {name} zeigen" if key else
                                     "Alle Getränke zeigen")
            teile.append(self.art_btns[key])
        self.getr_fluss.setze(teile)
        self.markenfluss = _Fluss(g)
        self.markenfluss.pack(fill="x", pady=(S(6), 0))
        self.marke_btns = {}
        self._getraenke_markieren()
        self._filter_texte()

    # ── Kategorie-Leiste und Filter ───────────────────────────────────────────
    @staticmethod
    def _min_text(n):
        try:
            n = int(n or 0)
        except (TypeError, ValueError):
            n = 0
        return f"{n} % Rabatt" if n else "Rabatt: egal"

    def _kat_setzen(self, key):
        if key != self.kat:
            self.kat = key
            if key != "getraenke":
                self.art, self.marke_wahl = "", None
            for k, btn in self.kat_btns.items():
                _markieren(btn, k == key)
            self._unterbox_ordnen()
            self._chips_zeigen()
        self.fuellen()
        self.entry.focus_set()

    def _unterbox_ordnen(self):
        """Händler-Auswahl (aufgeklappt) und Getränke-Leiste (nur bei Getränke) ein- oder ausblenden."""
        for w in (self.haendlerfluss, self.getraenke):
            w.pack_forget()
        if self._haendler_offen:
            self.haendlerfluss.pack(fill="x", pady=(S(8), 0))
        if self.kat == "getraenke":
            self.getraenke.pack(fill="x", pady=(S(8), 0))

    def _chips_zeigen(self):
        """Die Beispiel-Knöpfe gehören zur freien Suche – in einer Kategorie und bei wenig Höhe weg."""
        soll = self.kat == "alle" and not self._kompakt
        if soll and not self.chips.winfo_manager():
            self.chips.pack(fill="x", pady=(S(8), 0))
        elif not soll and self.chips.winfo_manager():
            self.chips.pack_forget()

    def _speichern(self):
        self.app._save_cfg(still=True)

    def _haendler_wahl(self):
        """Angehakte Händler, die diese Woche Angebote haben – leer heißt alle."""
        sel = self.app.cfg.get("raussuchen_haendler") or []
        return [h for h in self._haendler_kand if h in sel]

    def _haendler_bauen(self):
        kand = sorted({d[1]["haendler"] for d in (self._daten or ())}, key=str.lower)
        if kand == self._haendler_kand and self.haendlerfluss.teile:
            self._haendler_markieren()
            return
        self._haendler_kand = kand
        for w in self.haendlerfluss.teile:
            w.destroy()
        teile = [tk.Label(self.haendlerfluss, text="Händler:", bg=C["surface"], fg=C["subtext"],
                          font=F["small_bold"]),
                 Btn(self.haendlerfluss, "Alle", lambda: self._haendler_klick(None), kind="light",
                     font=F["small_bold"], padx=9, pady=3, tip="Bei allen deinen Händlern suchen")]
        for h in kand:
            teile.append(Btn(self.haendlerfluss, h, lambda h=h: self._haendler_klick(h), kind="light",
                             font=F["small_bold"], padx=9, pady=3,
                             tip=f"{h} an- oder abhaken (mehrere möglich)"))
        self._haendler_teile = dict(zip(["", None] + kand, teile))
        self.haendlerfluss.setze(teile)
        self._haendler_markieren()

    def _haendler_markieren(self):
        wahl = set(self._haendler_wahl())
        for h, btn in getattr(self, "_haendler_teile", {}).items():
            if h == "":
                continue
            _markieren(btn, (not wahl) if h is None else h in wahl)
        self._filter_texte()

    def _haendler_klick(self, h):
        cfg = self.app.cfg
        gespeichert = set(cfg.get("raussuchen_haendler") or [])
        wahl = set(self._haendler_wahl())
        if h is None:
            wahl = set()
        elif h in wahl:
            wahl.discard(h)
        else:
            wahl.add(h)
        if wahl == set(self._haendler_kand):
            wahl = set()
        # Händler ohne Angebote in dieser Woche bleiben gemerkt (nächste Woche wieder da)
        rest = gespeichert - set(self._haendler_kand) if wahl else set()
        cfg["raussuchen_haendler"] = sorted(wahl | rest, key=str.lower)
        self._speichern()
        self._haendler_markieren()
        self.fuellen()

    def _haendler_umschalten(self):
        self._haendler_offen = not self._haendler_offen
        self._unterbox_ordnen()
        self._filter_texte()

    def _min_rabatt_tab(self):
        try:
            return max(0, min(90, int(self.app.cfg.get("raussuchen_min_rabatt") or 0)))
        except (TypeError, ValueError):
            return 0

    def _min_gewaehlt(self):
        wert = self.min_var.get()
        n = int(wert.split()[0]) if wert[:1].isdigit() else 0
        self.app.cfg["raussuchen_min_rabatt"] = n
        self._speichern()
        self.min_cb.selection_clear()
        self.fuellen()
        self.entry.focus_set()

    def _sortierung(self):
        s = self.app.cfg.get("raussuchen_sortierung")
        return s if s in dict(SORTIERUNGEN) else "rabatt"

    def _sort_gewaehlt(self):
        name = self.sort_var.get()
        self.app.cfg["raussuchen_sortierung"] = next((k for k, n in SORTIERUNGEN if n == name), "rabatt")
        self._speichern()
        self.sort_cb.selection_clear()
        self.fuellen()
        self.entry.focus_set()

    def _neu_umschalten(self):
        if not self.nur_neu and not self._neu:
            self._melden("Seit deinem letzten Besuch ist nichts dazugekommen." if self._gesehen is not None else
                         "„Neu“ gibt es ab deinem nächsten Besuch – dann siehst du, was dazugekommen ist.",
                         C["orange"])
            return
        self.nur_neu = not self.nur_neu
        self._filter_texte()
        self.fuellen()

    def _alkohol(self):
        a = self.app.cfg.get("raussuchen_alkohol")
        return a if a in dict(ALKOHOL) else "beides"

    def _alkohol_setzen(self, key):
        self.app.cfg["raussuchen_alkohol"] = key
        self._speichern()
        if key == "ohne" and self.art in _ALKOHOL_ARTEN or key == "mit" and self.art and \
                self.art not in _ALKOHOL_ARTEN:
            self.art = ""
        self._getraenke_markieren()
        self.fuellen()

    def _art_setzen(self, key):
        self.art = key
        if key in _ALKOHOL_ARTEN and self._alkohol() == "ohne" or key and key not in _ALKOHOL_ARTEN and \
                self._alkohol() == "mit":
            self.app.cfg["raussuchen_alkohol"] = "beides"
            self._speichern()
        self._getraenke_markieren()
        self.fuellen()

    def _marke_setzen(self, m):
        self.marke_wahl = None if m == self.marke_wahl else m
        self._getraenke_markieren()
        self.fuellen()

    def _getraenke_markieren(self):
        alk = self._alkohol()
        for k, btn in self.alk_btns.items():
            _markieren(btn, k == alk)
        for k, btn in self.art_btns.items():
            _markieren(btn, k == self.art)
        for m, btn in self.marke_btns.items():
            _markieren(btn, m == self.marke_wahl)

    def _getraenke_marken(self, daten):
        """Marken-Knöpfe: deine Getränke-Marken, die es gerade gibt, dazu die häufigsten Marken."""
        basis = [d for d in daten if in_kategorie(d, "getraenke", self.art, self._alkohol())]
        eigene = [m for m in self._marken_liste() if MARKE_KAT.get(sb.kompakt(m)) in ("getraenke", None)]
        liste = [m for m in eigene if any(hat_marke(d[1], m) for d in basis)]
        schon = {sb.kompakt(m) for m in liste}
        zaehler = collections.Counter((d[1].get("marke") or "").strip() for d in basis)
        for m, _n in zaehler.most_common(30):
            k = sb.kompakt(m)
            if len(liste) >= 14:
                break
            if len(k) < 2 or "nobrand" in k or k in schon:
                continue
            liste.append(m)
            schon.add(k)
        if self.marke_wahl and self.marke_wahl not in liste:
            liste.append(self.marke_wahl)
        stand = tuple(liste)
        if stand == self._marken_stand:
            return
        self._marken_stand = stand
        for w in self.markenfluss.teile:
            w.destroy()
        self.marke_btns = {}
        teile = [tk.Label(self.markenfluss, text="Marke:" if liste else "Marke: gerade keine im Angebot",
                          bg=C["surface"], fg=C["subtext"], font=F["small_bold"])]
        for m in liste:
            self.marke_btns[m] = Btn(self.markenfluss, m, lambda m=m: self._marke_setzen(m), kind="light",
                                     font=F["small_bold"], padx=9, pady=3,
                                     tip=f"Nur {m} zeigen (noch einmal klicken = alle Marken)")
            teile.append(self.marke_btns[m])
        self.markenfluss.setze(teile)
        self._getraenke_markieren()

    def _marken_liste(self):
        return meine_marken(self.app.cfg)

    def _marken_bearbeiten(self):
        _MarkenFenster(self.app, self._marken_geaendert)

    def _marken_geaendert(self):
        self._marken_stand = None
        self.fuellen()

    def _filter_aktiv(self):
        return bool(self._haendler_wahl() or self._min_rabatt_tab() or self.nur_neu or
                    (self.kat == "getraenke" and (self.art or self.marke_wahl or self._alkohol() != "beides")))

    def _filter_zuruecksetzen(self):
        cfg = self.app.cfg
        cfg["raussuchen_haendler"], cfg["raussuchen_min_rabatt"], cfg["raussuchen_alkohol"] = [], 0, "beides"
        self._speichern()
        self.nur_neu, self.art, self.marke_wahl = False, "", None
        self.min_var.set(self._min_text(0))
        self._haendler_markieren()
        self._getraenke_markieren()
        self.fuellen()

    def _filter_texte(self):
        """Beschriftung von „Händler“ und „Nur neue“ an den Stand anpassen."""
        wahl = self._haendler_wahl()
        n = len(self._haendler_kand)
        txt = ("Händler: alle" if not wahl else f"Händler: {wahl[0]}" if len(wahl) == 1 else
               f"Händler: {len(wahl)} von {n}") + (" ▴" if self._haendler_offen else " ▾")
        if self.haendler_btn.text != txt:
            self.haendler_btn.set_text(txt)
        _markieren(self.haendler_btn, bool(wahl))
        ntxt = f"Nur neue ({len(self._neu)})" if self._neu else "Nur neue"
        if self.neu_btn.text != ntxt:
            self.neu_btn.set_text(ntxt)
        _markieren(self.neu_btn, self.nur_neu)
        self.filterfluss.ordnen()

    def _neu_berechnen(self):
        """„Neu seit dem letzten Besuch“: einmal je Sitzung die gemerkten IDs laden, dann die jetzigen dazu."""
        if self._gesehen is _UNGELADEN:
            self._gesehen = gesehen_laden(GESEHEN_FILE)
            self._gesehen_alle = set(self._gesehen or ())
        self._neu = neue(self._daten, self._gesehen)
        ids = [d[1]["id"] for d in self._daten if d[1].get("id") is not None]
        if ids and not set(ids) <= self._gesehen_alle:
            gesehen_merken(GESEHEN_FILE, self._gesehen_alle, ids)
            self._gesehen_alle |= set(ids)
        if self.nur_neu and not self._neu:
            self.nur_neu = False
        self._filter_texte()

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
        self.tv = app._tree(box1, [("warum", "Warum vorgeschlagen", 250), ("haendler", "Händler", 165),
                                   ("produkt", "Produkt", 250), ("info", "Info", 200), ("preis", "Preis", 82),
                                   ("grund", "Je Liter/kg", 108), ("alt", "Vorher", 82),
                                   ("rabatt", "Rabatt", 90), ("gueltig", "Gültig", 112)],
                            flex=("produkt", "info"))
        self.tv2 = app._tree(box2, [("warum", "Warum vorgeschlagen", 250), ("haendler", "Händler", 150),
                                    ("produkt", "Produkt", 220), ("info", "Info", 180), ("preis", "Preis", 82),
                                    ("grund", "Je Liter/kg", 108), ("alt", "Vorher", 82), ("rabatt", "Rabatt", 90),
                                    ("gueltig", "Gültig", 112)],
                             flex=("produkt", "info"))
        self.tv.configure(displaycolumns=[c for c in self.tv["columns"] if c != "warum"])
        legende = ("Preis = was du zahlst · Je Liter/kg = Preis je Liter, Kilo oder Stück · Vorher = normaler "
                   "Preis · ~ = geschätzt\n"
                   "✔ = steht schon auf deiner Einkaufsliste · NEU = seit deinem letzten Besuch dazugekommen\n"
                   "Spaltenkopf anklicken = sortieren")
        ToolTip(self.tv, "Angebot anklicken, dann „Auf die Einkaufsliste“ – oder doppelt klicken.\n"
                         "Mehrere auf einmal: mit Strg oder Umschalt anklicken (Strg+A = alle).\n" + legende,
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
            tv.configure(selectmode="extended")
            for k in ("<Control-a>", "<Control-A>"):
                tv.bind(k, lambda e, t=tv: (t.selection_set(t.get_children()), "break")[1])

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
        kompakt = e.height < S(720)    # Kategorie- und Filterleiste brauchen Höhe
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
            self._chips_zeigen()
            wk.titel.pack(before=wk.schritte)
            wk.schritte.pack_configure(pady=(S(12), 0))
            wk.legende.pack(fill="x", pady=(S(10), 0))
        # Kategorie-Leiste: bei wenig Höhe nur die runden Icons (der Name steht im Tooltip)
        for (key, _i, name, _t) in KATEGORIEN:
            self.kat_btns[key].set_text("" if kompakt else name)
        self.katfluss.pack_configure(pady=(S(6 if kompakt else 10), 0))
        self.filterfluss.pack_configure(pady=(S(5 if kompakt else 8), 0))
        self.katfluss.ordnen()
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
        elif self.tv.get_children():
            # Treffer oben: mindestens Kopfzeile + drei Zeilen; reicht es nicht, gibt die untere Liste nach
            need = klein = 4 * zeile + 2 * self.tv._card.m + S(4)
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
            self._neu_berechnen()
            self._haendler_bauen()
        # Händler-Auswahl, Mindest-Rabatt und „Nur neue“ des Reiters gelten für beide Listen
        daten = filtern(self._daten, self._haendler_wahl(), self._min_rabatt_tab(),
                        self._neu if self.nur_neu else None)
        self._gefiltert = daten
        text = self._text()
        if text != self._gesucht:
            self._enter_fuer = None
        self._gesucht, self._gemeint = text, None
        self.ohne_btn.set_enabled(bool(text))
        hits, oben, kat = [], [], self.kat
        such = sb.Suche(text) if text else None
        if kat == "alle":
            if text:
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
            oben = [(None, d) for d in hits[:MAX_TREFFER]]
        elif kat == "top":
            deals = top_deals(daten, self._marken_liste())
            if such:
                deals = [t for t in deals if such.passt(t[1][1])]
            grund = {id(d): g for g, d, _p in deals}
            hits = [d for _g, d, _p in deals]
            if self._sortierung() != "rabatt":      # „Rabatt“ = Güte des Radars (Rabatt, Marke, Kiste …)
                hits = sortieren(hits, self._sortierung())
            oben = [(grund[id(d)], d) for d in hits[:MAX_KAT]]
            schon = {id(d) for d in hits}
            alts = [(g, d) for g, d in top(daten) if id(d) not in schon and (not such or such.passt(d[1]))]
        else:
            if kat == "getraenke":
                self._getraenke_marken(daten)
            rows = [d for d in daten if in_kategorie(d, kat, self.art, self._alkohol(), self.marke_wahl)]
            if such:
                rows = [d for d in rows if such.passt(d[1])]
            hits = sortieren(rows, self._sortierung())
            oben = [(None, d) for d in hits[:MAX_KAT]]
            alts = [(g, d) for g, d, _p in top_deals(rows, self._marken_liste(), kachel=kat)][:60]
        anzeige = [c for c in self.tv["columns"] if c != "warum" or kat == "top"]
        if list(self.tv["displaycolumns"]) != anzeige:
            self.tv.configure(displaycolumns=anzeige)
            self.tv._fit()
        auf = self._auf_liste()
        self._zeilen(self.tv, self.rows1, oben, auf)
        self._zeilen(self.tv2, self.rows2, alts, auf)
        self._knopf_zaehlen()
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
        spalten = tv["columns"]
        for n, (grund, (rab, o, name, p, v, est)) in enumerate(liste):
            iid = str(n)
            werte = {"warum": grund or "", "haendler": o["haendler"], "produkt": self._name(o, name, auf),
                     "info": o.get("info") or "", "preis": ext._eur(p), "grund": grund_text(grundpreis(o, p)),
                     "alt": pl.eur(v, est) if v else "",
                     "rabatt": f"{'~ ' if est else ''}-{rab} %" if rab is not None else "–", "gueltig": gueltig(o)}
            tv.insert("", "end", iid=iid, tags=("odd",) if n % 2 else (), values=[werte[c] for c in spalten])
            rows[iid] = (o, name, p, v, est)

    def _name(self, o, name, auf):
        """Produktname in der Liste: ✔ = steht auf der Einkaufsliste, NEU = seit dem letzten Besuch neu."""
        i = o.get("id")
        return ("✔ " if i in auf else "") + ("NEU · " if i in self._neu else "") + name

    def _marken(self):
        """„✔“ vor den Produkten auffrischen, die (nicht mehr) auf der Einkaufsliste stehen."""
        auf = self._auf_liste()
        try:
            for tv, rows in ((self.tv, self.rows1), (self.tv2, self.rows2)):
                for iid, (o, name, *_rest) in rows.items():
                    soll = self._name(o, name, auf)
                    if tv.set(iid, "produkt") != soll:
                        tv.set(iid, "produkt", soll)
        except tk.TclError:
            pass

    def _ueberschriften(self, text, hits):
        ic1, t1, s1 = self.k1
        ic2, t2, s2 = self.k2
        kat, n = self.kat, len(hits)
        sortiert = dict(SORTIERUNGEN)[self._sortierung()]
        mehr = f" – die {MAX_KAT} ersten stehen oben" if n > MAX_KAT else ""
        if kat == "top":
            ic1.set("⭐")
            t1.config(text="Top-Deals – dein Schnäppchen-Radar" + (f": „{text}“" if text else ""))
            s1.config(text=f"{n} {'Vorschlag' if n == 1 else 'Vorschläge'}{mehr} · Kisten, Großpackungen, deine Marken und starke Rabatte · "
                           + ("die besten zuerst" if self._sortierung() == "rabatt" else f"nach {sortiert}"))
            ic2.set("🔥")
            t2.config(text="Außerdem stark reduziert")
            s2.config(text="ab 25 % billiger als sonst")
            return
        if kat != "alle":
            name = KAT_NAME[kat]
            if kat == "getraenke" and (self.art or self.marke_wahl):
                name = " · ".join(x for x in (dict(GETRAENKE_ARTEN).get(self.art) if self.art else "",
                                             self.marke_wahl or "") if x)
            ic1.set(KAT_ICON[kat])
            t1.config(text=name + (f": „{text}“" if text else ""))
            s1.config(text=f"{n} {'Angebot' if n == 1 else 'Angebote'}{mehr} · sortiert nach {sortiert}" if n else "")
            ic2.set("⭐")
            t2.config(text=f"Top-Deals in „{KAT_NAME[kat]}“")
            s2.config(text="Kisten, Großpackungen, deine Marken und starke Rabatte")
            return
        ic1.set("🛒")
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
        if self._daten and not text and not self.app._busy and self.kat == "alle":
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
        elif self.kat not in ("alle", "top"):
            self.leer2.zeigen("Hier gerade keine Kisten, Marken-Angebote oder starken Rabatte.")
        elif text:
            self.leer2.zeigen("Gerade nichts Ähnliches stark reduziert.")
        else:
            self.leer2.zeigen("Diese Woche ist bei deinen Händlern nichts stark reduziert.")

        if self.kat != "alle" and self._daten and not app._busy:
            self._zustand_kategorie(text, hits)
            return
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

    def _zustand_kategorie(self, text, hits):
        """Kategorie oder Top-Deals: Statuszeile – oder eine Karte, wenn die Filter alles wegnehmen."""
        name = KAT_NAME[self.kat]
        if hits:
            self.karte.verbergen()
            n = len(hits)
            wort = ("Vorschlag" if n == 1 else "Vorschläge") if self.kat == "top" else ("Angebot" if n == 1 else "Angebote")
            self._melden(f"{n} {wort} in „{name}“. Anklicken und "
                         "„Auf die Einkaufsliste“ drücken – mehrere auf einmal mit Strg oder Umschalt.")
            return
        knoepfe = []
        if self._filter_aktiv():
            knoepfe.append(("Filter zurücksetzen", self._filter_zuruecksetzen, "primary", "🧹"))
        if text:
            knoepfe.append(("In allen Kategorien suchen", lambda: self._kat_setzen("alle"), "light", "🔎"))
        bei = (f" zu „{text}“" if text else "")
        warum = ("Deine Filter (Händler, Mindest-Rabatt, „Nur neue“ oder die Getränke-Auswahl) lassen nichts "
                 "übrig." if self._filter_aktiv() else "Bei deinen Händlern ist diese Woche nichts davon im Angebot.")
        self.karte.zeigen(KAT_ICON[self.kat], f"Nichts in „{name}“{bei}", warum, knoepfe[:2])
        self._melden(f"In „{name}“ gibt es gerade nichts{bei}.", C["orange"])

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
        self._knopf_zaehlen()
        wahl = [rows[i] for i in sel if i in rows]
        if len(wahl) > 1:
            summe = sum(w[2] for w in wahl)
            self._melden(f"{len(wahl)} Angebote ausgewählt – zusammen {ext._eur(summe)}. Jetzt „Auf die "
                         "Einkaufsliste“ drücken.", C["text"])
            return
        o, name, p, *_rest = rows[sel[0]]
        if o.get("id") is not None and o.get("id") in self._auf_liste():
            self._melden(f"„{name}“ bei {o['haendler']} steht schon auf deiner Einkaufsliste (✔).", C["text"])
        else:
            self._melden(f"Ausgewählt: {name} bei {o['haendler']} für {ext._eur(p)}. "
                         "Jetzt „Auf die Einkaufsliste“ drücken.", C["text"])

    def _auswahl(self):
        """Alle markierten Angebote (Strg/Umschalt = mehrere) – aus der Liste, in der markiert ist."""
        for tv, rows in ((self.tv, self.rows1), (self.tv2, self.rows2)):
            try:
                wahl = [rows[i] for i in tv.selection() if i in rows]
            except tk.TclError:
                wahl = []
            if wahl:
                return wahl
        return []

    def _knopf_zaehlen(self):
        """„Auf die Einkaufsliste“ nennt die Zahl, wenn mehrere markiert sind."""
        n = len(self._auswahl())
        txt = f"{n} auf die Einkaufsliste" if n > 1 else "Auf die Einkaufsliste"
        if self.auf_btn.text != txt:
            self.auf_btn.set_text(txt)

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
        neu = schon = 0
        for o, name, p, v, est in wahl:
            if self.app.extra_hinzufuegen("produkt", name, ext.eintrag(o, name, p, v, est)):
                neu += 1
            else:
                schon += 1
        if len(wahl) == 1:
            o, name, p, *_rest = wahl[0]
            if neu:
                self._melden(f"✔ {name} ({o['haendler']}, {ext._eur(p)}) steht jetzt auf deiner Einkaufsliste.",
                             C["green"])
            else:
                self._melden(f"„{name}“ steht schon auf deiner Einkaufsliste.", C["orange"])
        else:
            rest = f" {schon} standen schon drauf." if schon else ""
            self._melden(f"✔ {neu} Angebot{'e' if neu != 1 else ''} auf die Einkaufsliste gesetzt.{rest}",
                         C["green"] if neu else C["orange"])
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
