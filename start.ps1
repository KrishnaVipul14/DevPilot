<#
.SYNOPSIS
DevPilot Quick Launcher for Windows PowerShell
Automatically sets up Python virtualenv, installs dependencies, and launches DevPilot.
#>
[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$Command = "",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$RemainingArgs = @()
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "                   DevPilot Launcher                        " -ForegroundColor Cyan
Write-Host "        Your Repository's AI Engineering Assistant          " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Locate compatible Python (3.10+)
$PythonCmd = $null
$PythonPrefix = @()
$CheckPyCode = "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"

if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        & py -3 -c $CheckPyCode 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = "py"
            $PythonPrefix = @("-3")
        }
    } catch {}
}

if (-not $PythonCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try {
        & python -c $CheckPyCode 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = "python"
            $PythonPrefix = @()
        }
    } catch {}
}

if (-not $PythonCmd -and (Get-Command python3 -ErrorAction SilentlyContinue)) {
    try {
        & python3 -c $CheckPyCode 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = "python3"
            $PythonPrefix = @()
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Python 3.10 or newer is required to run DevPilot." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "IMPORTANT: Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    exit 1
}

$PyVer = & $PythonCmd @PythonPrefix -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'
Write-Host "[DevPilot] Found Python $PyVer ($PythonCmd)" -ForegroundColor Green

# 2. Check / Create Virtual Environment
$VenvDir = Join-Path $ScriptDir ".venv"
$VenvScripts = Join-Path $VenvDir "Scripts"
$VenvPython = Join-Path $VenvScripts "python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[DevPilot] Creating virtual environment in .venv..." -ForegroundColor Cyan
    & $PythonCmd @PythonPrefix -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "[DevPilot] Virtual environment created." -ForegroundColor Green
}

# 3. Add venv Scripts to PATH for the current session
$env:PATH = "$VenvScripts;$env:PATH"

# 4. Check DevPilot Installation
$VenvDevpilot = Join-Path $VenvScripts "devpilot.exe"
if (-not (Test-Path $VenvDevpilot)) {
    Write-Host "[DevPilot] Installing DevPilot into virtual environment..." -ForegroundColor Cyan
    & $VenvPython -m pip install --upgrade pip setuptools wheel -q
    & $VenvPython -m pip install -e ".[dev]" -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install DevPilot dependencies." -ForegroundColor Red
        exit 1
    }
    Write-Host "[DevPilot] DevPilot installed successfully." -ForegroundColor Green
}

# 5. Dispatch command
switch ($Command) {
    "scan" {
        Write-Host "[DevPilot] Running scan..." -ForegroundColor Cyan
        $target = if ($RemainingArgs.Count -gt 0) { $RemainingArgs } else { @(".") }
        & devpilot scan @target
        exit $LASTEXITCODE
    }
    "test" {
        Write-Host "[DevPilot] Running test suite..." -ForegroundColor Cyan
        & pytest tests/ -v @RemainingArgs
        exit $LASTEXITCODE
    }
    "lint" {
        Write-Host "[DevPilot] Running linter..." -ForegroundColor Cyan
        & ruff check devpilot tests @RemainingArgs
        exit $LASTEXITCODE
    }
    "demo" {
        Write-Host "[DevPilot] Scanning demo application..." -ForegroundColor Cyan
        Set-Location (Join-Path $ScriptDir "examples\demo-app")
        & devpilot scan . @RemainingArgs
        exit $LASTEXITCODE
    }
    "dashboard" {
        Write-Host "[DevPilot] Starting local dashboard..." -ForegroundColor Cyan
        & devpilot dashboard --open @RemainingArgs
        exit $LASTEXITCODE
    }
    { $_ -in "help", "--help", "-h", "/?" } {
        Write-Host "Usage: .\start.ps1 [command] [args...]"
        Write-Host ""
        Write-Host "Commands:"
        Write-Host "  (default)     Scan repository (if needed) and launch web dashboard"
        Write-Host "  dashboard     Launch the local web dashboard"
        Write-Host "  scan [path]   Run repository scan"
        Write-Host "  test          Run pytest automated test suite"
        Write-Host "  lint          Run Ruff linter checks"
        Write-Host "  demo          Scan the included demo application"
        Write-Host "  help          Show this help message"
        Write-Host ""
        Write-Host "Any other arguments are passed directly to the 'devpilot' CLI."
        exit 0
    }
    default {
        if ($Command) {
            & devpilot $Command @RemainingArgs
            exit $LASTEXITCODE
        }
    }
}

# Default action: run initial scan if no report exists, then open dashboard
$LatestReport = Join-Path $ScriptDir ".devpilot\reports\latest.json"
if (-not (Test-Path $LatestReport)) {
    Write-Host "[DevPilot] No previous scan report found. Running initial scan..." -ForegroundColor Cyan
    & devpilot scan .
    Write-Host ""
}

Write-Host "[DevPilot] Launching DevPilot dashboard..." -ForegroundColor Green
Write-Host "[DevPilot] URL: http://127.0.0.1:8765" -ForegroundColor Yellow
Write-Host "[DevPilot] Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""
& devpilot dashboard --open
