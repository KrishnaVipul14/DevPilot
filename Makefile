# DevPilot Developer Workflow & Automation
PYTHON ?= python3
VENV ?= .venv
BIN ?= $(VENV)/bin

.PHONY: help start setup install test lint scan dashboard demo clean build-dashboard

help:
	@echo "Available commands:"
	@echo "  make start            Run ./start.sh (setup environment + launch dashboard)"
	@echo "  make setup            Create virtual environment and install DevPilot with dev dependencies"
	@echo "  make test             Run test suite with pytest"
	@echo "  make lint             Run ruff checks across devpilot and tests"
	@echo "  make scan             Run devpilot offline self-scan"
	@echo "  make dashboard        Start local DevPilot dashboard on http://127.0.0.1:8765"
	@echo "  make demo             Run DevPilot scan on the demo application"
	@echo "  make build-dashboard  Rebuild Next.js dashboard and bundle static assets"
	@echo "  make clean            Remove build artifacts and virtual environment"

setup: $(VENV)/bin/activate

start: setup
	./start.sh

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip setuptools wheel
	$(BIN)/pip install -e ".[dev]"

install: setup

test: setup
	$(BIN)/pytest tests/ -v

lint: setup
	$(BIN)/ruff check devpilot tests

scan: setup
	$(BIN)/devpilot scan . --offline

dashboard: setup
	$(BIN)/devpilot dashboard --open

demo: setup
	cd examples/demo-app && ../../$(BIN)/devpilot scan .

build-dashboard:
	cd dashboard && npm install && npm run build:engine

clean:
	rm -rf $(VENV) build dist *.egg-info .pytest_cache .ruff_cache .devpilot
