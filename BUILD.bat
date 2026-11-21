@echo off
cd /d "%~dp0"
title Essens-Plan - Build
echo.
echo  ==========================================
echo    Essens-Plan  -  Build-Prozess
echo  ==========================================
echo.

echo  [PRE] Pruefe Abhaengigkeiten...
py -3 -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo  [FEHLER] pip install fehlgeschlagen.
    pause & exit /b 1
)

echo  [1/5] Laufende Instanz beenden / alten Build loeschen...
rem Erst hoeflich schliessen: ein hart beendetes Programm laesst seinen _MEI-Ordner in %%TEMP%% liegen.
tasklist /fi "imagename eq Essens-Plan.exe" 2>nul | find /i "Essens-Plan.exe" >nul
if not errorlevel 1 (
    taskkill /im "Essens-Plan.exe" >nul 2>&1
    timeout /t 3 /nobreak >nul
    taskkill /f /im "Essens-Plan.exe" >nul 2>&1
    timeout /t 1 /nobreak >nul
)
rem Geloescht werden nur diese drei Dateien - der Ordner dist\res (echte Nutzerdaten) bleibt unangetastet.
if exist "dist\Essens-Plan.exe" del /f /q "dist\Essens-Plan.exe"
if exist "dist\Essens-Plan.zip" del /f /q "dist\Essens-Plan.zip"
if exist "dist\Anleitung.pdf" del /f /q "dist\Anleitung.pdf"
if exist "dist\Essens-Plan.exe" (
    echo  [FEHLER] dist\Essens-Plan.exe laesst sich nicht loeschen - laeuft das Programm noch?
    pause & exit /b 1
)

echo  [2/5] Programmsymbol erzeugen...
if not exist "res\icon.ico" py -3 make_icon.py

echo  [3/5] Kompiliere...
rem Was in die EXE kommt, steht in Essens-Plan.spec.
py -3 -m PyInstaller --noconfirm --clean "Essens-Plan.spec"
if errorlevel 1 (
    echo  [FEHLER] Build fehlgeschlagen. Siehe Ausgabe oben.
    pause & exit /b 1
)
if not exist "dist\Essens-Plan.exe" (
    echo  [FEHLER] Der Build hat keine dist\Essens-Plan.exe erzeugt.
    pause & exit /b 1
)

echo  [4/5] Anleitung.pdf erzeugen...
rem make_anleitung.py nutzt reportlab, startet kein Programm und legt nichts in res\ an.
py -3 make_anleitung.py "dist\Anleitung.pdf"
if errorlevel 1 (
    echo  [FEHLER] Die Anleitung konnte nicht erstellt werden. Siehe Meldung oben.
    pause & exit /b 1
)
if not exist "dist\Anleitung.pdf" (
    echo  [FEHLER] Es wurde keine dist\Anleitung.pdf erzeugt.
    pause & exit /b 1
)

echo  [5/5] Paket zum Weitergeben schnueren...
rem Ins Paket kommen nur EXE, Anleitung und LIESMICH - nie der Ordner dist\res mit eigenen Daten.
copy /y "LIESMICH.txt" "dist\LIESMICH.txt" >nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Essens-Plan.exe','dist\Anleitung.pdf','dist\LIESMICH.txt' -DestinationPath 'dist\Essens-Plan.zip' -Force"
if errorlevel 1 (
    echo  [FEHLER] Das Zip-Paket konnte nicht erstellt werden.
    pause & exit /b 1
)
rem Kontrolle: Inhalt auflisten und pruefen, dass wirklich nur die drei Dateien drin sind.
powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $z=[IO.Compression.ZipFile]::OpenRead((Resolve-Path 'dist\Essens-Plan.zip').Path); try { $n=@($z.Entries | ForEach-Object { $_.FullName } | Sort-Object); $z.Entries | ForEach-Object { '    im Zip: ' + $_.FullName + '  (' + $_.Length + ' Bytes)' }; if (($n -join '|') -ne 'Anleitung.pdf|Essens-Plan.exe|LIESMICH.txt') { exit 1 } } finally { $z.Dispose() }"
if errorlevel 1 (
    echo  [FEHLER] Der Zip-Inhalt stimmt nicht: erwartet Essens-Plan.exe, Anleitung.pdf, LIESMICH.txt.
    pause & exit /b 1
)
echo.
echo  ==========================================
echo  BUILD ERFOLGREICH
echo    dist\Essens-Plan.exe   (einzelne Datei, keine Installation)
echo    dist\Anleitung.pdf     (ausfuehrliche Anleitung)
echo    dist\Essens-Plan.zip   (EXE + Anleitung + LIESMICH zum Verschicken)
echo.
echo  Einstellungen, eigene Rezepte und Wochen landen neben der EXE
echo  in res\ - oder in %%APPDATA%%\Essens-Plan, wenn dort nicht
echo  geschrieben werden darf.
echo  ==========================================
pause
