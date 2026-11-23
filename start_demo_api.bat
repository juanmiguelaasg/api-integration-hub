@echo off
cd /d %~dp0
.venv\Scripts\python mock_systems.py --port 8100
