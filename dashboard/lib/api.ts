import type {
  AIExplanation,
  FixEngine,
  GraphResponse,
  HistoryResponse,
  ImpactReport,
  Patch,
  Plan,
  Report,
  ScanRequest,
  ScanResponse,
  SettingsResponse,
  StatusResponse,
  UpdateSettingsRequest,
} from "./types";

/** Base URL for the local DevPilot API. Empty string = same origin (production). */
export const API_BASE = (process.env.NEXT_PUBLIC_DEVPILOT_API ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** True when the server could not be reached at all (network error). */
export function isNetworkError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 0;
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("DevPilot server is unreachable", 0);
  }
  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const msg =
      body && typeof body === "object" && "error" in body
        ? String((body as { error: unknown }).error)
        : `Request failed (HTTP ${res.status})`;
    throw new ApiError(msg, res.status);
  }
  return body as T;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

function post<T>(path: string, body: unknown = {}): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "X-DevPilot": "1", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const enc = encodeURIComponent;

export const api = {
  status: () => get<StatusResponse>("/api/status"),
  report: () => get<Report>("/api/report"),
  history: () => get<HistoryResponse>("/api/history"),
  graph: () => get<GraphResponse>("/api/graph"),
  impactGit: (base = "HEAD") => get<ImpactReport>(`/api/impact?base=${enc(base)}`),
  impactSymbol: (symbol: string) => get<ImpactReport>(`/api/impact?symbol=${enc(symbol)}`),
  plan: () => get<{ plan: Plan | null }>("/api/plan"),
  generatePlan: () => post<{ plan: Plan }>("/api/plan"),
  patches: () => get<{ patches: Patch[] }>("/api/patches"),
  explain: (ref: string) =>
    post<{ explanation: AIExplanation }>(`/api/findings/${enc(ref)}/explain`),
  fix: (ref: string, engine: FixEngine = "auto") =>
    post<{ patch: Patch }>(`/api/findings/${enc(ref)}/fix`, { engine }),
  verifyPatch: (id: string) => post<{ patch: Patch }>(`/api/patches/${enc(id)}/verify`),
  applyPatch: (id: string) => post<{ patch: Patch }>(`/api/patches/${enc(id)}/apply`),
  discardPatch: (id: string) => post<{ patch: Patch }>(`/api/patches/${enc(id)}/discard`),
  settings: () => get<SettingsResponse>("/api/settings"),
  updateSettings: (body: UpdateSettingsRequest) =>
    post<SettingsResponse>("/api/settings", body),
  changeRepository: (path: string) =>
    post<StatusResponse>("/api/repository", { path }),
  demo: () =>
    post<{ status: StatusResponse; report: Report }>("/api/demo"),
  scan: (options: ScanRequest = {}) =>
    post<ScanResponse>("/api/scan", options),
  mermaid: () =>
    get<{ mermaid: string }>("/api/mermaid"),
  ask: (question: string) =>
    post<{
      question: string;
      answer: string;
      provider: string;
      model: string;
      offline: boolean;
      referenced_files: string[];
    }>("/api/ask", { question }),
  testgen: (symbol: string) =>
    post<{
      symbol: string;
      target_file: string;
      suggested_test_file: string;
      language: string;
      framework: string;
      command: string;
      success: boolean;
      test_code: string;
      error?: string;
    }>("/api/testgen", { symbol }),
  deadcode: () =>
    get<{
      dead_symbols_count: number;
      lines_reclaimable: number;
      symbols: Array<{
        id: string;
        name: string;
        kind: string;
        file: string;
        line: number | null;
        lines_of_code: number;
        reason: string;
      }>;
    }>("/api/deadcode"),
  review: (base = "HEAD~1") =>
    post<{
      verdict: string;
      summary: string;
      key_strengths: string[];
      critical_risks: string[];
      actionable_suggestions: string[];
      markdown_review: string;
      provider: string;
    }>("/api/review", { base }),
  pr: (base = "HEAD~1") =>
    post<{
      title: string;
      summary: string;
      changes: string[];
      impact: string;
      testing_plan: string[];
      markdown_pr: string;
      provider: string;
    }>("/api/pr", { base }),
};
