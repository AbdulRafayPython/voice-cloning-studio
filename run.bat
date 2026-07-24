@echo off
REM ── Launch Zenvyrolabs Voice Studio locally (Windows, venv) ──
REM Requires: Python 3.11 venv already created by setup (venv\), FFmpeg on PATH.
call venv\Scripts\activate.bat
python app.py
pause
