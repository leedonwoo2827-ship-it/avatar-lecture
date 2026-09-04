@echo off
setlocal
cd /d "%~dp0"

REM Avatar Lecture - READ-ONLY console for people on the office LAN.
REM Plain ASCII only (Korean-locale cmd.exe reads .bat as CP949) - the Korean
REM text lives in the Python server and the HTML page.
REM
REM   run.bat      = this PC only, everything works
REM   lan-run.bat  = anyone on the LAN can LOOK, nobody can RUN
REM
REM The server refuses every POST in this mode, so viewers cannot start a
REM build, drop a video, change subtitles, or open a folder on this PC.
REM
REM Windows Firewall asks once on the first run: allow PRIVATE networks only.
REM Keep this window open while people are watching. Closing it stops the server.

if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  echo.
  pause
  exit /b 1
)

echo.
echo   READ-ONLY mode. Tell your colleagues the address printed below.
echo.
.venv\Scripts\python.exe webapp\server.py --lan
echo.
pause
exit /b 0
