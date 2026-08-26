@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Plain ASCII only in this file, on purpose. A Korean-locale cmd.exe parses
REM .bat files in the system codepage (CP949), not UTF-8. Korean messages live
REM in the Python scripts, which set their own stdout encoding.

echo == mp42perso setup ==
echo.

echo [1/3] checking python
set "PYEXE="
for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do call :try "%%p"
if not defined PYEXE for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)" 2^>nul') do call :try "%%p"
if not defined PYEXE (
  echo.
  echo [ERROR] No working Python 3.10+ found.
  echo   Install from https://www.python.org/downloads/
  echo   and CHECK "Add python.exe to PATH" during setup.
  exit /b 1
)
echo       %PYEXE%

echo [2/3] checking ffmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] ffmpeg not found on PATH.
  echo   winget install Gyan.FFmpeg
  echo   ...then open a NEW terminal so PATH refreshes.
  exit /b 1
)
echo       ok

echo [3/3] creating venv and installing packages
if not exist ".venv\Scripts\python.exe" (
  "%PYEXE%" -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Done. Next:
echo   run.bat "C:\path\to\lecture.mp4"
echo   run.bat "C:\path\to\lecture.mp4" "C:\path\to\slides"
echo.
echo NOTE: the first s2 run downloads the speech model (about 1.5GB) once.
echo       To make a test lecture first, see tools\sample\setup.bat
exit /b 0

:try
if defined PYEXE goto :eof
"%~1" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>nul
if not errorlevel 1 set "PYEXE=%~1"
goto :eof
