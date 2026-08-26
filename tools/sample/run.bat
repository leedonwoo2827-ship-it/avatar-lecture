@echo off
setlocal

REM Material folder -> dummy.mp4   (t1 TTS -> t2 slide PNG -> t3 mux)
REM Run it from the repo root, e.g.
REM   tools\sample\run.bat "material_folder_name"
REM   tools\sample\run.bat "C:\full\path\to\material_folder" narration_ko

if "%~1"=="" (
  echo Usage: run.bat "material folder" [script field]
  echo   The folder must contain script.json and slides\*.html
  exit /b 1
)

REM Resolve the argument to a full path BEFORE cd - a relative path given by
REM the user is relative to THEIR directory, not to this .bat file's folder.
set "MAT=%~f1"
set "FIELD=%~2"
if "%FIELD%"=="" set "FIELD=narration_ru"

cd /d "%~dp0"

if not exist "%MAT%\script.json" (
  echo [ERROR] script.json not found in:
  echo         %MAT%
  echo   Give the folder that holds script.json and slides\
  exit /b 1
)

set "ROOT=%~dp0..\.."
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo Run the root setup.bat, then this folder's setup.bat.
  exit /b 1
)
set "PY=%ROOT%\.venv\Scripts\python.exe"

"%PY%" t1_tts.py "%MAT%" --field %FIELD%   || exit /b 1
"%PY%" t2_slides_png.py "%MAT%"            || exit /b 1
"%PY%" t3_mux.py "%MAT%"                   || exit /b 1

echo.
echo dummy.mp4 is in the material folder.
echo Feed it to the main pipeline from the repo root:
echo   run.bat "%MAT%\dummy.mp4" "%MAT%\_build\slides"
exit /b 0
