@echo off
REM ============================================================
REM  NTT Pricing Tool - one-click launcher (Windows)
REM  Double-click this file. First run sets things up (~1-2 min);
REM  after that it just opens the tool in your browser.
REM ============================================================
cd /d "%~dp0"

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

echo.
echo   Starting the NTT Pricing Tool...
echo   A browser window will open at http://127.0.0.1:5000
echo   Keep this window open while you use the tool. Close it to stop.
echo.
python -m ntt_pricing.web
pause
