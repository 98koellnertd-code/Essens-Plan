"""Update über GitHub-Releases.

Zwei Betriebsarten, weil beide etwas völlig anderes brauchen:

* Als EXE steckt Python samt aller Bibliotheken fest in der Datei – es gibt kein pip
  darin. Das einzig mögliche Update ist, die EXE gegen eine neue zu tauschen. Windows
  sperrt die laufende Datei, darum lädt das Programm die neue Version daneben, schreibt
  ein kleines Hilfsskript, beendet sich, und das Skript tauscht und startet neu.
* Als Quelltext (START.bat) kann pip die Bibliotheken aktualisieren; Python selbst wird
  nie automatisch installiert, dafür gibt es nur den Hinweis mit Link.

Geladen wird ausschließlich über HTTPS von GitHub, und niemals ohne Rückfrage.
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse

import requests

import utils

GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"
RELEASE_SEITE = "https://github.com/{repo}/releases/latest"
# Nur von diesen Hosts wird geladen – so kann ein manipuliertes Release die EXE nicht
# von irgendeiner fremden Adresse nachladen.
ERLAUBTE_HOSTS = ("github.com", "api.github.com", "codeload.github.com",
                  "objects.githubusercontent.com", "release-assets.githubusercontent.com")
LIBS = ("requests", "reportlab", "pillow")     # die wichtigen: Netzwerk, PDF, Bilder
MIN_PYTHON = (3, 9)
PYTHON_URL = "https://www.python.org/downloads/"
TIMEOUT = 20
KEIN_FENSTER = 0x08000000


# ─── Versionen ────────────────────────────────────────────────────────────────
def ver(text):
    """„v1.12.0-beta“ → (1, 12, 0). Unlesbares wird zu (0,) und gilt damit als älteste."""
    zahlen = re.findall(r"\d+", str(text or "").split("+")[0])
    return tuple(int(z) for z in zahlen[:4]) or (0,)


def ist_neuer(fremd, eigen):
    a, b = ver(fremd), ver(eigen)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def repo_name(text):
    """Nimmt „benutzer/projekt“ oder eine GitHub-Adresse und gibt „benutzer/projekt“ zurück."""
    t = (text or "").strip().rstrip("/")
    if not t:
        return ""
    if "github.com" in t:
        t = t.split("github.com", 1)[1].lstrip(":/")
        t = "/".join(t.split("/")[:2])
    if t.endswith(".git"):
        t = t[:-4]
    return t if re.fullmatch(r"[\w.-]+/[\w.-]+", t) else ""


def _sicher(url):
    p = urllib.parse.urlparse(url or "")
    return p.scheme == "https" and p.hostname in ERLAUBTE_HOSTS


def frozen():
    return getattr(sys, "frozen", False)


# ─── Release abfragen ─────────────────────────────────────────────────────────
def check(repo_text, aktuelle_version):
    """Fragt das neueste Release ab. Gibt ein dict zurück oder wirft RuntimeError."""
    repo = repo_name(repo_text)
    if not repo:
        raise RuntimeError("Kein gültiges GitHub-Projekt hinterlegt (Format: benutzer/projekt).")
    kopf = {"Accept": "application/vnd.github+json",
            "User-Agent": f"Essens-Plan/{aktuelle_version}",
            "X-GitHub-Api-Version": "2022-11-28"}
    try:
        r = requests.get(GITHUB_API.format(repo=repo), headers=kopf, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"Keine Verbindung zu GitHub: {e}")
    if r.status_code == 404:
        raise RuntimeError(f"Kein Release gefunden. Prüfe, ob „{repo}“ stimmt, öffentlich ist "
                           "und dort schon ein Release veröffentlicht wurde.")
    if r.status_code == 403:
        raise RuntimeError("GitHub bremst gerade (zu viele Abfragen). Bitte später erneut versuchen.")
    if r.status_code != 200:
        raise RuntimeError(f"GitHub antwortete mit Fehler {r.status_code}.")
    try:
        d = r.json()
    except json.JSONDecodeError:
        raise RuntimeError("Die Antwort von GitHub war unlesbar.")

    exe = None
    for a in d.get("assets") or []:
        if str(a.get("name", "")).lower().endswith(".exe") and _sicher(a.get("browser_download_url")):
            exe = {"name": a["name"], "url": a["browser_download_url"], "size": a.get("size") or 0}
            break
    tag = d.get("tag_name") or d.get("name") or ""
    return {"repo": repo, "tag": tag, "version": ".".join(str(z) for z in ver(tag)),
            "titel": d.get("name") or tag, "notizen": (d.get("body") or "").strip(),
            "seite": d.get("html_url") or RELEASE_SEITE.format(repo=repo),
            "asset": exe, "neu": ist_neuer(tag, aktuelle_version)}


# ─── Herunterladen und tauschen ───────────────────────────────────────────────
def _weg(pfad):
    """Halbe Datei wegräumen – ein Fehlschlag darf den eigentlichen Grund nicht verdecken."""
    try:
        os.remove(pfad)
    except OSError:
        pass


def download(asset, ziel, prog=None, exe=True):
    """Lädt das Release-Paket nach ziel. prog(geladen, gesamt) darf None sein.

    exe=False ist nur zum Testen da – dann entfällt die Prüfung auf ein Windows-Programm."""
    if not _sicher(asset.get("url")):
        raise RuntimeError("Die Download-Adresse gehört nicht zu GitHub – abgebrochen.")
    gesamt, geladen = int(asset.get("size") or 0), 0
    with requests.get(asset["url"], stream=True, timeout=TIMEOUT,
                      headers={"User-Agent": "Essens-Plan"}) as r:
        r.raise_for_status()
        gesamt = int(r.headers.get("Content-Length") or gesamt)
        with open(ziel, "wb") as f:
            for stueck in r.iter_content(256 * 1024):
                f.write(stueck)
                geladen += len(stueck)
                if prog:
                    prog(geladen, gesamt)
    if gesamt and os.path.getsize(ziel) != gesamt:
        _weg(ziel)
        raise RuntimeError("Der Download ist unvollständig – bitte erneut versuchen.")
    if exe:
        with open(ziel, "rb") as f:
            kopf = f.read(2)                         # erst schließen, dann löschen
        if kopf != b"MZ":                            # jede Windows-EXE beginnt so
            _weg(ziel)
            raise RuntimeError("Die geladene Datei ist kein Windows-Programm – abgebrochen.")
    return ziel


HELFER = """@echo off
rem Die Pfade kommen als Umgebungsvariablen (EP_ALT, EP_NEU, EP_BAK, EP_LOG, EP_DIR, EP_BAT, EP_PID).
rem So stimmen auch Umlaute im Benutzernamen - egal, mit welcher Codepage cmd diese Datei liest.
set /a N=0
rem Erst warten, bis das Programm wirklich beendet ist. Windows erlaubt zwar, eine
rem laufende EXE umzubenennen - dann liefen aber kurz zwei Programme nebeneinander.
:warten
ping -n 2 127.0.0.1 >nul
tasklist /nh /fi "pid eq %EP_PID%" 2>nul | find "%EP_PID%" >nul
if errorlevel 1 goto tauschen
set /a N+=1
if %N% LSS 150 goto warten
goto abbruch
:tauschen
set /a M=0
:versuch
del "%EP_BAK%" >nul 2>&1
move /y "%EP_ALT%" "%EP_BAK%" >nul 2>&1
if not errorlevel 1 goto ersetzen
set /a M+=1
if %M% GEQ 20 goto abbruch
ping -n 2 127.0.0.1 >nul
goto versuch
:ersetzen
move /y "%EP_NEU%" "%EP_ALT%" >nul 2>&1
if errorlevel 1 goto zurueck
del "%EP_LOG%" >nul 2>&1
start "" "%EP_ALT%"
rem Die Sicherung loeschen. Das alte Programm raeumt nach seinem Ende noch seinen Temp-Ordner
rem auf und haelt die Datei so lange fest - darum notfalls eine halbe Minute lang wiederholen.
set /a K=0
:sicherung
del "%EP_BAK%" >nul 2>&1
if not exist "%EP_BAK%" goto ende
set /a K+=1
if %K% GEQ 30 goto ende
ping -n 2 127.0.0.1 >nul
goto sicherung
:zurueck
move /y "%EP_BAK%" "%EP_ALT%" >nul 2>&1
start "" "%EP_LOG%"
if exist "%EP_ALT%" start "" "%EP_ALT%"
goto ende
:abbruch
start "" "%EP_LOG%"
:ende
rem Sich selbst loeschen und den Download-Ordner gleich mit (rd nimmt ihn nur, wenn er leer ist -
rem nach einem Fehlschlag liegen die neue EXE und der Hinweis noch darin und bleiben erhalten).
(goto) 2>nul & del "%~f0" & rd "%EP_DIR%" 2>nul
"""


def tausche_und_starte(neue_datei, alt=None, pid=None):
    """Startet das Hilfsskript, das nach dem Programmende die EXE ersetzt und neu startet.

    Danach muss sich das Programm sofort beenden – sonst wartet das Skript vergeblich.
    alt und pid sind nur zum Testen da; normal sind es die laufende EXE und ihre Prozess-ID."""
    alt = os.path.abspath(alt or sys.executable)
    neu = os.path.abspath(neue_datei)
    ordner = os.path.dirname(neu)
    bat = os.path.join(ordner, "essens-plan-update.cmd")
    log = os.path.join(ordner, "Update fehlgeschlagen.txt")
    # Den Hinweis für den Fehlerfall schreibt Python vorab (mit BOM, damit der Editor die Umlaute
    # richtig zeigt); das Skript öffnet ihn nur noch oder löscht ihn nach geglücktem Tausch.
    with open(log, "w", encoding="utf-8-sig") as f:
        f.write("Das Update konnte nicht eingespielt werden.\n\n"
                f"Die neue Version liegt hier:\n{neu}\n\n"
                f"Du kannst sie von Hand an diese Stelle kopieren:\n{alt}\n")
    with open(bat, "w", encoding="ascii", newline="\r\n") as f:
        f.write(HELFER)
    # Saubere Umgebung: das Skript startet die neue EXE unter demselben Pfad, und mit geerbten
    # PyInstaller-Variablen liefe sie aus dem Temp-Ordner der alten (der dann weg ist).
    env = utils.saubere_umgebung()
    env.update(EP_ALT=alt, EP_NEU=neu, EP_BAK=alt + ".alt", EP_LOG=log, EP_DIR=ordner,
               EP_BAT=bat, EP_PID=str(pid or os.getpid()))
    # Nur KEIN_FENSTER: ein abgekoppelter Prozess hat keine Konsole, und ohne Konsole
    # bleibt tasklist einfach hängen – damit wäre das Update nie eingespielt worden.
    # Arbeitsordner ist der Ordner der EXE, nicht der Download-Ordner: den könnte das Skript
    # sonst nie wegräumen, und die neue EXE startet so wie nach einem Doppelklick.
    # Auch der Skriptpfad kommt als Variable: stünde er direkt hinter /c, würfe cmd bei einem
    # „&“ oder Klammern im Pfad die Anführungszeichen weg und fände das Skript nicht.
    cmd = os.environ.get("COMSPEC") or "cmd.exe"
    utils.starte_unabhaengig(f'"{cmd}" /d /s /c ""%EP_BAT%""', cwd=os.path.dirname(alt), env=env,
                             creationflags=KEIN_FENSTER)
    return bat


# ─── Bibliotheken und Python (nur im Quelltext-Betrieb sinnvoll) ───────────────
def python_info():
    v = sys.version_info[:3]
    return {"version": ".".join(str(x) for x in v),
            "alt": v[:2] < MIN_PYTHON,
            "mindest": ".".join(str(x) for x in MIN_PYTHON),
            "url": PYTHON_URL}


def lib_status(prog=None):
    """Je wichtiger Bibliothek: installierte Version und die neueste auf PyPI."""
    from importlib import metadata
    out = []
    for i, name in enumerate(LIBS):
        try:
            da = metadata.version(name)
        except Exception:
            da = ""
        neu = ""
        try:
            r = requests.get(f"https://pypi.org/pypi/{name}/json", timeout=TIMEOUT,
                             headers={"User-Agent": "Essens-Plan"})
            if r.status_code == 200:
                neu = r.json()["info"]["version"]
        except Exception:
            pass
        out.append({"name": name, "da": da, "neu": neu,
                    "veraltet": bool(da and neu and ist_neuer(neu, da))})
        if prog:
            prog(i + 1, len(LIBS))
    return out


def pip_upgrade(namen):
    """pip install --upgrade für die genannten Pakete. Gibt (ok, Ausgabe) zurück."""
    if frozen():
        return False, "In der EXE steckt kein pip – die Bibliotheken kommen mit einer neuen EXE."
    if not namen:
        return True, "Nichts zu tun."
    try:
        p = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade",
                            "--disable-pip-version-check", *namen],
                           capture_output=True, text=True, timeout=600,
                           creationflags=KEIN_FENSTER)
    except Exception as e:
        return False, str(e)
    aus = (p.stdout or "") + (p.stderr or "")
    zeilen = [z for z in aus.splitlines() if z.strip()][-12:]
    return p.returncode == 0, "\n".join(zeilen) or "Fertig."
