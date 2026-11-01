# DevPilot — Your Repository's AI Engineering Assistant

> **"Understand your codebase. Fix problems. Verify improvements. Build better software."**

DevPilot is a local-first, CLI-first repository intelligence and engineering assistant for Python projects. It unifies static code health analysis, dependency vulnerability auditing, configuration & secret hygiene, documentation drift detection, AST code-relationship graphing, Git change-impact analysis, safe isolated fix verification, and SQLite repository memory into one cohesive workflow:

```text
DETECT → UNDERSTAND → ANALYZE IMPACT → PRIORITIZE → FIX → VERIFY → REMEMBER
```

---

## Architecture Overview

```text
CLI (Typer) ──► Scanner & Analyzer Registry
                   ├── Code Health (Ruff + AST maintainability)
                   ├── Dependency Security (OSV.dev / pip-audit + CVSS v3)
                   ├── Configuration & Setup Doctor (.env vs code, secret hygiene)
                   ├── Documentation Drift (README examples & docstring params vs AST)
                   ├── Repository Intelligence Graph (AST modules, defs, calls, routes, tests)
                   └── Git Change Impact Analysis (diff → symbols → callers/routes/tests → risk)
                        │
                        ▼
           Unified Validated Report (.devpilot/reports/latest.json)
                        │
                        ├──► SQLite Repository Memory (.devpilot/devpilot.db)
                        ├──► Safe Fix & Isolated Git Worktree Verifier
                        ├──► Modular AI Assistant (Gemini API + deterministic fallback)
                        └──► Local Python HTTP Server (127.0.0.1) ──► Next.js Dashboard
```

---

## Core Modules

1. **Module A — Automated Repository Scanner (`devpilot/analyzers/`)**
   - **Code Health (`code_health.py`):** Runs Ruff (`F`, `E9`, `B`, `C901`, `S102/S307/S506/S602`, `E722`) plus AST checks for overly long functions and excessive parameters.
   - **Dependency Security (`dependencies.py`, `osv.py`, `manifests.py`):** Parses `requirements*.txt`, `pyproject.toml`, `poetry.lock`, and `uv.lock`. Queries **OSV.dev** (or `pip-audit`) for known advisories, computes CVSS v3 base scores, recommends fixed versions, and clearly separates security vulnerabilities from merely outdated packages.
   - **Configuration & Setup Doctor (`setup_doctor.py`, `envsecrets.py`):** Extracts `os.environ` / `os.getenv` references from AST and compares them against `.env.example`. Checks `.gitignore` coverage for `.env` files without ever reading `.env` contents, and detects hardcoded secrets with automatic value redaction.
   - **Documentation Drift (`documentation.py`):** Compares `:param:` / Google-style `Args:` docstrings against actual AST function signatures, parses fenced Python blocks in `README.md` / Markdown files to detect broken calls to repository functions, and flags documented env vars missing from code.

2. **Module B — Repository Intelligence Graph (`devpilot/analyzers/repository_graph.py`)**
   - Builds a static AST graph of modules, classes, functions, HTTP route decorators (`@app.get`, `@app.post`, etc.), and `pytest` test nodes.
   - Tracks `imports`, `defines`, `calls`, and `routes_to` edges, explicitly labeling heuristic method-name matches as `inferred`.

3. **Module C — Change Impact Analysis (`devpilot/analyzers/change_impact.py`)**
   - Parses `git diff` (or accepts `--symbol <name>`) to map modified lines to enclosing functions/classes, traverses reverse call and import edges to find affected callers, API endpoints, and relevant tests, and produces an explainable risk level (`Low`, `Medium`, `High`, `Critical`) with concrete evidence.

4. **Module D — AI Developer Assistant (`devpilot/ai/`)**
   - Integrates **Google Gemini** (`gemini-2.5-flash` by default) through a modular `AIProvider` interface.
   - Sends only redacted, relevant code snippets framed inside `<untrusted_repository_content>` tags. Never reads or uploads `.env` files.
   - Every CLI command and dashboard view continues to work when `GEMINI_API_KEY` is unset or AI is disabled.

5. **Module E — Safe AI Fix Engine & Isolated Verifier (`devpilot/fixes/`)**
   - Generates deterministic fixes (Ruff safe edits, dependency version upgrades, `.env.example` entries) or AI search-and-replace patches.
   - Displays a unified diff and requires explicit approval before verification or application.
   - Verifies patches inside an **isolated temporary Git worktree** (or isolated temp copy) using `py_compile`, `ruff`, and targeted `pytest` runs with timeouts. Reports honest verification statuses (`VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `NOT_VERIFIED`).

6. **Module F — Repository Memory (`devpilot/memory/`)**
   - Persists scan summaries, line-independent finding fingerprints, lifecycle states (`new`, `existing`, `resolved`, `reintroduced`), AI explanations, plans, and patch verification audit logs in `.devpilot/devpilot.db` (SQLite).

---

## Installation

### Prerequisites
- **Python 3.10+** (compatible with Python 3.10, 3.11, 3.12+)
- **Git**
- **Node.js 20+** *(optional — only needed if rebuilding the Next.js static dashboard; the pre-built static bundle is already included in `devpilot/dashboard_server/static/`)*

### Install DevPilot

```bash
git clone https://github.com/KrishnaVipul14/DevPilot.git
cd DevPilot

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

### Optional: Configure Gemini API Key

Copy `.env.example` or export `GEMINI_API_KEY` in your shell:

```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your-gemini-api-key"

# macOS / Linux
export GEMINI_API_KEY="your-gemini-api-key"
```

---

## CLI Usage

```bash
# 1. Initialize DevPilot configuration (devpilot.yml)
devpilot init .

# 2. Scan a repository (saves .devpilot/reports/latest.json and updates SQLite memory)
devpilot scan .
devpilot scan . --offline          # Skip OSV.dev network calls

# 3. Launch the local dashboard (binds strictly to http://127.0.0.1:8765)
devpilot dashboard --port 8765

# 4. Inspect scan history and health score trends
devpilot history

# 5. Analyze Git diff impact or simulate changing a specific function
devpilot impact
devpilot impact --symbol validate_token

# 6. Explain a finding (uses Gemini AI if configured, plus deterministic evidence)
devpilot explain DP001

# 7. Propose a fix diff, verify in an isolated Git worktree, or discard
devpilot fix DP001
devpilot verify DP001
devpilot verify DP001 --apply --yes
devpilot fix DP001 --discard

# 8. Generate a prioritized improvement plan
devpilot plan

# 9. View or export the latest report (table, json, markdown)
devpilot report --format markdown --output report.md
```

---

## Try the Included Demo Repository (`examples/demo-app`)

`examples/demo-app` is a realistic Python billing & authentication service containing intentionally seeded issues across all four analyzer modules:

```bash
cd examples/demo-app

# Run a full scan (including live OSV.dev vulnerability lookup)
devpilot scan .

# Analyze the blast radius of modifying validate_token() in auth.py
devpilot impact --symbol validate_token

# Generate a prioritized action plan
devpilot plan

# Propose and verify a fix in an isolated worktree
devpilot fix DP001 --verify --yes

# Launch the local web dashboard for demo-app
devpilot dashboard --port 8765
```

Then open **http://127.0.0.1:8765** in your browser to explore:
- **Overview:** Health score & formula, severity breakdown, analyzer statuses, memory delta, and health trend chart.
- **Findings:** Search/filter findings, inspect evidence, generate AI explanations, and propose patches.
- **Code Intelligence:** Interactive module/function relationship explorer and Git / symbol impact simulator.
- **AI Action Plan:** Prioritized engineering tasks with linked findings and test commands.
- **Fix Review:** Colored unified diff viewer, isolated worktree verification runner, apply, and discard controls.
- **Repository Memory:** Historical scan table, health trend line chart, new vs. resolved bar chart, and verification audit log.

---

## Rebuilding the Frontend Dashboard

The Next.js static export is pre-built into `devpilot/dashboard_server/static/`. If you modify files under `dashboard/`:

```bash
cd dashboard
npm install
npm run build:engine
```

---

## GitHub Actions Integration

DevPilot includes both a reusable composite action (`action/action.yml`) and a ready-to-run workflow (`.github/workflows/devpilot.yml`) that runs on pull requests with minimal `contents: read` permissions, emits GitHub file/line annotations (`::error`, `::warning`, `::notice`), and writes a Markdown Job Summary with PR change-impact analysis.

---

## Honest Limitations

- **Static Analysis Scope:** Static AST and linter analysis cannot detect every runtime defect, dynamic import, reflection call, or business-logic flaw. Edges matched by method name alone are explicitly marked `inferred`.
- **Dependency Auditing:** Precise vulnerability matching requires pinned versions (`==`) or lock files (`poetry.lock`, `uv.lock`) and advisory coverage in OSV.dev.
- **AI Assistance:** AI explanations and AI-generated patches are non-deterministic and clearly labeled in both the CLI and Dashboard. A proposed patch is never marked `VERIFIED` unless static checks and relevant tests pass in an isolated workspace.
