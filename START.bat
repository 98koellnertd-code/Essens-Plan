@echo off
cd /d "%~dp0"
title Essens-Plan
py -3 -c "import requests, reportlab, PIL" >nul 2>&1
if errorlevel 1 (
    echo  [INFO] Installiere Abhaengigkeiten...
    py -3 -m pip install -r requirements.txt -q
)
py -3 app.py
if errorlevel 1 pause
