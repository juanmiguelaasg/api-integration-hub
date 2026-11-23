@echo off
cd /d %~dp0
.venv\Scripts\python -m integrationhub export --check
pause
