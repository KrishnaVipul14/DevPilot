@echo off
rem ==============================================================================
rem DevPilot Quick Launcher for Windows (Command Prompt / Batch)
rem Automatically sets up Python virtualenv, installs dependencies, and launches DevPilot.
rem ==============================================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo                    DevPilot Launcher
echo         Your Repository's AI Engineering Assistant
echo ============================================================
echo.

rem 1. Locate compatible Python (3.10+)
set "PYTHON_CMD="

rem Check Python launcher (py -3)
py -3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto :python_found
)

rem Check python
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :python_found
)

rem Check python3
python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python3"
    goto :python_found
)

echo [ERROR] Python 3.10 or newer is required to run DevPilot.
echo Please install Python 3.10+ from https://www.python.org/downloads/
echo IMPORTANT: Make sure to check "Add Python to PATH" during installation.
exit /b 1

:python_found
for /f "delims=" %%v in ('%PYTHON_CMD% -c "import sys; print(str(sys.version_info[0])+'.'+str(sys.version_info[1])+'.'+str(sys.version_info[2]))"') do set "PY_VER=%%v"
echo [DevPilot] Found Python %PY_VER% (%PYTHON_CMD%)

rem 2. Check or create virtual environment
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_SCRIPTS=%VENV_DIR%\Scripts"
set "VENV_PY=%VENV_SCRIPTS%\python.exe"

if not exist "%VENV_PY%" (
    echo [DevPilot] Creating virtual environment in .venv...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
    echo [DevPilot] Virtual environment created.
)

rem 3. Ensure virtual environment Scripts is on PATH
set "PATH=%VENV_SCRIPTS%;%PATH%"

rem 4. Check DevPilot installation
if not exist "%VENV_SCRIPTS%\devpilot.exe" (
    echo [DevPilot] Installing DevPilot into virtual environment...
    "%VENV_PY%" -m pip install --upgrade pip setuptools wheel -q
    "%VENV_PY%" -m pip install -e ".[dev]" -q
    if errorlevel 1 (
        echo [DevPilot] Trying standard install without optional dev tools...
        "%VENV_PY%" -m pip install -e . -q
        if errorlevel 1 (
            echo [ERROR] Failed to install DevPilot dependencies.
            exit /b 1
        )
    )
    echo [DevPilot] DevPilot installed successfully.
)

rem 5. Handle Arguments or Launch Default Dashboard
set "CMD=%~1"

if "%CMD%"=="scan" (
    echo [DevPilot] Running scan...
    if "%~2"=="" (
        call devpilot scan .
    ) else (
        call devpilot %*
    )
    goto :done
)

if "%CMD%"=="test" (
    echo [DevPilot] Running test suite...
    call pytest tests\ -v
    goto :done
)

if "%CMD%"=="lint" (
    echo [DevPilot] Running linter...
    call ruff check devpilot tests
    goto :done
)

if "%CMD%"=="demo" (
    echo [DevPilot] Scanning demo application...
    cd /d "%SCRIPT_DIR%examples\demo-app"
    call devpilot scan .
    goto :done
)

if "%CMD%"=="dashboard" (
    echo [DevPilot] Starting local dashboard...
    if "%~2"=="" (
        call devpilot dashboard --open
    ) else (
        call devpilot %*
    )
    goto :done
)

if "%CMD%"=="web" (
    echo [DevPilot] Starting local dashboard...
    if "%~2"=="" (
        call devpilot web --open
    ) else (
        call devpilot %*
    )
    goto :done
)

if "%CMD%"=="help" goto :help
if "%CMD%"=="--help" goto :help
if "%CMD%"=="-h" goto :help
if "%CMD%"=="/?" goto :help

if not "%CMD%"=="" (
    call devpilot %*
    goto :done
)

rem Default behavior: scan if no report exists, then launch dashboard
if not exist "%SCRIPT_DIR%.devpilot\reports\latest.json" (
    echo [DevPilot] No previous scan report found. Running initial scan...
    call devpilot scan .
    echo.
)

echo [DevPilot] Launching DevPilot dashboard...
echo [DevPilot] URL: http://127.0.0.1:8765
echo [DevPilot] Press Ctrl+C to stop.
echo.
call devpilot dashboard --open
goto :done

:help
echo Usage: start.bat [command] [args...]
echo.
echo Commands:
echo   (default)     Scan repository (if needed) and launch web dashboard
echo   dashboard     Launch the local web dashboard (alias: web)
echo   scan [path]   Run repository scan
echo   test          Run pytest automated test suite
echo   lint          Run Ruff linter checks
echo   demo          Scan the included demo application
echo   help          Show this help message
echo.
echo Any other arguments are passed directly to the 'devpilot' CLI.
goto :done

:done
endlocal
