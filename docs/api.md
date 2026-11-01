# DevPilot Local API

The local server (`devpilot dashboard`) binds to `127.0.0.1` only and serves both
the static dashboard and this JSON API from the same origin (no CORS).

* All responses are JSON. Errors: HTTP 4xx/5xx with body `{"error": "message"}`.
* Mutating requests (`POST`) **must** send header `X-DevPilot: 1` and
  `Content-Type: application/json`. Requests from other origins are rejected
  (custom header forces a CORS preflight that the server never approves) and the
  `Host` header must be `127.0.0.1`/`localhost`.
* Finding references (`{ref}`) accept a report id (`DP001`) or a fingerprint.

## Read endpoints

| Method | Path | Response |
| --- | --- | --- |
| GET | `/api/status` | `{has_report, scan_id, finished_at, report_mtime, repository:{name,path}, ai:{available, provider, model, reason}}` |
| GET | `/api/report` | Full `Report` (see `devpilot/core/models.py`), with `findings[].verification` refreshed from memory and `ai` populated with cached explanations. `404` if no scan yet. |
| GET | `/api/history` | `{scans:[ScanRow], verifications:[VerificationRow]}` |
| GET | `/api/graph` | `{nodes:[GraphNode], edges:[GraphEdge], summary:GraphSummary}` (404 if no scan yet) |
| GET | `/api/impact?base=HEAD` | `ImpactReport` for current git changes vs `base` |
| GET | `/api/impact?symbol=validate_token` | `ImpactReport` for a hypothetical change to the symbol |
| GET | `/api/plan` | `{plan: Plan \| null}` |
| GET | `/api/patches` | `{patches:[Patch]}` |

## Mutating endpoints

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| POST | `/api/findings/{ref}/explain` | `{}` | `{explanation: AIExplanation}` (503 if AI unavailable) |
| POST | `/api/plan` | `{}` | `{plan: Plan}` (falls back to deterministic plan, `source:"deterministic"`) |
| POST | `/api/findings/{ref}/fix` | `{engine: "auto"\|"ruff"\|"ai"}` | `{patch: Patch}` (status `proposed`) |
| POST | `/api/patches/{patch_id}/verify` | `{}` | `{patch: Patch}` — clicking this is the explicit approval; runs in an isolated worktree |
| POST | `/api/patches/{patch_id}/apply` | `{}` | `{patch: Patch}` — writes to the working tree (refuses if files changed since proposal) |
| POST | `/api/patches/{patch_id}/discard` | `{}` | `{patch: Patch}` |

## Shapes

```ts
type ScanRow = { scan_id: string; started_at: string; finished_at: string; commit: string|null;
  branch: string|null; status: string; total: number; health_score: number;
  by_severity: Record<string, number>; new: number; existing: number; resolved: number; reintroduced: number };

type VerificationRow = { patch_id: string; finding_id: string; fingerprint: string; title: string;
  status: "verified"|"partially_verified"|"failed"|"not_verified"; created_at: string; checks: Check[] };

type GraphNode = { id: string; kind: "module"|"class"|"function"|"route"|"test"; name: string;
  file: string|null; line: number|null; module: string|null; meta?: Record<string, unknown> };
type GraphEdge = { source: string; target: string; kind: "imports"|"calls"|"defines"|"routes_to"|"tests";
  certainty: "resolved"|"inferred" };

type Risk = { level: "low"|"medium"|"high"|"critical"; reasons: string[] };
type ImpactReport = {
  base: string|null; mode: "git"|"symbol"; generated_at: string;
  changed_files: { path: string; status: string; changed_symbols: string[] }[];
  changed_symbols: { id: string; name: string; kind: string; file: string; line: number|null }[];
  impacts: { symbol: string; callers: string[]; dependent_modules: string[];
    routes: { id: string; method: string; path: string; handler: string }[];
    tests: { id: string; nodeid: string; file: string; certainty: "resolved"|"inferred" }[];
    risk: Risk }[];
  overall_risk: Risk; suggested_commands: string[]; limitations: string[] };

type PlanTask = { priority: number; title: string; why: string; resolution: string;
  finding_ids: string[]; tests: string[]; effort: "small"|"medium"|"large" };
type Plan = { source: "ai"|"deterministic"; provider: string|null; model: string|null;
  created_at: string; scan_id: string; summary: string; tasks: PlanTask[] };

type Check = { name: string; status: "passed"|"failed"|"skipped"|"error"; detail: string;
  command: string|null; duration_ms: number };
type Patch = { patch_id: string; finding_id: string; fingerprint: string; title: string;
  engine: "ruff"|"ai"; summary: string;
  status: "proposed"|"verified"|"partially_verified"|"failed"|"not_verified"|"applied"|"discarded";
  created_at: string; diff: string; files: string[];
  verification: null | { status: string; checks: Check[]; mode: "git-worktree"|"temp-copy"; finished_at: string } };
```
