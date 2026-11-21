# Änderungsprotokoll

Je Version ein Abschnitt `## X.Y.Z`. Das Release-Skript (`scripts\release.py`) nimmt den Abschnitt
der Version aus `app.py` (`APP_VERSION`) als Text für die GitHub-Release-Notiz und bricht ab, wenn er
fehlt oder leer ist. Die Prüfsummentabelle hängt das Skript selbst an – nicht hier eintragen.

## 1.6.0

<!-- Noch nichts eingetragen. Hier unter „### Neu“ / „### Kleinigkeiten“ die Änderungen sammeln;
     dieser Kommentar zählt nicht als Text. -->

## 1.5.3

### Neu
- **Einstellungen speichern sich automatisch** – kurz nach jeder Änderung: Postleitzahl, Personen, Läden, Händler, Treue-Programme, Rabatt-Filter, Größe und Update-Optionen.
- Der Knopf **💾 Speichern** sitzt jetzt oben in der Leiste neben „Angebote scannen“ und speichert Einstellungen und Wochenplan sofort.

### Kleinigkeiten
- Halb eingetippte Werte werden nicht übernommen, z. B. eine Postleitzahl mit weniger als 5 Ziffern. Bis dahin gilt der zuletzt gespeicherte Wert, ein Hinweis unter dem Feld zeigt das an.
- Anleitung und LIESMICH beschreiben das automatische Speichern.
