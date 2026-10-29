@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "ets2garage\app.py" %*