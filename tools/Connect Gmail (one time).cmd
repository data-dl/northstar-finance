@echo off
REM Location-independent: works from the repo's tools folder or from a shortcut folder
REM that holds a copy of this file next to (or one level below) update.py.
setlocal
set "PIPE="
if exist "%~dp0update.py"    set "PIPE=%~dp0"
if exist "%~dp0..\update.py" set "PIPE=%~dp0..\"
if not defined PIPE (
  echo Could not find update.py next to this script or one folder up.
  echo.
  pause
  exit /b 1
)
cd /d "%PIPE%"
echo  Northstar - connect Gmail
echo  ============================================================
echo.
echo  A browser tab will open asking you to allow READ-ONLY Gmail
echo  access. Approve it there and come back. Nothing is sent,
echo  deleted, archived, or even marked read.
echo.
echo  Leave this window open until it says done. Do NOT run this as
echo  administrator - an elevated window gets a different AppData
echo  folder and will not find the saved client.
echo.
echo  Checking setup...
python tools\sync_alerts.py --status
echo.
echo  ------------------------------------------------------------
echo.
python tools\sync_alerts.py --connect
echo.
pause
