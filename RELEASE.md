# Release-Ablauf

Ein Release ist ein Befehl. Voraussetzungen: `git`, `gh` (GitHub-CLI, einmal `gh auth login`), Python 3 mit den Paketen aus `requirements.txt`.

## Vorher

1. `APP_VERSION` in `app.py` erhöhen (z. B. `1.6.0`).
2. `version_info.txt` anpassen – oder das Skript mit `--fix-version-info` machen lassen.
3. In `CHANGELOG.md` den Abschnitt `## 1.6.0` mit den Änderungen füllen (leer = Abbruch).
4. Alles committen (das Skript bricht bei nicht committeten Änderungen ab, außer mit `--allow-dirty`).
   Der Git-Remote `origin` muss auf das GitHub-Projekt zeigen, aus dem die App ihre Updates holt.

## Ausführen

| Zweck | Befehl |
|---|---|
| Trockenlauf (baut, rechnet, prüft, schreibt `dist\Release-vX.Y.Z.md`, lädt nichts hoch) | `py -3 scripts\release.py` |
| Veröffentlichen (mit Rückfrage, Doppelklick möglich) | `scripts\RELEASE.bat` |
| Veröffentlichen ohne Rückfrage | `py -3 scripts\release.py --publish` |
| Vorhandenes `dist\` nehmen statt neu zu bauen | `--skip-build` |
| Nur ein bestehendes Release gegenprüfen | `py -3 scripts\release.py --verify v1.6.0` |

Weitere Optionen: `--allow-dirty`, `--fix-version-info`, `--repo benutzer/projekt`, `--remote origin`.
Für Claude oder CI: `py -3 scripts\release.py --publish`; Exit-Code 0 = alles geprüft, 1 = Abbruch (Grund steht in der Ausgabe).

## Was das Skript tut

1. Version aus `app.py`; prüft sauberes Git, Tag `vX.Y.Z` lokal und auf dem Remote noch frei, `version_info.txt`, Text in `CHANGELOG.md`.
2. `BUILD.bat` mit `EP_NOPAUSE=1` (keine „Taste drücken“-Pausen, Exit-Code ≠ 0 bei Fehler); prüft, dass die Versionsinfo der EXE zur App-Version passt.
3. SHA-256 von `Essens-Plan.exe`, `Essens-Plan.zip`, `Anleitung.pdf` → `dist\SHA256SUMS.txt` (Format `<hex>  <Dateiname>`), danach Datei neu einlesen und alle drei Dateien dagegen prüfen.
4. `dist\Release-vX.Y.Z.md`: Text aus `CHANGELOG.md` plus Tabelle Datei | Bytes | SHA256.
5. Nur mit `--publish`: Tag setzen, `git push` und Tag-Push, `gh release create` mit den drei Dateien und `SHA256SUMS.txt` (`--latest`).
6. Gegenprobe: Assets frisch herunterladen, gegen `SHA256SUMS.txt` und gegen das API-Feld `digest` prüfen. Bei Abweichung laut abbrechen – das Release dann nicht stehen lassen (löschen oder neu machen).

## Prüfsumme in der App

`update.py` lädt beim Update zusätzlich `SHA256SUMS.txt` aus demselben Release (nur von GitHub-Hosts) und vergleicht die geladene EXE damit und, falls vorhanden, mit dem `digest`-Feld der API. Fehlt die Prüfsumme oder weicht sie ab, wird die Datei gelöscht und das Update mit einer verständlichen Meldung abgebrochen. Ein Release **ohne** `SHA256SUMS.txt` lässt sich deshalb nicht mehr per Update einspielen – immer das Skript benutzen, nie von Hand hochladen. Die Datei muss `Essens-Plan.exe` heißen und in der Prüfsummendatei stehen.
