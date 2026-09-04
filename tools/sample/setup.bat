@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Plain ASCII only, on purpose (Korean-locale cmd.exe reads .bat as CP949).
REM This sets up the SAMPLE tool: material folder -> dummy.mp4
REM The main pipeline lives in the repo root.

echo == avatar-lecture sample-maker setup ==
echo.

set "ROOT=%~dp0..\.."
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo [ERROR] Run the root setup.bat first - this tool shares that venv.
  echo         %ROOT%\setup.bat
  exit /b 1
)
set "PY=%ROOT%\.venv\Scripts\python.exe"

echo [1/3] installing packages
"%PY%" -m pip install -r "%ROOT%\requirements-sample.txt"
if errorlevel 1 exit /b 1

echo [2/3] installing headless chromium (for slide screenshots)
"%PY%" -m playwright install chromium
if errorlevel 1 exit /b 1

echo [3/3] downloading Piper Russian voice (MIT licence)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_piper.ps1"
if errorlevel 1 exit /b 1

echo.
echo Done. Next:
echo   run.bat "C:\path\to\material_folder"
echo.
echo The material folder is what Claude Code Desktop produced:
echo   script.json   subs.uz.srt   slides\001.html ...
exit /b 0
