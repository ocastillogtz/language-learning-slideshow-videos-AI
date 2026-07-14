@echo off
setlocal enableextensions
cd /d "%~dp0"

if "%~1"=="--open-browser" goto :openbrowser

echo ================================================================
echo   German Learning Video tool - launcher
echo ================================================================
echo.

REM Pick the first Python that actually has the app's dependencies installed.
REM Several interpreters can coexist on one machine; the first "python" on
REM PATH is not necessarily the one where requirements.txt was installed.
set "PYEXE="
set "PYCHECK=import flask, elevenlabs, moviepy, pydub, dotenv, openai"

for /f "delims=" %%p in ('where python 2^>nul') do (
    if not defined PYEXE (
        "%%p" -c "%PYCHECK%" >nul 2>&1
        if not errorlevel 1 set "PYEXE=%%p"
    )
)

REM Fall back to interpreters known only to the py launcher (not on PATH).
if not defined PYEXE (
    for %%v in (-3.12 -3.11 -3.13 -3.10) do (
        if not defined PYEXE (
            py %%v -c "%PYCHECK%" >nul 2>&1
            if not errorlevel 1 (
                for /f "delims=" %%q in ('py %%v -c "import sys; print(sys.executable)"') do set "PYEXE=%%q"
            )
        )
    )
)

if not defined PYEXE (
    echo   ERROR: no Python installation with the required packages was found.
    echo   Run install_dependencies.bat first.
    pause
    exit /b 1
)
echo Using Python: %PYEXE%

REM Open the browser in the background once the server is reachable
start "" /b cmd /c ""%~f0" --open-browser"

echo Starting server at http://127.0.0.1:5000/ ...
echo (close this window or press Ctrl+C to stop the server)
echo.
"%PYEXE%" "%~dp0app.py"
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
