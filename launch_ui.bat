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
set "UI=-m src.ui.launcher"
set "REQ=%SCRIPT_DIR%requirements_ui.txt"
set "REQ_HASH_FILE=%VENV%\.requirements_hash"

:: ── Jump to main logic — subroutines are defined below :main ─────────────────
goto :main

:: =============================================================================
::  S U B R O U T I N E S
::  (only reached via  call :name — never executed during normal flow)
:: =============================================================================

:: ── Compute MD5 of requirements_ui.txt via CertUtil ──────────────────────────
:compute_hash
    set "_hash="
    for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%REQ%" MD5 2^>nul') do (
        if "!_hash!"=="" set "_hash=%%H"
    )
    :: Strip spaces that certutil sometimes adds
    set "_hash=!_hash: =!"
    goto :eof

:: ── Install / upgrade dependencies ───────────────────────────────────────────
:install_deps
    echo =^> Installing / updating dependencies...
    "%VENV%\Scripts\python.exe" -m ensurepip --default-pip >nul 2>&1
    "%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install --quiet -r "%REQ%"
    if errorlevel 1 (
        echo.
        echo ERROR: pip install failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
    :: Save current hash so we skip next time
    set "_hash="
    call :compute_hash
    echo !_hash!> "%REQ_HASH_FILE%"
    echo =^> Dependencies up to date.
    echo.
    goto :eof

:: =============================================================================
::  M A I N
:: =============================================================================
:main

:: ── Check / create venv ──────────────────────────────────────────────────────
if not exist "%VENV%\Scripts\python.exe" (
    echo =^> First run — setting up virtual environment...
    echo.

    :: Find Python 3.10+
    set "PYTHON="
    for %%C in (py python python3 python3.13 python3.12 python3.11 python3.10) do (
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
        echo   Try:  !PYTHON! -m pip install --upgrade pip
        pause
        exit /b 1
    )

    call :install_deps

    echo =^> Environment ready.
    echo.
) else (
    :: Venv exists — check if requirements_ui.txt changed since last install
    set "_hash="
    call :compute_hash
    set "CURRENT_HASH=!_hash!"

    set "SAVED_HASH="
    if exist "%REQ_HASH_FILE%" set /p SAVED_HASH=<"%REQ_HASH_FILE%"

    if not "!CURRENT_HASH!"=="!SAVED_HASH!" (
        echo =^> requirements_ui.txt changed — updating dependencies...
        call :install_deps
    )
)

:: ── Launch the UI ─────────────────────────────────────────────────────────────
echo =^> Starting DMD GIF Converter...
"%VENV%\Scripts\python.exe" %UI% %*

if errorlevel 1 (
    echo.
    echo ERROR: The application exited with an error. See output above.
    pause
)
