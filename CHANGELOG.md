# Änderungsprotokoll

Je Version ein Abschnitt `## X.Y.Z`. Das Release-Skript (`scripts\release.py`) nimmt den Abschnitt
der Version aus `app.py` (`APP_VERSION`) als Text für die GitHub-Release-Notiz und bricht ab, wenn er
fehlt oder leer ist. Die Prüfsummentabelle hängt das Skript selbst an – nicht hier eintragen.

## 1.6.0

### Neu
- **Kategorien in „Angebot raussuchen“**: eine Knopfleiste mit runden Symbolen für Getränke, Kaffee & Tee, Süßes & Snacks, Fleisch & Wurst, Fisch, Obst & Gemüse, Kräuter & Gewürze, Milch & Käse, Brot & Backwaren, Tiefkühl, Drogerie, Haushalt und Tier. Das Suchfeld sucht dann nur noch in der gewählten Kategorie.
- **Getränke** lassen sich nach Alkohol (mit, ohne, beides), Sorte und Marke filtern.
- **⭐ Top-Deals – der Schnäppchen-Radar** zeigt Kisten, Träger, Großpackungen, deine Marken und stark reduzierte Ware. Jeder Vorschlag nennt seinen Grund und den Preis je Liter oder Kilo. Unter **Meine Marken** stellst du ein, welche Marken zählen.
- **Händler, Mindest-Rabatt und Sortierung** (Rabatt, Preis, Händler) stellst du direkt im Reiter ein; die Einstellung bleibt gespeichert.
- **„Nur neue“** zeigt die Angebote, die seit dem letzten Besuch dazugekommen sind. In der Liste sind sie mit „NEU“ markiert.
- **Mehrere Angebote auf einmal** auf die Einkaufsliste: mit Strg oder Umschalt auswählen.
- **73 neue Gerichte** (jetzt 203).
- **Update prüft SHA-256-Prüfsummen**: Ein Update wird nur installiert, wenn die Datei unverändert angekommen ist.

### Kleinigkeiten
- Neue Spalte „Je Liter/kg“ in „Angebot raussuchen“.
- Klopapier, Küchenrolle, Katzenstreu und Kräuter werden zuverlässiger gefunden.
- Anleitung und LIESMICH beschreiben die neuen Funktionen.

## 1.5.3

### Neu
- **Einstellungen speichern sich automatisch** – kurz nach jeder Änderung: Postleitzahl, Personen, Läden, Händler, Treue-Programme, Rabatt-Filter, Größe und Update-Optionen.
- Der Knopf **💾 Speichern** sitzt jetzt oben in der Leiste neben „Angebote scannen“ und speichert Einstellungen und Wochenplan sofort.

### Kleinigkeiten
- Halb eingetippte Werte werden nicht übernommen, z. B. eine Postleitzahl mit weniger als 5 Ziffern. Bis dahin gilt der zuletzt gespeicherte Wert, ein Hinweis unter dem Feld zeigt das an.
- Anleitung und LIESMICH beschreiben das automatische Speichern.
