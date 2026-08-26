@echo off
setlocal
cd /d "%~dp0"

REM mp42perso - web console. Double-click this file.
REM Plain ASCII only (Korean-locale cmd.exe reads .bat as CP949) - the Korean
REM text lives in the Python server and the HTML page.
REM
REM Keep this window open while you work. Closing it stops the server.
REM Ctrl+C also stops it.

if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  echo.
  pause
  exit /b 1
)

start "" http://127.0.0.1:6326
.venv\Scripts\python.exe webapp\server.py
echo.
pause
exit /b 0
