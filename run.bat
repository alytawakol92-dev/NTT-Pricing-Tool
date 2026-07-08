@echo off
REM ============================================================
REM  NTT Pricing Tool - one-click launcher (Windows)
REM  Double-click this file. First run sets things up (~1-2 min);
REM  after that it just opens the tool in your browser.
REM ============================================================
cd /d "%~dp0"

REM auto-update to the latest version if this is a git clone.
REM find git on PATH, or fall back to the copy bundled with GitHub Desktop.
set "GITEXE="
where git >nul 2>nul && set "GITEXE=git"
if "%GITEXE%"=="" (
  for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
    if exist "%%D\resources\app\git\cmd\git.exe" set "GITEXE=%%D\resources\app\git\cmd\git.exe"
  )
)
REM the branch these updates are published to — pull it explicitly so the
REM update works even if the clone is sitting on 'main'.
set "NTT_BRANCH=claude/quotation-panel-design-tool-moy141"
if not "%GITEXE%"=="" (
  if exist ".git" (
    echo Checking for the latest version...
    "%GITEXE%" fetch --quiet origin %NTT_BRANCH% 2>nul
    "%GITEXE%" checkout --quiet %NTT_BRANCH% 2>nul
    "%GITEXE%" merge --ff-only "origin/%NTT_BRANCH%" 2>nul
  )
)

REM find Python (py launcher or python on PATH)
where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

%PY% --version >nul 2>nul
if %errorlevel% neq 0 (
  echo.
  echo   Python is not installed.
  echo   Please install Python 3.10+ from https://www.python.org/downloads/
  echo   During install, TICK "Add Python to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Creating environment ^(first run only, please wait^)...
  %PY% -m venv .venv
)

call ".venv\Scripts\activate.bat"
echo Installing / updating components...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

REM Optional manual override: if the tool cannot auto-find the DWG converter,
REM create a file "converter_path.txt" next to this launcher containing the
REM full path to ODAFileConverter.exe. (Editing this .bat is not needed and
REM would block auto-update.)
if exist "converter_path.txt" (
  set /p NTT_DWG2DXF=<converter_path.txt
  echo Using DWG converter from converter_path.txt
)

echo.
echo   Starting the NTT Pricing Tool...
echo   A browser window will open at http://127.0.0.1:5000
echo   Keep this window open while you use the tool. Close it to stop.
echo.
echo   NOTE: to upload AutoCAD .dwg files, install the free "ODA File
echo         Converter" once from https://www.opendesign.com/guestfiles/oda_file_converter
echo         The tool then finds it automatically. DXF and PDF need nothing extra.
echo.
python -m ntt_pricing.web
pause
