#!/usr/bin/env bash
# ==============================================================================
# DevPilot Quick Launcher (Linux / macOS / Windows Git Bash / WSL)
# Automatically sets up the environment, validates dependencies, runs an initial
# scan if needed, and launches the DevPilot local web dashboard.
# ==============================================================================

set -euo pipefail

# ANSI color codes
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BOLD}${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║                     DevPilot Launcher                      ║${NC}"
echo -e "${BOLD}${BLUE}║         Your Repository's AI Engineering Assistant         ║${NC}"
echo -e "${BOLD}${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 1. Locate compatible Python (3.10+)
PYTHON_BIN=""
for cmd in python3 python py; do
    if command -v "$cmd" >/dev/null 2>&1; then
        if [ "$cmd" = "py" ]; then
            if py -3 -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
                PYTHON_BIN="py -3"
                break
            fi
        elif "$cmd" -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}Error: Python 3.10 or newer is required to run DevPilot.${NC}"
    echo -e "Please install Python 3.10+ and ensure it is available in your PATH."
    exit 1
fi

PY_VERSION=$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null | tr -d '\r')
echo -e "${GREEN}✓ Found Python ${PY_VERSION} (${PYTHON_BIN})${NC}"

# 2. Check / Create Virtual Environment
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_BIN="$VENV_DIR/bin"
if [ -d "$VENV_DIR/Scripts" ]; then
    VENV_BIN="$VENV_DIR/Scripts"
fi

if [ ! -d "$VENV_DIR" ]; then
    echo -e "${CYAN}→ Creating virtual environment in .venv...${NC}"
    $PYTHON_BIN -m venv .venv
    echo -e "${GREEN}✓ Virtual environment created.${NC}"
    if [ -d "$VENV_DIR/Scripts" ]; then
        VENV_BIN="$VENV_DIR/Scripts"
    fi
fi

# 3. Activate Virtual Environment
if [ -f "$VENV_BIN/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_BIN/activate"
elif [ -f "$VENV_BIN/activate.bat" ] || [ -d "$VENV_BIN" ]; then
    export PATH="$VENV_BIN:$PATH"
else
    echo -e "${RED}Error: Could not locate virtual environment activation script in ${VENV_BIN}.${NC}"
    exit 1
fi

export PATH="$VENV_BIN:$PATH"

# 4. Check DevPilot Installation
DEVPILOT_CMD="devpilot"
if [ -f "$VENV_BIN/devpilot.exe" ]; then
    DEVPILOT_CMD="$VENV_BIN/devpilot.exe"
fi

if ! command -v "$DEVPILOT_CMD" >/dev/null 2>&1 && ! command -v devpilot >/dev/null 2>&1; then
    echo -e "${CYAN}→ Installing DevPilot into virtual environment...${NC}"
    python -m pip install --upgrade pip setuptools wheel -q
    python -m pip install -e ".[dev]" -q
    echo -e "${GREEN}✓ DevPilot installed.${NC}"
fi

# 5. Handle Arguments or Launch Default Dashboard
if [ $# -gt 0 ]; then
    case "$1" in
        scan)
            shift
            echo -e "${CYAN}→ Running DevPilot scan...${NC}"
            exec "$DEVPILOT_CMD" scan "${@:-.}"
            ;;
        test)
            shift
            echo -e "${CYAN}→ Running test suite...${NC}"
            exec pytest tests/ -v "$@"
            ;;
        lint)
            shift
            echo -e "${CYAN}→ Running linter...${NC}"
            exec ruff check devpilot tests "$@"
            ;;
        demo)
            shift
            echo -e "${CYAN}→ Scanning demo application...${NC}"
            cd "$SCRIPT_DIR/examples/demo-app"
            exec "$DEVPILOT_CMD" scan . "$@"
            ;;
        dashboard)
            shift
            echo -e "${CYAN}→ Starting DevPilot local dashboard...${NC}"
            exec "$DEVPILOT_CMD" dashboard --open "$@"
            ;;
        help|--help|-h)
            echo -e "Usage: ./start.sh [command] [args...]"
            echo ""
            echo "Commands:"
            echo "  (default)     Scan repository (if needed) and launch web dashboard"
            echo "  dashboard     Launch the local web dashboard"
            echo "  scan [path]   Run repository scan"
            echo "  test          Run pytest automated test suite"
            echo "  lint          Run Ruff linter checks"
            echo "  demo          Scan the included demo application"
            echo "  help          Show this help message"
            echo ""
            echo "Any other arguments are passed directly to the 'devpilot' CLI."
            exit 0
            ;;
        *)
            exec "$DEVPILOT_CMD" "$@"
            ;;
    esac
fi

# Default behavior: run initial scan if no report exists, then open dashboard
if [ ! -f "$SCRIPT_DIR/.devpilot/reports/latest.json" ]; then
    echo -e "${CYAN}→ No previous scan report found. Running initial scan...${NC}"
    "$DEVPILOT_CMD" scan .
    echo ""
fi

echo -e "${GREEN}✓ Launching DevPilot dashboard...${NC}"
echo -e "${YELLOW}→ URL: http://127.0.0.1:8765${NC}"
echo -e "${YELLOW}→ Press Ctrl+C to stop.${NC}"
echo ""
exec "$DEVPILOT_CMD" dashboard --open
