@echo off
rem Double-click to start doctor and patient windows
chcp 65001 > nul
cd /d %~dp0
set PY=py -3.12
if exist "%~dp0.venv\Scripts\python.exe" set PY="%~dp0.venv\Scripts\python.exe"
cd app
%PY% start.py
if errorlevel 1 pause
