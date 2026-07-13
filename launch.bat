@echo off
setlocal enableextensions
cd /d "%~dp0"

if "%~1"=="--open-browser" goto :openbrowser

echo ================================================================
echo   German Learning Video tool - launcher
echo ================================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found on PATH.
    echo   Run install_dependencies.bat first.
    pause
    exit /b 1
)

for /f "delims=" %%p in ('where python') do (
    echo Using Python: %%p
    goto :gotpython
)
:gotpython

REM Open the browser in the background once the server is reachable
start "" /b cmd /c ""%~f0" --open-browser"

echo Starting server at http://127.0.0.1:5000/ ...
echo (close this window or press Ctrl+C to stop the server)
echo.
python "%~dp0app.py"
exit /b

:openbrowser
REM Poll the port for up to 60 seconds, then open the default browser
for /l %%i in (1,1,60) do (
    powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient('127.0.0.1',5000)).Close(); exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        start "" "http://127.0.0.1:5000/"
        exit /b
    )
    timeout /t 1 /nobreak >nul
)
exit /b
