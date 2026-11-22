"""Release-Skript für den Essens-Plan: bauen, SHA-256-Prüfsummen, Release-Notiz, Veröffentlichung.

  py -3 scripts\\release.py                  Trockenlauf: baut, rechnet, prüft, schreibt die Notiz
  py -3 scripts\\release.py --publish        zusätzlich Tag, Push und GitHub-Release + Gegenprobe
  py -3 scripts\\release.py --skip-build     vorhandenes dist\\ verwenden (kein BUILD.bat)
  py -3 scripts\\release.py --verify v1.5.3  nur die Gegenprobe für ein bestehendes Release

Nur Standardbibliothek; für GitHub wird die „gh“-CLI gebraucht (nur bei --publish/--verify).
Jeder Fehler bricht mit Exit-Code 1 ab.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:                                   # Umlaute auch in einer Konsole mit alter Codepage
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
EXE, ZIP, PDF = "Essens-Plan.exe", "Essens-Plan.zip", "Anleitung.pdf"
DATEIEN = (EXE, ZIP, PDF)             # Reihenfolge = Reihenfolge in Summen und Tabelle
SUMMEN = "SHA256SUMS.txt"


class Abbruch(Exception):
    pass


def schritt(n, text):
    print(f"\n[{n}] {text}")


def ok(text):
    print(f"    OK  {text}")


def hinweis(text):
    print(f"    ..  {text}")


def fehler(text):
    raise Abbruch(text)


# ─── Hilfen ───────────────────────────────────────────────────────────────────
def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for stueck in iter(lambda: f.read(1024 * 1024), b""):
            h.update(stueck)
    return h.hexdigest()


def lauf(args, **kw):
    """Führt einen Befehl aus und gibt (Exit-Code, Ausgabe) zurück."""
    try:
        p = subprocess.run(args, cwd=kw.pop("cwd", ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        fehler(f"Programm nicht gefunden: {args[0]}")
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def muss(args, was):
    rc, aus = lauf(args)
    if rc != 0:
        fehler(f"{was} fehlgeschlagen (Exit-Code {rc}).\n{aus}")
    return aus


def gh_pfad():
    p = shutil.which("gh")
    if not p:
        fehler("Die GitHub-CLI „gh“ fehlt oder ist nicht im PATH (https://cli.github.com, danach „gh auth login“).")
    return p


# ─── Version und Voraussetzungen ──────────────────────────────────────────────
def app_version():
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as f:
        m = re.search(r'^APP_VERSION\s*=\s*["\'](\d+\.\d+\.\d+)["\']', f.read(), re.M)
    if not m:
        fehler("APP_VERSION in app.py nicht gefunden (erwartet z. B. APP_VERSION = \"1.5.3\").")
    return m.group(1)


def version_info_pruefen(version, korrigieren):
    pfad = os.path.join(ROOT, "version_info.txt")
    with open(pfad, encoding="utf-8") as f:
        text = f.read()
    teile = version.split(".")
    vier = ", ".join(teile + ["0"])
    soll = text
    soll = re.sub(r"(filevers=|prodvers=)\([^)]*\)", lambda m: f"{m.group(1)}({vier})", soll)
    soll = re.sub(r"(StringStruct\('(?:FileVersion|ProductVersion)', ')[^']*(')",
                  lambda m: f"{m.group(1)}{version}.0{m.group(2)}", soll)
    if soll == text:
        ok(f"version_info.txt passt (Version {version})")
        return
    if not korrigieren:
        fehler(f"version_info.txt passt nicht zur App-Version {version}. "
               "Mit --fix-version-info anpassen lassen (danach committen) oder von Hand ändern.")
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        f.write(soll)
    ok(f"version_info.txt auf {version} geändert – bitte mit committen (Tag zeigt sonst auf den alten Stand)")


def git_pruefen(version, remote, erlaube_dreckig, publish):
    tag = f"v{version}"
    if not shutil.which("git"):
        fehler("git fehlt oder ist nicht im PATH.")
    rc, aus = lauf(["git", "status", "--porcelain"])
    if rc != 0:
        fehler(f"git status fehlgeschlagen:\n{aus}")
    if aus and not erlaube_dreckig:
        fehler("Das Git-Arbeitsverzeichnis ist nicht sauber (nicht committete Änderungen):\n"
               + "\n".join("    " + z for z in aus.splitlines()[:15])
               + "\nErst committen – oder mit --allow-dirty bewusst weitermachen.")
    ok("Git-Arbeitsverzeichnis sauber" if not aus else "Git-Arbeitsverzeichnis NICHT sauber (--allow-dirty)")
    rc, aus = lauf(["git", "tag", "--list", tag])
    if aus.strip():
        fehler(f"Der Tag {tag} existiert lokal schon. Version in app.py erhöhen (oder Tag bewusst löschen).")
    ok(f"Tag {tag} existiert lokal noch nicht")
    rc, aus = lauf(["git", "remote"])
    if remote not in aus.split():
        if publish:
            fehler(f"Es gibt kein Git-Remote „{remote}“ (git remote add {remote} <URL>).")
        hinweis(f"Kein Git-Remote „{remote}“ – Remote-Prüfung des Tags übersprungen (nur Trockenlauf)")
        return
    rc, aus = lauf(["git", "ls-remote", "--tags", remote, f"refs/tags/{tag}"])
    if rc != 0:
        fehler(f"Remote „{remote}“ nicht erreichbar:\n{aus}")
    if aus.strip():
        fehler(f"Der Tag {tag} existiert auf „{remote}“ schon. Version in app.py erhöhen.")
    ok(f"Tag {tag} existiert auf „{remote}“ noch nicht")


# ─── Bauen ────────────────────────────────────────────────────────────────────
def bauen():
    env = dict(os.environ, EP_NOPAUSE="1")
    # voller Pfad – sonst findet cmd die Datei je nach Aufrufer nicht
    p = subprocess.run(["cmd", "/c", os.path.join(ROOT, "BUILD.bat")], cwd=ROOT, env=env)
    if p.returncode != 0:
        fehler(f"BUILD.bat ist fehlgeschlagen (Exit-Code {p.returncode}).")
    ok("BUILD.bat erfolgreich")


def dateien_da():
    fehlt = [n for n in DATEIEN if not os.path.isfile(os.path.join(DIST, n))]
    if fehlt:
        fehler("In dist\\ fehlt: " + ", ".join(fehlt) + (" (ohne --skip-build baut das Skript neu)."))
    for n in DATEIEN:
        if os.path.getsize(os.path.join(DIST, n)) == 0:
            fehler(f"dist\\{n} ist leer.")
    ok("dist\\ enthält " + ", ".join(DATEIEN))


def exe_version_pruefen(version):
    """Die Versionsinfo in der EXE muss zur App-Version passen (fängt eine alte EXE in dist\\ ab)."""
    rc, aus = lauf(["powershell", "-NoProfile", "-Command",
                    f"(Get-Item -LiteralPath '{os.path.join(DIST, EXE)}').VersionInfo.ProductVersion"])
    if rc != 0 or not aus:
        hinweis("Versionsinfo der EXE nicht lesbar – übersprungen")
        return
    ist = aus.strip()
    if ist not in (version, f"{version}.0"):
        fehler(f"dist\\{EXE} trägt die Version {ist}, erwartet {version}. "
               "Das ist eine alte EXE – ohne --skip-build neu bauen.")
    ok(f"EXE trägt die Version {ist}")


# ─── Prüfsummen ───────────────────────────────────────────────────────────────
def summen_schreiben():
    zeilen = [f"{sha256(os.path.join(DIST, n))}  {n}" for n in DATEIEN]
    pfad = os.path.join(DIST, SUMMEN)
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(zeilen) + "\n")
    for z in zeilen:
        ok(z)
    return pfad


def summen_lesen(pfad):
    out = {}
    with open(pfad, encoding="utf-8-sig") as f:
        for z in f:
            m = re.fullmatch(r"\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*", z)
            if z.strip() and not m:
                fehler(f"Unlesbare Zeile in {os.path.basename(pfad)}: {z.strip()!r}")
            if m:
                out[m.group(2)] = m.group(1).lower()
    return out


def summen_pruefen(summen_pfad, ordner, erwartet=DATEIEN):
    """sha256sum -c: jede erwartete Datei muss eingetragen sein und stimmen."""
    summen = summen_lesen(summen_pfad)
    for n in erwartet:
        if n not in summen:
            fehler(f"{os.path.basename(summen_pfad)} enthält keinen Eintrag für {n}.")
        p = os.path.join(ordner, n)
        if not os.path.isfile(p):
            fehler(f"Datei fehlt zur Prüfung: {p}")
        ist = sha256(p)
        if ist != summen[n]:
            fehler(f"PRÜFSUMME FALSCH für {n}:\n    erwartet {summen[n]}\n    tatsächlich {ist}")
        ok(f"{n}: SHA-256 stimmt")
    extra = sorted(set(summen) - set(erwartet))
    if extra:
        fehler("Unerwartete Einträge in der Prüfsummendatei: " + ", ".join(extra))
    return summen


# ─── Release-Notiz ────────────────────────────────────────────────────────────
def changelog_text(version):
    pfad = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.isfile(pfad):
        fehler("CHANGELOG.md fehlt.")
    with open(pfad, encoding="utf-8") as f:
        text = f.read()
    m = re.search(rf"^##\s+v?{re.escape(version)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        fehler(f"In CHANGELOG.md gibt es keinen Abschnitt „## {version}“.")
    inhalt = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()
    if not inhalt:
        fehler(f"Der Abschnitt „## {version}“ in CHANGELOG.md ist leer – erst die Änderungen eintragen.")
    return inhalt


def notiz_schreiben(version, summen):
    zeilen = ["## Prüfsummen (SHA256)", "",
              "| Datei | Bytes | SHA256 |", "|---|---|---|"]
    for n in DATEIEN:
        zeilen.append(f"| {n} | {os.path.getsize(os.path.join(DIST, n))} | `{summen[n]}` |")
    zeilen += ["", "Prüfen unter Windows: `certutil -hashfile Essens-Plan.exe SHA256`. "
                   "Dieselben Werte stehen in `SHA256SUMS.txt`; das automatische Update prüft sie selbst."]
    pfad = os.path.join(DIST, f"Release-v{version}.md")
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write(changelog_text(version) + "\n\n" + "\n".join(zeilen) + "\n")
    ok(pfad)
    return pfad


# ─── GitHub ───────────────────────────────────────────────────────────────────
def repo_ermitteln(repo):
    if repo:
        return repo
    gh = gh_pfad()
    return muss([gh, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                "Repo ermitteln (gh repo view)").strip()


def veroeffentlichen(version, repo, remote, notiz):
    gh, tag = gh_pfad(), f"v{version}"
    muss(["git", "tag", tag], "git tag")
    ok(f"Tag {tag} gesetzt")
    muss(["git", "push", remote, "HEAD"], "git push")
    muss(["git", "push", remote, tag], "git push (Tag)")
    ok(f"Commit und Tag nach „{remote}“ geschoben")
    assets = [os.path.join(DIST, n) for n in DATEIEN] + [os.path.join(DIST, SUMMEN)]
    muss([gh, "release", "create", tag, *assets, "--repo", repo, "--title", f"Essens-Plan {tag}",
          "--notes-file", notiz, "--latest"], "gh release create")
    ok(f"Release {tag} auf {repo} angelegt")


def gegenprobe(tag, repo, lokal_summen=None):
    """Lädt die Assets des Releases neu herunter und vergleicht sie mit SHA256SUMS.txt und der API."""
    gh = gh_pfad()
    tmp = tempfile.mkdtemp(prefix="essens-plan-verify-")
    try:
        muss([gh, "release", "download", tag, "--repo", repo, "--dir", tmp, "--clobber"],
             "gh release download")
        sp = os.path.join(tmp, SUMMEN)
        if not os.path.isfile(sp):
            fehler(f"Das Release {tag} enthält kein {SUMMEN}.")
        if lokal_summen is not None and summen_lesen(sp) != lokal_summen:
            fehler("Die hochgeladene SHA256SUMS.txt weicht von der lokalen ab.")
        summen = summen_pruefen(sp, tmp)
        api = json.loads(muss([gh, "api", f"repos/{repo}/releases/tags/{tag}"], "gh api (Release)"))
        gesehen = 0
        for a in api.get("assets") or []:
            d = str(a.get("digest") or "")
            if not d:
                continue
            if not d.startswith("sha256:"):
                fehler(f"Unbekanntes digest-Format bei {a.get('name')}: {d}")
            if a["name"] in summen:
                if d[7:].lower() != summen[a["name"]]:
                    fehler(f"GitHub meldet für {a['name']} einen anderen SHA-256 als SHA256SUMS.txt:\n"
                           f"    API {d[7:]}\n    Summen {summen[a['name']]}")
                gesehen += 1
        if gesehen:
            ok(f"API-Feld „digest“ stimmt bei {gesehen} Datei(en)")
        else:
            hinweis("Die GitHub-API liefert kein „digest“-Feld – nur SHA256SUMS.txt verglichen")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─── Ablauf ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Essens-Plan: Release bauen, prüfen, veröffentlichen.")
    ap.add_argument("--publish", action="store_true", help="Tag, Push und GitHub-Release (sonst Trockenlauf)")
    ap.add_argument("--skip-build", action="store_true", help="vorhandenes dist\\ nehmen")
    ap.add_argument("--allow-dirty", action="store_true", help="auch mit nicht committeten Änderungen")
    ap.add_argument("--fix-version-info", action="store_true", help="version_info.txt auf APP_VERSION setzen")
    ap.add_argument("--verify", metavar="vX.Y.Z", help="nur die Gegenprobe für ein bestehendes Release")
    ap.add_argument("--repo", help="benutzer/projekt (sonst per gh repo view)")
    ap.add_argument("--remote", default="origin", help="Git-Remote (Standard: origin)")
    a = ap.parse_args()

    if a.verify:
        tag = a.verify if a.verify.startswith("v") else "v" + a.verify
        schritt(1, f"Gegenprobe für {tag}")
        gegenprobe(tag, repo_ermitteln(a.repo))
        print(f"\nFERTIG: {tag} stimmt mit den Prüfsummen überein.")
        return

    version = app_version()
    tag = f"v{version}"
    print(f"Essens-Plan {tag} – {'VERÖFFENTLICHUNG' if a.publish else 'Trockenlauf (lädt nichts hoch)'}")

    schritt(1, "Voraussetzungen prüfen")
    ok(f"APP_VERSION in app.py: {version}")
    if a.publish:
        gh_pfad()
    changelog_text(version)
    ok(f"CHANGELOG.md hat Text für {version}")
    git_pruefen(version, a.remote, a.allow_dirty, a.publish)
    version_info_pruefen(version, a.fix_version_info)
    repo = repo_ermitteln(a.repo) if a.publish else (a.repo or "")

    schritt(2, "Bauen" + (" (übersprungen: --skip-build)" if a.skip_build else " (BUILD.bat)"))
    if not a.skip_build:
        bauen()
    dateien_da()
    exe_version_pruefen(version)

    schritt(3, "SHA-256-Prüfsummen berechnen und gegenprüfen")
    sp = summen_schreiben()
    summen = summen_pruefen(sp, DIST)

    schritt(4, "Release-Notiz schreiben")
    notiz = notiz_schreiben(version, summen)

    if not a.publish:
        print(f"\nTROCKENLAUF FERTIG. Zum Veröffentlichen: py -3 scripts\\release.py --publish "
              f"{'--skip-build ' if a.skip_build else ''}(oder scripts\\RELEASE.bat)")
        return

    schritt(5, f"Veröffentlichen ({repo})")
    veroeffentlichen(version, repo, a.remote, notiz)

    schritt(6, "Gegenprobe: Release neu herunterladen und prüfen")
    gegenprobe(tag, repo, summen)
    print(f"\nFERTIG: {tag} ist veröffentlicht und die Prüfsummen stimmen.")


if __name__ == "__main__":
    try:
        main()
    except Abbruch as e:
        print(f"\nABBRUCH: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nABBRUCH: vom Benutzer beendet.", file=sys.stderr)
        sys.exit(1)
