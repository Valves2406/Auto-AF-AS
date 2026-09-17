@echo off
rem Abre o Gerador de AF com o Python do sistema (evita o .venv do OneDrive).
cd /d "%~dp0"
start "" "C:\Users\valves\AppData\Local\Programs\Python\Python314\pythonw.exe" app.py
