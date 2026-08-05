@echo off
echo Restarting PPC OS frontend container...
cd /d "%~dp0"
docker compose up -d --force-recreate frontend
echo Done! Frontend restarting with volume mount active.
echo New source code (with error logging) will be live at http://localhost:3000
pause
