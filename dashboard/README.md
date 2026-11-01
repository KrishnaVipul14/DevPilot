# DevPilot Dashboard (Frontend Source)

This folder contains the Next.js + TypeScript + Tailwind CSS source code for the local DevPilot web dashboard.

> **Note:** You do **not** need to build or run this manually just to use DevPilot. A production static build is already copied into `../devpilot/dashboard_server/static/` and served automatically when you run `devpilot dashboard`.

---

## Developing the Dashboard Locally

If you want to edit the UI components or pages:

### 1. Install dependencies

```bash
cd dashboard
npm install
```

### 2. Run in development mode

Start the Python backend in one terminal (from the repository you scanned):

```bash
devpilot dashboard --port 8765
```

Then start the Next.js dev server in a second terminal pointed at that local API:

```bash
# Windows PowerShell
$env:NEXT_PUBLIC_DEVPILOT_API="http://127.0.0.1:8765"
npm run dev

# macOS / Linux
NEXT_PUBLIC_DEVPILOT_API="http://127.0.0.1:8765" npm run dev
```

Open **http://localhost:3000** in your browser.

---

## Rebuilding for the Python Package

When you finish making changes to the frontend, run:

```bash
npm run build:engine
```

This runs `next build` (static export to `dashboard/out/`) and copies the generated static files straight into `../devpilot/dashboard_server/static/` so `devpilot dashboard` serves your updated UI.
