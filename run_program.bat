@echo off
setlocal
cd /d "%~dp0"
title Employee Information System
rem Open an existing server, or start a hidden browser-readiness watcher.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_browser.ps1"
if errorlevel 20 goto failed
if errorlevel 10 exit /b 0
rem Keep the server in this window so closing it stops the program.
call "%~dp0start_server.bat"
exit /b %errorlevel%

:failed
echo Could not start the program. See the message above.
pause
exit /b 1
