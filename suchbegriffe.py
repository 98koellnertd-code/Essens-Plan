"""Artikelsuche mit Sorten, Schreibweisen und Marken.

Wer „Deo“ tippt, soll das Axe-Bodyspray finden, wer „AXE“ tippt, ebenso. Dafür kennt das Modul für
gängige Artikel (vor allem Drogerie und Haushalt, dazu ein paar Lebensmittel) die üblichen Sorten-
Bezeichnungen und die bekannten Marken. Schreibweisen werden angeglichen: Groß/klein, ä/ae/a,
ß/ss, Bindestriche und Leerzeichen sind egal; bei Tippfehlern hilft vorschlag().

Schnell genug für jeden Tastendruck: Der Suchbegriff wird einmal in Prüfungen übersetzt, jedes
Angebot einmal normalisiert (zwischengespeichert), die Prüfung selbst sind nur `in`-Vergleiche."""
import difflib
import re

_UML = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e", "ê": "e",
                      "à": "a", "á": "a", "ç": "c", "ñ": "n", "ô": "o", "î": "i", "&": " "})
_NICHT_AN = re.compile(r"[^a-z0-9]+")


def norm(s):
    """Kleinbuchstaben, ohne Umlaute/Akzente, ae/oe/ue → a/o/u, nur a-z0-9 und einzelne Leerzeichen."""
    s = (s or "").lower().translate(_UML).replace("ae", "a").replace("oe", "o").replace("ue", "u")
    return _NICHT_AN.sub(" ", s).strip()


def kompakt(s):
    return norm(s).replace(" ", "")


# Branchen, in denen Drogerie-, Haushalts- und Lebensmittel-Sorten nichts zu suchen haben
# (Duschkopf, Hundeshampoo, Kaffeeservice aus dem Möbelhaus …)
_NICHT_DROGERIE = ("Möbelhaus", "Baumarkt", "KFZ", "Zoo")

# name: (Sorten und Schreibweisen, Kategorien, Marken, Ausschluss-Wörter,
#        nur Drogerie/Haushalt/Lebensmittel? – False: auch Baumarkt & Co., z. B. Batterien)
_TYPEN = {
    "duschgel": ("duschgel dusche duschcreme cremedusche pflegedusche duschbad duschol duschschaum "
                 "duschpflege showergel duschgel", "Duschgel",
                 "axe nivea dove duschdas fa palmolive adidas old spice kneipp balea isana cien fenjal "
                 "treaclemoon bruno banani sanex tabac playboy",
                 "duschkopf duscharmatur duschkabine duschvorhang duschstange duschsystem duschabtrennung "
                 "handbrause brausestange duschthermostat duschmatte duschablage duschrinne duschhocker "
                 "duschwand duschtasse duschregal duschwanne reiniger kaffee", True),
    "shampoo": ("shampoo schampoo schampo schampu haarshampoo haarwasche pflegeshampoo", "Haarpflege",
                "schauma garnier fructis wahre schatze head shoulders pantene elvital elvive syoss gliss "
                "herbal essences guhl alpecin balea isana nivea dove ultra doux",
                "hundeshampoo katzenshampoo tiershampoo", True),
    "spulung": ("spulung haarspulung conditioner haarkur kur", "Haarpflege",
                "schauma garnier fructis wahre schatze pantene elvital elvive syoss gliss guhl balea isana",
                "", True),
    "haarspray": ("haarspray haarlack haargel haarwachs schaumfestiger festiger stylinggel", "Haarpflege",
                  "taft drei wetter got2b schauma wella syoss nivea balea", "", True),
    "deo": ("deo deodorant deospray deoroller deostick deocreme bodyspray antitranspirant", "Deo",
            "axe rexona nivea dove fa adidas old spice 8x4 bac garnier balea borotalco mum speick "
            "isana dove men", "", True),
    "zahnpasta": ("zahnpasta zahncreme zahngel zahnpaste", "Zahngesundheit",
                  "colgate elmex aronal blendamed blend a med odol odolmed3 sensodyne meridol signal "
                  "parodontax dentagard ajona theramed perlweiss", "burste hunde", True),
    "zahnburste": ("zahnburste zahnbursten aufsteckburste aufsteckbursten zahnburstenkopfe",
                   "Zahngesundheit", "oral b oralb dr best colgate elmex philips sonicare meridol", "hund",
                   True),
    "mundspulung": ("mundspulung mundwasser mundspullosung", "Zahngesundheit",
                    "listerine odol meridol elmex colgate", "", True),
    "seife": ("seife flussigseife handseife cremeseife seifenspender", "Seife",
              "sagrotan dove palmolive fa nivea balea duschdas lux", "", True),
    "bodylotion": ("bodylotion korperlotion korpermilch hautcreme handcreme gesichtscreme bodybutter",
                   "Cremes und Lotionen,Gesichtspflege", "nivea bebe penaten garnier dove balea eucerin neutrogena loreal kneipp", "", True),
    "rasierer": ("rasierer rasierklingen klingen rasierschaum rasiergel einwegrasierer", "Haarentfernung",
                 "gillette wilkinson bic venus", "", True),
    "sonnencreme": ("sonnencreme sonnenschutz sonnenspray sonnenmilch", "Sonnenschutz",
                    "nivea sun ambre solaire sundance ladival piz buin", "", True),
    "windeln": ("windeln babywindeln pants feuchttucher", "Windeln,Babypflege", "pampers huggies babylove lupilu moltex", "",
                True),
    "damenhygiene": ("binden tampons tampon slipeinlagen slipeinlage damenbinden menstruationstasse "
                     "periodenunterwasche", "Damenhygiene",
                     "always ob carefree libresse alldays", "", True),
    "toilettenpapier": ("toilettenpapier klopapier wcpapier klorolle klorollen toilettenrollen",
                        "Toilettenpapier", "hakle zewa charmin cosy danke floralys happy end tempo", "", True),
    "kuchenrolle": ("kuchenrolle kuchenrollen kuchenpapier haushaltsrolle haushaltsrollen kuchentucher",
                    "Küchenrolle", "zewa bounty plenty", "", True),
    "taschentucher": ("taschentucher papiertaschentucher", "Taschentücher",
                      "tempo softis kleenex zewa", "", True),
    "waschmittel": ("waschmittel waschpulver vollwaschmittel colorwaschmittel feinwaschmittel "
                    "flussigwaschmittel waschgel waschcaps", "Waschmittel",
                    "persil ariel spee frosch weisser riese perwoll sunil omo tandil fewa formil coral dash",
                    "maschine trockner", True),
    "weichspuler": ("weichspuler waschespuler wascheparfum", "Waschmittel",
                    "lenor kuschelweich vernel silan softlan", "", True),
    "spulmittel": ("spulmittel geschirrspulmittel handspulmittel", "Spülmittel", "pril fairy palmolive frosch", "",
                   True),
    "spultabs": ("spulmaschinentabs geschirrspultabs spultabs maschinentabs tabs geschirrreiniger "
                 "klarspuler spulmaschinensalz", "Spülmittel", "finish somat calgonit fairy sun", "", True),
    "reiniger": ("reiniger allzweckreiniger badreiniger wcreiniger glasreiniger putzmittel kuchenreiniger "
                 "entkalker", "Reinigen", "meister proper frosch domestos viss cillit bang sagrotan ajax general "
                 "wcente biff sidolin", "", True),
    "mullbeutel": ("mullbeutel mullsacke abfallbeutel mulltuten", "Müllbeutel", "swirl", "", True),
    "katzenstreu": ("katzenstreu klumpstreu katzensand hygienestreu katzenklostreu silikatstreu bentonit",
                    "Katzenzubehör", "", "", False),
    "batterien": ("batterien batterie mignon knopfzelle akkubatterien", "Batterien",
                  "varta duracell energizer panasonic", "ladegerat ultraschall",
                  False),
    "kaffee": ("kaffee bohnenkaffee kaffeebohnen espresso cafecrema caffecrema filterkaffee "
               "kaffeepads kaffeekapseln", "Kaffee",
               "jacobs tchibo dallmayr melitta lavazza eduscho onko senseo nescafe dolce gusto kronung "
               "movenpick segafredo bellarom gala idee kaffee",
               "maschine vollautomat automat muhle becher tasse sahne milchschaumer kocher service geschirr kanne", True),
    "tee": ("tee krautertee fruchtetee schwarztee grunertee teebeutel", "Tee",
            "teekanne messmer meßmer onno behrends westminster lipton yogi", "kocher kanne", True),
    "hackfleisch": ("hackfleisch hack gehacktes faschiertes rinderhack schweinehack gemischtes hack",
                    "Hackfleisch", "", "", True),
    "sahne": ("sahne schlagsahne schlagobers kochsahne", "", "", "", True),
    "quark": ("quark topfen magerquark speisequark", "", "", "", True),
    "brotchen": ("brotchen semmeln semmel schrippen wecken aufbackbrotchen", "Brötchen", "", "", True),
    "kartoffeln": ("kartoffeln kartoffel erdapfel speisekartoffeln", "", "", "", True),
    "tomaten": ("tomaten tomate paradeiser cherrytomaten rispentomaten strauchtomaten", "Tomaten", "", "", True),
    "nudeln": ("nudeln pasta spaghetti penne fusilli tagliatelle farfalle", "Nudeln,Eier-Teigwaren", "barilla birkel buitoni",
               "", True),
    "joghurt": ("joghurt jogurt joghurts", "Joghurt", "danone zott muller ehrmann weihenstephan", "", True),
    "schokolade": ("schokolade schoki", "Schokoladen", "milka ritter sport lindt kinder merci", "",
                   True),
    "chips": ("chips kartoffelchips stapelchips", "Chips", "lays funny frisch pringles chio crunchips", "",
              True),
    "cola": ("cola colagetrank", "Softdrinks", "coca cola pepsi fritz", "colada", True),
    "bier": ("bier pils pilsener weizen helles radler", "Bier",
             "krombacher becks warsteiner bitburger veltins oettinger paulaner erdinger", "", True),
    "eier": ("eier ei freilandeier bodenhaltung", "Eier", "", "", True),
    "butter": ("butter sussrahmbutter sauerrahmbutter", "Butter", "kerrygold meggle landliebe", "", True),
    "milch": ("milch vollmilch frischmilch hmilch", "Milch", "landliebe weihenstephan barenmarke",
              "milchreis milchschnitte milchschaumer",
              True),
}

# Oberbegriffe: Wer „Alkohol“, „Obst“ oder „Brot“ sucht, meint alles aus den passenden Prospekt-
# Kategorien von marktguru – auch wenn das Wort selbst nirgends im Angebot steht („Rotkäppchen
# Sekt“, „Pink Lady Äpfel“). Kategorien mit „|“ getrennt (manche Namen enthalten Kommas).
# name: (Wörter, Kategorien, Marken, Ausschluss-Wörter, nur Drogerie/Haushalt/Lebensmittel?)
_WEIN = "Wein|Rotweine|Weissweine|Roseweine|Likörweine|Weinmischgetränke"
_SEKT = "Sekt|Champagner|Cava"
_SCHNAPS = "Brände|Cocktails|Gin|Kornbrand|Liköre|Tequila|Weinbrand|Whiskey|Wodka|Brauner Rum|Weißer Rum"
_BIER = "Bier|Craft Beer"
_ALKOHOLFREI = "Softdrinks|Wasser|Alkoholfreies Bier|Kakao"
_FLEISCH = ("Geflügel|Hackfleisch|Kalbfleisch|Lammfleisch|Rindfleisch|Schweinefleisch|Wildfleisch|"
            "gemischte Fleischwaren|mariniertes Fleisch|Tiefkühlfleisch")
_WURST = "Koch- und Streichwurst|Salami|Schinken|Wurstaufschnitt|Würste"
_FISCH = "Frischfisch|Meeresfrüchte|Räucherfisch|marinierter Fisch|Tiefkühlfisch und Meeresfrüchte|Fischkonserven"
_MOLKEREI = "Butter|Eier|Joghurt|Käse|Milch|Sahne, Schmand und Crème fraîche"
_OBST = ("Beeren|Birnen|Exotische Früchte|Melonen|Steinobst|Trockenobst|Weintrauben|Zitrusfrüchte|Äpfel|"
         "Tiefkühlobst|Obstkonserven")
_GEMUESE = ("Brokkoli und Kohl|Exotisches Gemüse|Gurke|Hülsenfrüchte|Mais|Paprika|Salate und Blattgemüse|"
            "Sonstiges Gemüse|Spargel|Tomaten|Wurzelgemüse|Zucchini & Kürbis|Zwiebeln und Knoblauch|"
            "Kräuter|Pilze|Tiefkühlgemüse|Gemüsekonserven")
_TIERFUTTER = "Hundefutter|Katzenfutter|Kleintierfutter|Vogelfutter|Pferdefutter"
_OBER = {
    "alkohol": ("alkohol alkoholisch alk", "|".join(
        (_WEIN, _SEKT, _SCHNAPS, _BIER)), "", "alkoholfrei glas glaser tester", True),
    "wein": ("wein weine rotwein weisswein rosewein", _WEIN, "",
             "weintraube trauben essig schinken sauerkraut gummi glas glaser kuhlschrank regal", True),
    "sekt": ("sekt prosecco champagner cremant cava schaumwein", _SEKT, "", "glas glaser", True),
    "spirituosen": ("spirituosen spirituose schnaps likor whisky whiskey wodka vodka gin rum weinbrand "
                    "kornbrand doppelkorn brandy", _SCHNAPS, "", "glas glaser kugeln pralinen", True),
    "getranke": ("getranke getrank", "|".join((_ALKOHOLFREI, _WEIN, _SEKT, _SCHNAPS, _BIER)), "",
                 "halter spender kuhler", True),
    "fleisch": ("fleisch frischfleisch", _FLEISCH, "", "tomate hunde katzen kau", True),
    "wurst": ("wurst aufschnitt wurstchen", _WURST, "", "hunde katzen kau", True),
    "fisch": ("fisch fische", _FISCH, "", "fischer futter hunde katzen", True),
    "kase": ("kase", "Käse", "", "kuchen", True),
    "milchprodukte": ("milchprodukte molkerei molkereiprodukte", _MOLKEREI, "", "", True),
    "obst": ("obst fruchte frischobst", _OBST, "",
             "hulsenfruchte tee schale korb presse fliege obstler", True),
    "gemuse": ("gemuse frischgemuse", _GEMUESE, "",
               "bruhe chips hobel schneider reibe spiralschneider", True),
    "brot": ("brot brote vollkornbrot mischbrot roggenbrot weizenbrot toastbrot toast baguette ciabatta "
             "brezel brezeln", "Brot|Brötchen", "",
             "aufstrich korb dose messer kasten schneide automat toaster", True),
    "backwaren": ("backwaren feingeback", "Brot|Brötchen|Kuchen & Feinbackwaren|Tiefkühlbackwaren & -feingebäck",
                  "", "", True),
    "sussigkeiten": ("sussigkeiten susses suswaren sussware naschen nascherei", "Schokoladen|Fruchtgummi|Kekse",
                     "", "", True),
    "snacks": ("snacks snack knabbern knabbereien knabberzeug", "Chips|Knabbereien|Nüsse|Popcorn|Salzgebäck",
               "", "", True),
    "tiefkuhl": ("tiefkuhl tiefkuhlkost tiefgekuhlt tk", "Eis|Tiefkühlbackwaren & -feingebäck|"
                 "Tiefkühlfisch und Meeresfrüchte|Tiefkühlfleisch|Tiefkühlgemüse|Tiefkühlgerichte|"
                 "Tiefkühlkartoffeln|Tiefkühlobst|Tiefkühlpizza & -flammkuchen", "",
                 "schrank truhe kombi gerat", True),
    "konserven": ("konserve konserven", "Dosengerichte|Fischkonserven|Gemüsekonserven|Obstkonserven|"
                  "Wurst- und Fleischkonserven", "", "", True),
    "gewurze": ("gewurze gewurz", "Gewürzmischungen|Pfeffer|Röstzwiebel|Salz", "", "gurke", True),
    "musli": ("musli cornflakes cerealien", "Müslimischungen|Müsliriegel", "", "schale cup dose becher", True),
    "aufstrich": ("aufstrich brotaufstrich marmelade konfiture", "Honig|Marmeladen|Schokoaufstrich|"
                  "herzhafte Aufstriche", "", "", True),
    "baby": ("baby babyartikel babybedarf", "Babynahrung|Babypflege|Windeln|Schnuller|Schwangerschaft", "",
             "babybel spinat salat mais ananas mohren karotten kartoffel", True),
    "kosmetik": ("kosmetik schminke makeup", "Augen Makeup|Lippenstifte|Makeup Zubehör|Nagellack|"
                 "Teints Tönungen", "", "", True),
    "parfum": ("parfum parfums eaudetoilette eaudeparfum dufte", "Damen Düfte|Duftsets|Herren Düfte", "",
               "", True),
    "medikamente": ("medikamente medikament arznei arzneimittel apotheke", "Antiallergika|Alternativmedizin|"
                    "Augen-, Nasen-, & Ohrenmedikamente|Bandagen|Schlafmittel|Dampfinhalatoren|Diabetes|"
                    "Erste-Hilfe|Haut-, Haar- & Nagelpflegeartikel|Herz-, Kreislauf- & Gefäßmedikamente|"
                    "Magen & Darm Medikamente|Medizinische Geräte & Verbrauchsmaterialien|Schmerz- & Fiebermittel|"
                    "Pflaster & Verbandsmaterial|Wundheilmittel|Erkältungsmittel & Abwehrstärkung", "", "", True),
    "tierfutter": ("tierfutter tiernahrung futter", _TIERFUTTER, "", "", False),
    "tierbedarf": ("tierbedarf haustier haustiere zoobedarf", _TIERFUTTER + "|Hundezubehör|Katzenzubehör",
                   "", "", False),
    "katzenfutter": ("katzenfutter katzennahrung katzensnack katzensnacks", "Katzenfutter", "", "", False),
    "hundefutter": ("hundefutter hundenahrung hundesnack hundesnacks", "Hundefutter", "", "", False),
}

# Weitere Marken je Sorte (Hersteller- und Handelsmarken); sie zählen nur in der passenden Kategorie,
# darum stören auch kurze Namen wie „lea“ (Jolea) nicht.
_MARKEN_MEHR = {
    "duschgel": ("lea tesori kuhne sebamed lavera vaseline speick weleda nuxe alterra cadea "
                 "sunozon lux hidrofugal baylis badedas tetesept bebe 4711 timotei dermasan rexona"),
    "shampoo": ("john frieda cantu aussie ogx palette wella schwarzkopf loreal maybelline clairol "
                "tresemme timotei sebamed lavera logona alterra dermasel kerastase redken lea dzl "
                "cien"),
    "spulung": ("john frieda cantu aussie ogx wella tresemme timotei sebamed lavera redken "
                "kerastase lea dzl cien loreal"),
    "haarspray": "wellaflex studioline vo5 tresemme osis indola cien lea schwarzkopf loreal",
    "deo": ("lea hidrofugal sebamed lavera weleda logona vichy sanex vaseline tetesept fenjal "
            "pitralon tabac playboy brut intesa nuxe cien alterra"),
    "zahnpasta": ("prokudent lacalut dentalux curaprox biorepair swissmile bioniq tetesept cien "
                  "lea wolff pronamel"),
    "zahnburste": ("prokudent curaprox tepe jordan lacalut dentalux waterpik curaden trisa ixs "
                   "willowbrook cien"),
    "mundspulung": ("prokudent lacalut sensodyne aronal parodontax ajona dentalux wolff cien "
                    "chlorhexamed corsodyl dentagard"),
    "seife": ("lea alterra nevernot sebamed lavera speick weleda dettol fenjal kamill dermasan "
              "sunozon cien domol nuxe"),
    "bodylotion": ("lea isana cien alterra weleda diadermine mixa vaseline fenjal vichy sebamed "
                   "lavera tetesept baylis aveeno cetaphil bepanthen ladival olaz olay uriage "
                   "glysolid"),
    "rasierer": "estrid smartwaxx remington panasonic veet braun philips proraso barbasol",
    "sonnencreme": ("delial bilou lavozon sunozon asience hawaiian tropic bioderma eucerin cien "
                    "isana lea sanosan lavera alverde garnier"),
    "windeln": "bella babydream dada fixies libero cien naturababy",
    "damenhygiene": ("bella facelle tena camelia liasan naturella kotex natracare tampax bodyform "
                     "cien lea"),
    "toilettenpapier": ("alouette favora cottonelle goldeimer kokett lambi servus fripa softis "
                        "kleenex regina"),
    "kuchenrolle": "alouette favora floralys kokett fripa lambi regina servus vileda",
    "taschentucher": "lea domol floralys kokett alouette fripa",
    "waschmittel": "vanish domol beckmann ecover purex dalli denkmit paradies kuschelweich lea",
    "weichspuler": "domol tandil formil coral denkmit fewa perwoll yvette",
    "spulmittel": "somat finish domol denkmit ecover calgon",
    "spultabs": "domol denkmit ecover glorix",
    "reiniger": ("beckmann mellerud flink danklorix domol febreze maxx kaltenbach dettol antikal "
                 "jeyes denkmit ecover glorix sanytol viakal bagno vileda leifheit"),
    "mullbeutel": "toppits rubin priva domol fripa",
    "batterien": "rubin solakon ultralife camelion ansmann eneloop maxell",
    "kaffee": ("starbucks rostfein laudatio nestle maxwell tassimo illy kimbo eilles boyens "
               "darboven alnatura"),
    "tee": ("goldmunchen twinings pickwick heilbrunner althaus dethlefsen ronnefeldt halssen kusmi "
            "sonnentor"),
    "nudeln": "miracoli steinhaus combino rapunzel alnatura",
    "joghurt": ("milbona sachsenmilch arla yoplait activia actimel landliebe alpro sojade "
                "andechser"),
    "schokolade": ("ferrero favorina storck snickers toblerone quendt trumpf marabou chocolonely "
                   "balisto schogetten hachez sarotti leonidas moser carre bounty twix duplo "
                   "hanuta raffaello rocher kitkat nestle guylian villars freia cadbury hershey "
                   "ovomaltine rausch schneekoppe milkybar"),
    "chips": ("takis clarky clarkys lorenz kellogg doritos ruffles tyrrells sunbites zweifel "
              "estrella intersnack"),
    "bier": ("hasseroder heineken anheuser mauritius jever schaferhofer budweiser budvar tyskie "
             "schultheiss holzkirchner gosser stortebeker radeberger carlsberg corona desperados "
             "franziskaner hacker pschorr lowenbrau augustiner hofbrau tegernseer kulmbacher "
             "flensburger clausthaler benediktiner astra holsten bernard grolsch guinness leffe "
             "hoegaarden kolsch gaffel reissdorf wernesgruner freiberger bischoff"),
    "butter": "latta arla anchor president milbona alnatura weidegluck",
    "milch": "muller sachsenmilch milram berchtesgadener oatly alpro schwarzwaldmilch arla",
    "katzenstreu": "biokat catsan chicopee tigerino tierfreund vitakraft sanicat",
    "katzenfutter": ("whiskas sheba felix kitekat purina dreamies animonda carny rinti miamor "
                     "schmusy bozita applaws canin brekkies carno cosma catessy vitakraft multifit "
                     "selectgold winston bosch petfood sanabelle smilla josera iams eukanuba catz "
                     "finefood"),
    "hundefutter": ("pedigree chappi cesar frolic rinti purina animonda carny canin bosch petfood "
                    "selectgold wolfsblut belcando josera eukanuba clauders markus multifit "
                    "procani winston thempa 8in1 dibo adventuros chewies christopherus smoothiedog "
                    "nutrimento savanna olewo bellfor acana orijen yarrah mjamo wildborn schesir "
                    "vitakraft"),
}

# Marken mit mehreren Schreibweisen: alle Varianten zeigen auf dieselbe Liste
_MARKEN_ALIAS = [
    "headshoulders headundshoulders headandshoulders",
    "blendamed blendamed blend a med",
    "oralb oral b",
    "8x4 achtmalvier",
    "weisserriese weisser riese",
    "coca cola cocacola coke",
    "lenor",
    "nescafe nescafe",
    "drbest dr best",
    "wcente wc ente",
]


def _terme(text):
    return [t for t in dict.fromkeys(text.split()) if t]


def _vorbereiten():
    typen = {}
    for name, (alts, kats, marken, ohne, drogerie) in _TYPEN.items():
        typen[name] = {
            "name": name,
            "alts": set(_terme(alts)) | {name},
            "kats": {kompakt(k) for k in kats.split(",") if k.strip()},
            "voll": set(),
            "ober": False,
            "marken": set(_terme(marken + " " + _MARKEN_MEHR.get(name, ""))),
            "ohne": set(_terme(ohne)),
            "drogerie": drogerie,
        }
    for name, (alts, kats, marken, ohne, drogerie) in _OBER.items():
        voll = {kompakt(k) for k in kats.split("|") if k.strip()}
        typen[name] = {
            "name": name,
            "alts": set(_terme(alts)) | {name},
            "kats": voll,
            "voll": voll,
            "ober": True,
            "marken": set(_terme(marken + " " + _MARKEN_MEHR.get(name, ""))),
            "ohne": set(_terme(ohne)),
            "drogerie": drogerie,
        }
    alias = {}
    for zeile in _MARKEN_ALIAS:
        vs = set(_terme(zeile))
        for v in vs:
            alias.setdefault(v, set()).update(vs)
    return typen, alias


TYPEN, ALIAS = _vorbereiten()
ALLE_BEGRIFFE = sorted({t for ty in TYPEN.values() for t in ty["alts"] | ty["marken"]} | set(ALIAS))

# So heißen die Sorten auf dem Bildschirm (die Schlüssel oben sind ohne Umlaute)
_ANZEIGE = {"spulung": "Spülung", "zahnburste": "Zahnbürste", "mundspulung": "Mundspülung",
            "kuchenrolle": "Küchenrolle", "taschentucher": "Taschentücher", "weichspuler": "Weichspüler",
            "spulmittel": "Spülmittel", "spultabs": "Spültabs", "mullbeutel": "Müllbeutel",
            "brotchen": "Brötchen", "bodylotion": "Bodylotion & Creme", "getranke": "Getränke",
            "kase": "Käse", "obst": "Obst", "gemuse": "Gemüse", "sussigkeiten": "Süßigkeiten",
            "tiefkuhl": "Tiefkühlware", "gewurze": "Gewürze", "musli": "Müsli", "parfum": "Parfüm",
            "aufstrich": "Brotaufstrich"}

# Verwandte Sorten: Wer Duschgel sucht, dem hilft vielleicht auch eine stark reduzierte Seife.
_BEREICHE = {
    "Körperpflege": "duschgel seife bodylotion deo rasierer sonnencreme",
    "Haarpflege": "shampoo spulung haarspray",
    "Zahnpflege": "zahnpasta zahnburste mundspulung",
    "Baby & Hygiene": "windeln damenhygiene",
    "Papierwaren": "toilettenpapier kuchenrolle taschentucher",
    "Wäsche": "waschmittel weichspuler",
    "Spülen & Putzen": "spulmittel spultabs reiniger mullbeutel",
    "Kaffee & Tee": "kaffee tee",
    "Milchprodukte": "sahne quark joghurt butter milch",
    "Knabbern & Naschen": "schokolade chips",
    "Getränke": "cola bier",
}
BEREICH = {s: b for b, ss in _BEREICHE.items() for s in ss.split()}


def anzeige(name):
    """Sorte für den Bildschirm: „spulung“ → „Spülung“."""
    return _ANZEIGE.get(name) or name[:1].upper() + name[1:]


def nachbarn(name):
    """Verwandte Sorten aus demselben Bereich (ohne die Sorte selbst)."""
    b = BEREICH.get(name)
    return [s for s in _BEREICHE[b].split() if s != name] if b else []


def _pruefer(t):
    """Prüfung für einen Begriff: kurze Begriffe nur am Wortanfang (≤3 Zeichen: ganzes Wort), damit
    „deo“ nicht in „Video“ und „fa“ nicht in „Fanta“ steckt; längere überall (auch in Komposita)."""
    if len(t) <= 3:
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")
        return lambda sp, ko: rx.search(sp) is not None
    if len(t) == 4:
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(t))
        return lambda sp, ko: rx.search(sp) is not None
    return lambda sp, ko: t in ko


def _stamm(t):
    """Einfache Plural-/Endungsvarianten: „tomaten“ findet auch „Rispentomate“."""
    # nur eine Endung abschneiden – „tomat“ steckte sonst in „Kaffeevollautomat“
    return [t, t[:-1]] if len(t) >= 6 and t[-1] in "nse" else [t]


# ── Angebote vorbereiten (einmal je Angebot) ─────────────────────────────────
_CACHE = {}


def felder(o):
    """Normalisierte Texte eines Angebots, zwischengespeichert (Schlüssel: Objekt-Identität)."""
    hit = _CACHE.get(id(o))
    if hit is not None and hit[0] is o:
        return hit[1]
    if len(_CACHE) > 40000:
        _CACHE.clear()
    pm = norm(f"{o.get('marke') or ''} {o.get('produkt') or ''}")
    info = norm(o.get("info") or "")
    kat = norm(o.get("kategorie") or "")
    f = (pm, pm.replace(" ", ""), info, info.replace(" ", ""), kat, kat.replace(" ", ""),
         norm(o.get("marke") or ""), o.get("branche") or "")
    _CACHE[id(o)] = (o, f)
    return f


# ── Suchbegriff ──────────────────────────────────────────────────────────────
class _Gruppe:
    """Ein Wort der Eingabe samt allen Sorten, Schreibweisen und Marken, die dazugehören."""

    def __init__(self, wort):
        self.wort = wort
        self.typen = [ty for ty in TYPEN.values() if self._passt_typ(wort, ty)]
        alts = set(_stamm(wort))
        marken, kats, voll, ohne = set(), set(), set(), set()
        self.drogerie = bool(self.typen) and all(ty["drogerie"] for ty in self.typen)
        for ty in self.typen:
            alts |= ty["alts"]
            marken |= ty["marken"]
            kats |= ty["kats"]
            voll |= ty["voll"]
            ohne |= ty["ohne"]
        alts |= ALIAS.get(wort, set())
        ohne = {w for w in ohne if w not in wort}
        # Sorten-Wörter der Nachbarn in derselben Kategorie: „Syoss Haarspray“ ist zwar eine Haarpflege-
        # Marke, aber kein Shampoo – die Marken-Regel greift nur, wenn kein fremdes Sorten-Wort dasteht.
        self.fremd = sorted({a for ty in TYPEN.values()
                             if ty not in self.typen and not ty["ober"] and ty["kats"] & kats
                             for a in ty["alts"] if len(a) >= 5} - alts)
        self.alts = [_pruefer(t) for t in sorted(alts)]
        self.marken = [_pruefer(t) for t in sorted(marken)]
        self.kats = kats
        self.voll = voll
        self.ohne = sorted(ohne)
        # Oberbegriffe nicht im Info-Text suchen: „Alkohol“ stünde sonst bei jedem „alkoholfrei“
        self.info = not (self.typen and all(ty["ober"] for ty in self.typen))

    @staticmethod
    def _passt_typ(w, ty):
        if w in ty["alts"]:
            return True
        # angefangenes Wort: „dusch“ → Duschgel, „zahnp“ → Zahnpasta (nur gegen den Namen der Sorte,
        # sonst landete „creme“ über „Cremedusche“ bei den Duschgels). Oberbegriffe nur ganz – „Milch“
        # soll nicht alle Milchprodukte bringen.
        return len(w) >= 4 and not ty["ober"] and ty["name"].startswith(w)

    def punkte(self, f):
        """0 = passt nicht; 3 = Treffer im Produkt/der Kategorie (beim Oberbegriff: eine seiner
        Kategorien), 2 = bekannte Marke dieser Sorte,
        1 = nur im Info-Text (z. B. „oder Spülung“)."""
        pm, pmk, info, infok, kat, katk, marke, branche = f
        if self.drogerie and branche.startswith(_NICHT_DROGERIE):
            return 0
        if self.ohne and any(w in pmk for w in self.ohne):
            return 0
        if katk in self.voll:
            return 3
        for p in self.alts:
            if p(pm, pmk) or p(kat, katk):
                return 3
        if self.marken and katk in self.kats and not any(w in pmk for w in self.fremd):
            for p in self.marken:
                if p(pm, pmk):
                    return 2
        if self.info:
            for p in self.alts:
                if p(info, infok):
                    return 1
        return 0


class Suche:
    """Suchbegriff aus der Eingabe. passt(o) → Punkte (0 = kein Treffer); alle Wörter müssen passen."""

    def __init__(self, text):
        self.text = " ".join((text or "").split())
        n = norm(self.text)
        ganz = n.replace(" ", "")
        # Mehrwort-Begriffe aus der Tabelle („wc papier“, „head & shoulders“) als ein Wort behandeln
        if " " in n and (ganz in ALIAS or any(ganz in ty["alts"] for ty in TYPEN.values())):
            woerter = [ganz]
        else:
            woerter = n.split()
        self.gruppen = [_Gruppe(w) for w in woerter]
        self.sorten = sorted({name for g in self.gruppen for name, ty in TYPEN.items() if ty in g.typen})
        # Marken in der Eingabe („axe“, „head & shoulders“): zu welchen Sorten gehören sie? – für die
        # Alternativen
        roh = set(n.split())
        self.marken_sorten = sorted({
            name for name, ty in TYPEN.items()
            if any(({g.wort} | ALIAS.get(g.wort, set())) & ty["marken"] for g in self.gruppen)
            or (roh and roh <= ty["marken"])})

    def __bool__(self):
        return bool(self.gruppen)

    def passt(self, o):
        f = felder(o)
        summe = 0
        for g in self.gruppen:
            p = g.punkte(f)
            if not p:
                return 0
            summe += p
        return summe


def vorschlag(text, angebote):
    """Bei Tippfehlern: ähnlich geschriebene Suche („shampo“ → „shampoo“) oder None.
    Nur aufrufen, wenn die Suche nichts gefunden hat – das ist der teure Teil."""
    woerter = norm(text).split()
    if not woerter:
        return None
    vokabel = set(ALLE_BEGRIFFE)
    for o in angebote:
        f = felder(o)
        vokabel.update(w for w in f[0].split() if len(w) >= 4)
        vokabel.update(w for w in f[4].split() if len(w) >= 4)
    neu, geaendert = [], False
    for w in woerter:
        if w in vokabel or len(w) < 4:
            neu.append(w)
            continue
        # Tippfehler stecken selten im ersten Buchstaben – „gurkenwasser“ ist kein „rosenwasser“
        m = difflib.get_close_matches(w, [v for v in vokabel if v[:1] == w[:1]], n=1, cutoff=0.82)
        if m:
            neu.append(m[0])
            geaendert = True
        else:
            neu.append(w)
    return " ".join(neu) if geaendert else None
