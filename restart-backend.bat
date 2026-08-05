@echo off
echo Rebuilding and restarting PPC OS backend (api) container...
cd /d "%~dp0"
docker compose up -d --build api
echo Done! Backend rebuilt and restarting. Wait ~15s for health check to pass.
pause
