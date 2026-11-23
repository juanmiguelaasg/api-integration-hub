@echo off
cd /d %~dp0
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pytest
pause
