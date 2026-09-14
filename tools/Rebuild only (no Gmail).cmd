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
echo Rebuilding Northstar dashboards from:
echo   %CD%
echo.
python update.py
if errorlevel 1 (
  echo.
  echo BUILD FAILED - nothing was overwritten by a partial run.
) else (
  echo.
  echo Done. Open output\index.html to see the result.
)
echo.
pause
