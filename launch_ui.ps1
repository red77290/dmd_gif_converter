# =============================================================================
# launch_ui.ps1 - DMD GIF Converter UI launcher
# Windows (PowerShell)
#
# First run : creates a Python venv and installs all dependencies.
# Next runs  : activates the venv and starts the UI directly.
#              If requirements_ui.txt changed since last install, re-runs pip.
#
# Usage:
#   Right-click -> "Run with PowerShell"
#   or from a terminal:  .\launch_ui.ps1
#
# If you get an execution-policy error, run once as admin:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
# =============================================================================

$ScriptDir    = $PSScriptRoot
$Venv         = Join-Path $ScriptDir ".venv"
$Req          = Join-Path $ScriptDir "requirements_ui.txt"
$ReqHashFile  = Join-Path $Venv ".requirements_hash"
$VenvPy       = Join-Path $Venv "Scripts\python.exe"

# Compute MD5 hash of requirements_ui.txt
function Get-ReqHash {
    try {
        return (Get-FileHash $Req -Algorithm MD5).Hash
    } catch {
        return (Get-Item $Req).LastWriteTimeUtc.Ticks.ToString()
    }
}

# Install / upgrade dependencies
function Install-Deps {
    Write-Host "==> Installing / updating dependencies..." -ForegroundColor Cyan
    & $VenvPy -m ensurepip --default-pip 2>$null
    & $VenvPy -m pip install --quiet --upgrade pip
    & $VenvPy -m pip install --quiet -r $Req
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ERROR: pip install failed. Check your internet connection and try again." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    # Save current hash so we skip next time
    $hash = Get-ReqHash
    [System.IO.File]::WriteAllText($ReqHashFile, $hash)
    Write-Host "==> Dependencies up to date." -ForegroundColor Green
    Write-Host ""
}

# Check / create venv
if (-not (Test-Path $VenvPy)) {
    Write-Host "==> First run - setting up virtual environment..." -ForegroundColor Cyan
    Write-Host ""

    # Find Python 3.10+
    $Python = $null
    foreach ($candidate in @("py","python","python3","python3.13","python3.12","python3.11","python3.10")) {
        try {
            $p = Get-Command $candidate -ErrorAction Stop
            $Python = $p.Source
            break
        } catch { }
    }

    if (-not $Python) {
        Write-Host "ERROR: Python 3.10+ not found." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Download and install from https://www.python.org/downloads/"
        Write-Host "  Make sure to check 'Add Python to PATH' during installation."
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 1
    }

    $version = & $Python --version 2>&1
    Write-Host "    Python  : $Python" -ForegroundColor Gray
    Write-Host "    Version : $version" -ForegroundColor Gray
    Write-Host ""

    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Could not create virtual environment." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    Install-Deps
    Write-Host "==> Environment ready." -ForegroundColor Green
    Write-Host ""
}

# Ensure dependencies are installed and functional
$needsInstall = $false
& $VenvPy -c "import customtkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Missing dependencies detected in venv - installing..." -ForegroundColor Yellow
    $needsInstall = $true
} else {
    $currentHash = Get-ReqHash
    $savedHash   = ""
    if (Test-Path $ReqHashFile) {
        $savedHash = (Get-Content $ReqHashFile).Trim()
    }
    if ($currentHash -ne $savedHash) {
        Write-Host "==> requirements_ui.txt changed - updating dependencies..." -ForegroundColor Cyan
        $needsInstall = $true
    }
}

if ($needsInstall) {
    Install-Deps
}

# Launch the UI
Write-Host "==> Starting DMD GIF Converter..." -ForegroundColor Green
& $VenvPy -m src.ui.launcher $args

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: The application exited with an error. See output above." -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
