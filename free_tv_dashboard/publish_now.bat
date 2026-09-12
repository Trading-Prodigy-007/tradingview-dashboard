@echo off
cd /d "%~dp0"
python build_site.py
if errorlevel 1 pause & exit /b 1
git add .
git commit -m "Update dashboard"
git push
pause
