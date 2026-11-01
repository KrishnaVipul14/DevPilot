# DevPilot

**Your repository's AI engineering assistant.**  
*Understand your codebase. Fix problems. Verify improvements. Build better software.*

---

## What is DevPilot?

When you work on a real project, you end up jumping between five different tools just to keep things healthy: a linter for code bugs, a security scanner for dependencies, grep to see what breaks if you change a function, a test runner to check your fix, and notes to remember what you already fixed last week.

**DevPilot** brings all of that into one local tool.

You run it from your terminal. It scans your project, maps out how your files and functions connect, tells you what's broken (and what's risky to change), helps you generate fixes, **tests those fixes in a safe temporary copy of your repo before touching your actual files**, and remembers every scan over time.

It also comes with a clean local web dashboard that runs on `127.0.0.1` — no cloud account, no external database, and no uploading your code to third-party servers.

---

## How the workflow works

```text
DETECT  →  UNDERSTAND  →  ANALYZE IMPACT  →  PRIORITIZE  →  FIX  →  VERIFY  →  REMEMBER
```

1. **Detect** — Finds code bugs, vulnerable packages, missing `.env` config, hardcoded secrets, and outdated docs.
2. **Understand** — Builds a map of your Python files, functions, classes, API routes, and tests. You can also ask AI to explain any issue in plain English.
3. **Analyze Impact** — Looks at your `git diff` (or any function name you pick) and shows which functions, API routes, and tests depend on it.
4. **Prioritize** — Groups findings into a step-by-step action plan so you tackle critical bugs and security issues first.
5. **Fix** — Creates a code diff for a problem (using either fast deterministic rules or AI).
6. **Verify** — Applies the diff inside an isolated Git worktree and runs syntax checks, Ruff, and `pytest` to prove the fix actually works before you apply it to your working tree.
7. **Remember** — Saves every scan in a local SQLite database (`.devpilot/devpilot.db`) so you can see which issues are new, resolved, or reintroduced.

---

## Quick Start (Beginner Friendly — 1 Minute)

### 1. Requirements
- **Python 3.10 or newer** (check with `python3 --version` or `py --version`)
- **Git**

*(Node.js is **not** required to use DevPilot or view the dashboard — the compiled dashboard is already bundled inside the repository!)*

### 2. Instant 1-Command Launchers

DevPilot includes automated start scripts that automatically create the `.venv`, install DevPilot and dependencies, perform an initial scan, and open the web dashboard:

- **Windows (Command Prompt / File Explorer):**
  Just double-click **`start.bat`** or run:
  ```cmd
  start.bat
  ```
- **Windows (PowerShell):**
  ```powershell
  .\start.ps1
  ```
- **macOS / Linux / Git Bash:**
  ```bash
  ./start.sh
  ```

Your browser will automatically open to **`http://127.0.0.1:8765`** with your project health score, findings, architecture graph, and action plan!

---

### Manual Setup (Optional)

If you prefer setting up manually in your terminal:

```bash
git clone https://github.com/algospider/DevPilot.git
cd DevPilot

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate       # On Windows: .\.venv\Scripts\activate

# Install DevPilot
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"

# Scan current directory and open dashboard
devpilot scan .
devpilot dashboard --open
```

### 3. Scan a project and open the dashboard

Open **Terminal 1** and run a scan:

```bash
devpilot init .
devpilot scan .
```

Open **Terminal 2** and start the dashboard:

```bash
devpilot dashboard
```

Now open **http://127.0.0.1:8765** in your browser. Whenever you run `devpilot scan .` again, the dashboard updates automatically within a couple of seconds.

---

## Setting up AI (Optional — Groq & Google Gemini)

DevPilot works 100% fine **without** an AI key. All code scanning, dependency security checks, blast radius analysis, history tracking, action plans, and auto-fixes work offline.

If you want AI explanations (`devpilot explain`), AI action plans, and AI-assisted code patches:

1. **Via Web Dashboard (Easiest):**
   - Click **`AI Config`** in the bottom-left sidebar of the dashboard (or press `⌘K` / `Ctrl+K`).
   - Select **Groq** or **Gemini**, paste your free API key, and click Save. DevPilot will remember it automatically!
2. **Via Environment File (`.env`):**
   ```bash
   GROQ_API_KEY="your-groq-api-key"
   # or
   GEMINI_API_KEY="your-gemini-api-key"
   ```

**Privacy & safety with AI:**
- DevPilot **never** scans or uploads `.env` files or private keys.
- Any secret-looking string in code is redacted before anything is sent to the AI provider.
- Only the small code snippet around the finding is sent — never your whole repository.

---

## All CLI Commands

| Command | What it does |
| --- | --- |
| `devpilot init .` | Creates a `devpilot.yml` config file and sets up `.devpilot/`. |
| `devpilot scan .` | Scans the repo and saves the report to `.devpilot/reports/latest.json`. Add `--offline` to skip network checks. |
| `devpilot dashboard` | Starts the local web UI on `http://127.0.0.1:8765`. Add `--open` to launch your browser automatically. |
| `devpilot impact` | Checks your current `git diff` and shows affected functions, API routes, tests, and risk level. |
| `devpilot impact --symbol validate_token` | Shows what would be affected if you changed `validate_token()`. |
| `devpilot explain DP001` | Explains finding `DP001` in detail (uses Groq AI if `GROQ_API_KEY` is set). |
| `devpilot fix DP001` | Generates a proposed fix diff for `DP001` without touching your files. |
| `devpilot verify DP001` | Tests the proposed patch inside an isolated Git worktree (`py_compile` + `ruff` + `pytest`). Add `--apply` to write it to your files once verified. |
| `devpilot fix DP001 --discard` | Throws away a proposed patch safely. |
| `devpilot plan` | Creates a prioritized improvement plan from the latest scan. |
| `devpilot history` | Shows past scans, health score trends, and patch verification results. |
| `devpilot report` | Prints or exports the latest report (`--format table`, `json`, or `markdown`). |
| `devpilot ci .` | Runs in GitHub Actions mode (prints PR annotations and writes a Markdown summary). |

---

## Try the Demo Project (`examples/demo-app`)

We included a small, realistic sample project in `examples/demo-app/` (an auth and billing service) that has real bugs planted in it so you can test every feature right away:

- **Unused imports** (`json` in `auth.py`, `sys` in `billing.py`)
- **Undefined variable** (`default_discount_rate` in `billing.py` — would crash at runtime)
- **Vulnerable packages** in `requirements.txt` (`pyyaml==5.3.1`, `urllib3==1.26.4`, `requests==2.25.0`), checked live against **OSV.dev**
- **Missing `.env.example` variables** (`JWT_ISSUER` and `STRIPE_WEBHOOK_SECRET` are used in code but missing from `.env.example`)
- **Outdated docs** (`README.md` calls `create_invoice()` with old arguments that no longer exist in `billing.py`)
- **Connected functions, routes, and tests** (`validate_token()` is called by `require_user()` and `authorize_and_bill()`, used by 3 API routes, and tested in `tests/test_auth_and_billing.py`)

### Run the demo step by step:

```bash
cd examples/demo-app

# 1. Scan the demo repo
devpilot scan .

# 2. See what depends on validate_token()
devpilot impact --symbol validate_token

# 3. Explain a finding with Groq AI
devpilot explain DP001

# 4. Get a prioritized action plan
devpilot plan

# 5. Propose and verify a fix in an isolated worktree
devpilot fix DP001 --verify --yes

# 6. Check the scan & verification history
devpilot history

# 7. Open the dashboard for the demo app
devpilot dashboard
```

---

## What's Inside the Dashboard?

When you open `http://127.0.0.1:8765`, you get six pages:

1. **Overview** — Your repo's health score (with the exact math formula shown), issue counts by severity, analyzer status, what changed since the last scan, and a health trend chart.
2. **Findings** — Search and filter every issue by severity, module, or status (`new`, `existing`, `reintroduced`). Click any finding to see the code evidence, ask AI for an explanation, or click **Propose Fix Patch**.
3. **Code Intelligence** — Browse modules, classes, and functions to see what imports or calls what. Run live **Git Diff Impact** or type any function name to simulate a change and copy the suggested `pytest` command.
4. **AI Action Plan** — A prioritized checklist grouping related findings into clear tasks, showing why each task matters and which tests to run.
5. **Fix Review** — View the color-coded unified diff for each proposed patch, click **Approve & Verify in Isolated Worktree** to run checks safely, then **Apply to Working Tree** or **Discard**.
6. **Repository Memory** — Charts and tables showing your health score over time, new vs. resolved issues per scan, and past verification runs.

---

## GitHub Actions Integration

DevPilot runs in CI on pull requests. The workflow in `.github/workflows/devpilot.yml` (and the reusable action in `action/action.yml`):

1. Checks out the PR with read-only permissions (`contents: read`).
2. Installs DevPilot and runs the analyzers + PR diff impact analysis.
3. Posts inline annotations (`::error`, `::warning`, `::notice`) directly on the changed files in the GitHub PR view.
4. Writes a clean Markdown summary table to the GitHub Actions Job Summary.

---

## Project Structure

```text
DevPilot/
├── devpilot/
│   ├── cli/                # Typer CLI commands and terminal tables
│   ├── core/               # Scanner, config loader, Pydantic models, report writer
│   ├── analyzers/          # Code health, dependencies (OSV), setup doctor, docs, AST graph, git impact
│   ├── ai/                 # Groq client, context builder (with secret redaction), prompts, action plans
│   ├── fixes/              # Diff generator, isolated Git worktree verifier, safe patch applier
│   ├── memory/             # SQLite database and stable finding fingerprints
│   ├── dashboard_server/   # Local 127.0.0.1 HTTP server + pre-built static dashboard
│   ├── integrations/       # GitHub Actions annotations and job summary formatter
│   └── utils/              # Safe subprocess runner (with timeouts) and Git helpers
├── dashboard/              # Next.js + TypeScript + Tailwind + Recharts frontend source
├── examples/demo-app/      # Sample Python project with seeded issues for testing
├── action/action.yml       # Reusable GitHub Action
├── .github/workflows/      # CI workflow
├── docs/api.md             # Local JSON API documentation
├── tests/                  # Automated pytest suite
├── devpilot.yml            # Default configuration
└── pyproject.toml          # Python package setup
```

---

## Honest Limitations

We built DevPilot to be genuinely useful, which means being upfront about what static tools and LLMs can and cannot do:

- **Static analysis can't catch everything:** Ruff and Python AST parsing are great at catching syntax errors, undefined names, unused imports, and structural issues, but they cannot prove your business logic is right or follow dynamic runtime tricks (`getattr`, monkey-patching, reflection). When a call relationship is guessed by method name alone, DevPilot labels it `inferred`.
- **Dependency checks need pinned versions:** To check a package against OSV.dev, DevPilot needs an exact version (like `requests==2.25.0` or a lockfile). Unpinned ranges like `requests>=2.0` are flagged as informational so you know they weren't audited.
- **AI suggestions are never trusted blindly:** Any explanation or patch created by AI is clearly badged as `AI-generated`. DevPilot never touches your working tree automatically, and a patch is only marked `VERIFIED` after syntax checks, Ruff, and `pytest` pass inside an isolated workspace.
