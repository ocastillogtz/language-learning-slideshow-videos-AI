@echo off
setlocal enableextensions
cd /d "%~dp0"

echo ================================================================
echo   German Learning Video tool - dependency setup (Windows)
echo ================================================================
echo.

REM ---------------------------------------------------------------
REM 1. Python
REM ---------------------------------------------------------------
echo [1/5] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found on PATH.
    echo   Install Python 3.10+ from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup, then re-run this script.
    pause
    exit /b 1
)
python --version
echo.

REM ---------------------------------------------------------------
REM 2. Python packages
REM ---------------------------------------------------------------
echo [2/5] Installing Python packages from requirements.txt...
python -m pip install --upgrade pip
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo   ERROR: pip install failed. See messages above.
    pause
    exit /b 1
)
echo.

REM ---------------------------------------------------------------
REM 3. Playwright Chromium (for HTML annotation rendering)
REM ---------------------------------------------------------------
echo [3/5] Installing Playwright Chromium browser...
python -m playwright install chromium
echo.

REM ---------------------------------------------------------------
REM 4. FFmpeg + ImageMagick (system tools)
REM ---------------------------------------------------------------
echo [4/5] Installing FFmpeg and ImageMagick...
where winget >nul 2>&1
if errorlevel 1 (
    echo   winget not available. Install these two manually, then re-run check_dependencies.py:
    echo     - FFmpeg ^(add the bin folder to PATH^):  https://www.gyan.dev/ffmpeg/builds/
    echo     - ImageMagick ^(enable "Install legacy utilities" + "Add to PATH"^):
    echo         https://imagemagick.org/script/download.php#windows
) else (
    echo   Using winget...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    winget install --id ImageMagick.ImageMagick -e --accept-source-agreements --accept-package-agreements
    echo.
    echo   NOTE: open config.ini and set the ImageMagick path so it matches the install,
    echo         for example:   imagemagick = magick     ^(uses the copy now on PATH^)
)
echo.

REM ---------------------------------------------------------------
REM 5. Verify
REM ---------------------------------------------------------------
echo [5/5] Verifying installation...
echo.
python "%~dp0check_dependencies.py"

echo.
echo ----------------------------------------------------------------
echo   Done. If FFmpeg or ImageMagick were just installed, CLOSE this
echo   window and open a NEW one (so PATH refreshes), then run:
echo       python check_dependencies.py
echo ----------------------------------------------------------------
pause
endlocal
