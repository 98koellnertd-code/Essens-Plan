@echo off
rem Doppelklick-Starter fuer ein vollstaendiges Release (bauen, Pruefsummen, Tag, GitHub-Release, Gegenprobe).
rem Weitere Optionen werden durchgereicht, z. B.:  scripts\RELEASE.bat --skip-build
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0\.."
title Essens-Plan - Release
echo.
echo  ==========================================
echo    Essens-Plan  -  Release veroeffentlichen
echo  ==========================================
echo.
echo  Das baut die EXE, erzeugt die SHA-256-Pruefsummen, setzt den Git-Tag,
echo  schiebt ihn nach GitHub und legt dort das Release an. Das ist oeffentlich.
echo  Ohne Veroeffentlichung (Trockenlauf):  py -3 scripts\release.py
echo.
set /p ANTWORT= Wirklich veroeffentlichen? (j/N): 
if /i not "%ANTWORT%"=="j" (
    echo  Abgebrochen.
    if not defined EP_NOPAUSE pause
    exit /b 1
)
py -3 scripts\release.py --publish %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (echo  [FEHLER] Release nicht abgeschlossen - Exit-Code %RC%.) else (echo  Release fertig.)
if not defined EP_NOPAUSE pause
exit /b %RC%
