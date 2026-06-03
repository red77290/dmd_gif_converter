@echo off
:: =============================================================================
:: launch_ui.bat — DMD GIF Converter UI launcher
:: Windows (cmd / double-click)
::
:: First run : creates a Python venv and installs all dependencies.
:: Next runs  : activates the venv and starts the UI directly.
::
:: Usage:
::   Double-click this file, or run it from cmd / PowerShell.
:: =============================================================================
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "VENV=%SCRIPT_DIR%.venv"
set "UI=%SCRIPT_DIR%dmd_gif_converter_ui.py"

:: ── Check / create venv ──────────────────────────────────────────────────────
if not exist "%VENV%\Scripts\python.exe" (
    echo =^> First run — setting up virtual environment...
    echo.

    :: Find Python 3.10+
    :: Note: we avoid "where" which may be missing on some Windows 10 installs.
    ::       Instead we try to run each candidate directly and check errorlevel.
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

    echo =^> Installing dependencies...
    "%VENV%\Scripts\pip" install --quiet --upgrade pip
    "%VENV%\Scripts\pip" install --quiet -r "%SCRIPT_DIR%requirements_ui.txt"
    if errorlevel 1 (
        echo ERROR: pip install failed.
        pause
        exit /b 1
    )

    echo =^> Environment ready.
    echo.
)

:: ── Launch the UI ─────────────────────────────────────────────────────────────
"%VENV%\Scripts\python.exe" "%UI%"

if errorlevel 1 (
    echo.
    echo ERROR: The application exited with an error. See output above.
    pause
)

