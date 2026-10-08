@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%windows\Install-DW5934e.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo.
if not "%RC%"=="0" echo Installation did not complete. Read the JSON status above and docs\TROUBLESHOOTING.md.
exit /b %RC%
