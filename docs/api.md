# DevPilot Local Server API

When you run `devpilot dashboard`, DevPilot starts a local Python HTTP server on `127.0.0.1` (default port `8765`). It serves both the static web dashboard and the JSON endpoints below from the same origin.

## Security rules

1. **Localhost only:** The server only binds to `127.0.0.1` and checks that the `Host` header is `127.0.0.1` or `localhost`.
2. **CSRF protection on `POST` requests:** Every `POST` request must include the header `X-DevPilot: 1` and `Content-Type: application/json`. Requests without `X-DevPilot: 1` are rejected with `HTTP 403`.
3. **Error format:** Any failed request returns `HTTP 4xx/5xx` with JSON:
   ```json
   { "error": "Human-readable explanation" }
   ```

---

## GET Endpoints (Read-only)

| Endpoint | What it returns |
| --- | --- |
| `GET /api/status` | Server status, whether a scan report exists, latest `scan_id`, file timestamp (`report_mtime`) used for 2.5s live polling, repo name/path, and whether AI (`GEMINI_API_KEY`) is configured. |
| `GET /api/report` | The latest unified scan report (`.devpilot/reports/latest.json`), merged with cached AI explanations and patch verification statuses from SQLite. Returns `404` if no scan has been run yet. |
| `GET /api/history` | Past scans and patch verification runs from `.devpilot/devpilot.db`. |
| `GET /api/graph` | The repository's AST code graph (`nodes`, `edges`, and counts). Returns `404` if no scan has been run yet. |
| `GET /api/impact?base=HEAD` | Change-impact report for current uncommitted Git changes compared to `base`. |
| `GET /api/impact?symbol=validate_token` | What-if impact report showing callers, dependent modules, API routes, tests, and risk level if `validate_token` is modified. |
| `GET /api/plan` | The most recently generated improvement plan (or `{"plan": null}`). |
| `GET /api/patches` | All proposed, verified, applied, or discarded patches recorded in SQLite. |

---

## POST Endpoints (Actions)

*(All `POST` requests require header `X-DevPilot: 1`)*

| Endpoint | Request Body | What it does |
| --- | --- | --- |
| `POST /api/findings/{ref}/explain` | `{}` | Generates (or loads cached) AI explanation for finding ID (`DP001`) or fingerprint. Returns `503` if AI is not configured. |
| `POST /api/plan` | `{}` | Generates a prioritized improvement plan. Uses Gemini AI if available, or falls back to deterministic prioritization (`source: "deterministic"`). |
| `POST /api/findings/{ref}/fix` | `{"engine": "auto" \| "ruff" \| "ai"}` | Creates a proposed patch diff for the finding without modifying working-tree files. |
| `POST /api/patches/{patch_id}/verify` | `{}` | **Explicit approval step:** applies the patch inside an isolated temporary Git worktree (or temp copy) and runs `py_compile`, `ruff`, and targeted `pytest`. |
| `POST /api/patches/{patch_id}/apply` | `{}` | Writes a verified patch to the actual working-tree files (refuses if the target file changed since the patch was proposed). |
| `POST /api/patches/{patch_id}/discard` | `{}` | Marks the proposed patch as `discarded`. |
