@echo off
:: =============================================================================
:: launch_ui.bat — DMD GIF Converter UI launcher
:: Windows (cmd / double-click)
::
:: First run : creates a Python venv and installs all dependencies.
:: Next runs  : activates the venv and starts the UI directly.
::              If requirements_ui.txt changed since last install, re-runs pip.
::
:: Usage:
::   Double-click this file, or run it from cmd / PowerShell.
:: =============================================================================
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "VENV=%SCRIPT_DIR%.venv"
set "UI=%SCRIPT_DIR%dmd_gif_converter_ui.py"
set "REQ=%SCRIPT_DIR%requirements_ui.txt"
set "REQ_HASH_FILE=%VENV%\.requirements_hash"

:: ── Helper: compute MD5 of requirements_ui.txt via CertUtil ──────────────────
:compute_hash
    for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%REQ%" MD5 2^>nul') do (
        if "!_hash!"=="" set "_hash=%%H"
    )
    goto :eof

:: ── Install / upgrade dependencies ───────────────────────────────────────────
:install_deps
    echo =^> Installing / updating dependencies...
    "%VENV%\Scripts\pip" install --quiet --upgrade pip
    "%VENV%\Scripts\pip" install --quiet -r "%REQ%"
    if errorlevel 1 (
        echo ERROR: pip install failed.
        pause
        exit /b 1
    )
    :: Save current hash
    set "_hash="
    call :compute_hash
    echo !_hash!> "%REQ_HASH_FILE%"
    echo =^> Dependencies up to date.
    echo.
    goto :eof

:: ── Check / create venv ──────────────────────────────────────────────────────
if not exist "%VENV%\Scripts\python.exe" (
    echo =^> First run — setting up virtual environment...
    echo.

    :: Find Python 3.10+
    set "PYTHON="
    for %%C in (python3.13 python3.12 python3.11 python3.10 python3 python py) do (
        if "!PYTHON!"=="" (
            %%C --version >nul 2>&1
            if not errorlevel 1 set "PYTHON=%%C"
        )
    )

    if "!PYTHON!"=="" (
        echo ERROR: Python 3.10+ not found.
        echo.
        echo   Download and install from https://www.python.org/downloads/
        echo   Make sure to check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )

    echo     Python : !PYTHON!
    for /f "tokens=*" %%V in ('!PYTHON! --version 2^>^&1') do echo     Version: %%V
    echo.

    !PYTHON! -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )

    call :install_deps

    echo =^> Environment ready.
    echo.
) else (
    :: Venv exists — check if requirements_ui.txt changed
    set "_hash="
    call :compute_hash
    set "CURRENT_HASH=!_hash!"
    set /p SAVED_HASH=<"%REQ_HASH_FILE%" 2>nul || set "SAVED_HASH="

    if not "!CURRENT_HASH!"=="!SAVED_HASH!" (
        echo =^> requirements_ui.txt changed — updating dependencies...
        call :install_deps
    )
)

:: ── Launch the UI ─────────────────────────────────────────────────────────────
"%VENV%\Scripts\python.exe" "%UI%"

if errorlevel 1 (
    echo.
    echo ERROR: The application exited with an error. See output above.
    pause
)
