@echo off
setlocal enableextensions enabledelayedexpansion
cd /d "%~dp0"

echo ================================================================
echo   German Learning Video tool - dependency setup (Windows)
echo ================================================================
echo.

REM Supported Python range. numpy 1.26.x (pinned via numpy^<2.0 because
REM moviepy 1.0.3 needs numpy 1.x) only publishes prebuilt wheels for
REM CPython 3.10-3.12. On 3.13+ pip tries to COMPILE numpy from source,
REM which needs a Visual Studio C compiler and fails on most machines.
REM So this script refuses to install into an out-of-range interpreter and
REM instead finds (or creates) a compatible one.
set "CONDA_ENV=germanvids"
set "PYEXE="

REM ---------------------------------------------------------------
REM 1. Locate a compatible Python (3.10 - 3.12)
REM ---------------------------------------------------------------
echo [1/6] Locating a compatible Python (3.10 - 3.12)...

REM 1a. A project-local virtual environment, if one already exists.
if exist "%~dp0.venv\Scripts\python.exe" (
    call :checkver "%~dp0.venv\Scripts\python.exe"
    if not errorlevel 1 set "PYEXE=%~dp0.venv\Scripts\python.exe"
)

REM 1b. The dedicated conda env, under common Anaconda/Miniconda roots.
if not defined PYEXE (
    for %%c in (
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\miniconda3"
        "%USERPROFILE%\miniforge3"
        "C:\ProgramData\anaconda3"
        "C:\ProgramData\miniconda3"
    ) do (
        if not defined PYEXE if exist "%%~c\envs\%CONDA_ENV%\python.exe" (
            call :checkver "%%~c\envs\%CONDA_ENV%\python.exe"
            if not errorlevel 1 set "PYEXE=%%~c\envs\%CONDA_ENV%\python.exe"
        )
    )
)

REM 1c. Interpreters known to the py launcher (newest supported first).
if not defined PYEXE (
    for %%v in (-3.12 -3.11 -3.10) do (
        if not defined PYEXE (
            py %%v -c "import sys" >nul 2>&1
            if not errorlevel 1 (
                for /f "delims=" %%q in ('py %%v -c "import sys;print(sys.executable)"') do set "PYEXE=%%q"
            )
        )
    )
)

REM 1d. python / python3 on PATH, but only if the version is in range.
if not defined PYEXE (
    for %%e in (python python3) do (
        if not defined PYEXE (
            where %%e >nul 2>&1
            if not errorlevel 1 (
                call :checkver %%e
                if not errorlevel 1 (
                    for /f "delims=" %%q in ('%%e -c "import sys;print(sys.executable)"') do set "PYEXE=%%q"
                )
            )
        )
    )
)

REM ---------------------------------------------------------------
REM 2. If nothing compatible exists, create a conda env on Python 3.12
REM ---------------------------------------------------------------
if not defined PYEXE (
    echo   No compatible Python found on this machine.
    echo   Looking for conda so an isolated Python 3.12 env can be created...

    set "CONDA="
    where conda >nul 2>&1
    if not errorlevel 1 set "CONDA=conda"
    if not defined CONDA (
        for %%c in (
            "%USERPROFILE%\anaconda3\Scripts\conda.exe"
            "%USERPROFILE%\miniconda3\Scripts\conda.exe"
            "%USERPROFILE%\miniforge3\Scripts\conda.exe"
            "C:\ProgramData\anaconda3\Scripts\conda.exe"
            "C:\ProgramData\miniconda3\Scripts\conda.exe"
        ) do (
            if not defined CONDA if exist "%%~c" set "CONDA=%%~c"
        )
    )

    if defined CONDA (
        echo   Creating conda env "%CONDA_ENV%" on Python 3.12 ^(one-time, ~1-2 min^)...
        "!CONDA!" create -n %CONDA_ENV% python=3.12 -y
        if errorlevel 1 (
            echo   ERROR: conda failed to create the environment. See messages above.
            pause
            exit /b 1
        )
        "!CONDA!" run -n %CONDA_ENV% python -c "import sys;print(sys.executable)" > "%TEMP%\_gv_pyexe.txt"
        set /p PYEXE=<"%TEMP%\_gv_pyexe.txt"
        del "%TEMP%\_gv_pyexe.txt" >nul 2>&1
    )
)

if not defined PYEXE (
    echo.
    echo   ERROR: could not find or create a Python in the 3.10 - 3.12 range.
    echo   This project needs one of those versions because numpy 1.26.x only
    echo   ships prebuilt wheels for them ^(newer Python would try to compile it^).
    echo.
    echo   Fix by installing EITHER:
    echo     - Python 3.12: https://www.python.org/downloads/release/python-3129/
    echo       ^(tick "Add python.exe to PATH" during setup^), or
    echo     - Anaconda:    https://www.anaconda.com/download
    echo   then re-run this script.
    pause
    exit /b 1
)

"%PYEXE%" -c "import platform;print(platform.python_version())" > "%TEMP%\_gv_pyver.txt"
set /p PYVER=<"%TEMP%\_gv_pyver.txt"
del "%TEMP%\_gv_pyver.txt" >nul 2>&1
echo   Using Python %PYVER%: %PYEXE%
echo.

REM ---------------------------------------------------------------
REM 3. Python packages
REM ---------------------------------------------------------------
echo [2/6] Upgrading pip...
"%PYEXE%" -m pip install --upgrade pip
echo.

echo [3/6] Installing a prebuilt NumPy wheel...
REM --only-binary forbids a source build, so if a wheel is somehow missing
REM this fails immediately with a clear message instead of invoking a compiler.
"%PYEXE%" -m pip install --only-binary=:all: "numpy<2.0"
if errorlevel 1 (
    echo   ERROR: no prebuilt NumPy wheel is available for Python %PYVER%.
    echo   Use Python 3.10 - 3.12 for this project ^(see notes above^).
    pause
    exit /b 1
)
echo.

echo [4/6] Installing the remaining packages from requirements.txt...
"%PYEXE%" -m pip install --prefer-binary -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo   ERROR: pip install failed. See messages above.
    pause
    exit /b 1
)
echo.

REM ---------------------------------------------------------------
REM 4. Playwright Chromium (for HTML annotation rendering)
REM ---------------------------------------------------------------
echo [5/6] Installing Playwright Chromium browser...
"%PYEXE%" -m playwright install chromium
echo.

REM ---------------------------------------------------------------
REM 5. FFmpeg + ImageMagick (system tools)
REM ---------------------------------------------------------------
echo [6/6] Installing FFmpeg and ImageMagick...
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
REM 6. Verify
REM ---------------------------------------------------------------
echo Verifying installation...
echo.
"%PYEXE%" "%~dp0check_dependencies.py"

echo.
echo ----------------------------------------------------------------
echo   Done. If FFmpeg or ImageMagick were just installed, CLOSE this
echo   window and open a NEW one (so PATH refreshes), then run:
echo       "%PYEXE%" check_dependencies.py
echo   Start the app with launch.bat (it finds this Python automatically).
echo ----------------------------------------------------------------
pause
endlocal
exit /b

REM ===============================================================
REM  Subroutine: succeed (errorlevel 0) if %1 is Python 3.10 - 3.12
REM ===============================================================
:checkver
"%~1" -c "import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>&1
goto :eof
