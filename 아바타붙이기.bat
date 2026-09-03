@echo off
setlocal
cd /d "%~dp0"

REM Plain ASCII only (Korean-locale cmd.exe reads .bat as CP949).
REM Korean text lives in scripts\p45_attach.py, which sets its own stdout encoding.
REM
REM What this does:
REM   1) looks in the newest lecture's 05\bundleNN\ folders for downloaded videos
REM   2) runs p4 (attach avatar) then p5 (compose both styles, join)
REM   3) opens the 09 output folder
REM
REM Drop the rendered avatar video into the bundle folder, then double-click this.

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" scripts\p45_attach.py %*
echo.
pause
