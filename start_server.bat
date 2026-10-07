@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_dependencies
echo Preparing Python environment...
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto check_environment
)
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto check_environment
)
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%BUNDLED_PYTHON%" (
    echo Python 3.11 or newer is required. Install Python and run this file again.
    goto failed
)
"%BUNDLED_PYTHON%" -m venv .venv

:check_environment
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" goto failed

:check_dependencies
".venv\Scripts\python.exe" -c "from pathlib import Path; import sys, flask, pandas, openpyxl, werkzeug, xlrd, flask_limiter, PIL, waitress; p=Path('.venv/installed-requirements.txt'); sys.exit(not p.exists() or p.read_bytes()!=Path('requirements.txt').read_bytes())" >nul 2>&1
if not errorlevel 1 goto run_server
echo Installing required packages. The first run needs an internet connection...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
copy /y "requirements.txt" ".venv\installed-requirements.txt" >nul
if errorlevel 1 goto failed

:run_server
echo Server: http://127.0.0.1:5000
echo Press Ctrl+C to stop.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo Setup or server startup failed. See the message above.
pause
exit /b 1
