// TypeScript mirror of devpilot/core/models.py and docs/api.md.
// Keep in sync with the Python engine; these are the dashboard's only data contract.

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Confidence = "high" | "medium" | "low";
export type FindingStatus = "new" | "existing" | "reintroduced";
export type VerificationStatus =
  | "verified"
  | "partially_verified"
  | "failed"
  | "not_verified";
export type AnalyzerState = "ok" | "skipped" | "error";
export type ScanStatus = "completed" | "partial" | "failed";

export interface Finding {
  id: string;
  fingerprint: string;
  module: string;
  rule: string;
  severity: Severity;
  title: string;
  file: string | null;
  line: number | null;
  end_line: number | null;
  column: number | null;
  symbol: string | null;
  evidence: string;
  suggestion: string;
  confidence: Confidence;
  status: FindingStatus;
  verification: VerificationStatus;
  fixable: boolean;
  references: string[];
  metadata: Record<string, unknown>;
}

export interface AnalyzerRun {
  name: string;
  status: AnalyzerState;
  duration_ms: number;
  findings: number;
  message: string;
}

export interface RepositoryInfo {
  name: string;
  path: string;
  git_root: string | null;
  commit: string | null;
  branch: string | null;
  dirty: boolean | null;
}

export interface Summary {
  total: number;
  by_severity: Record<string, number>;
  by_module: Record<string, number>;
  health_score: number;
  health_formula: string;
  files_scanned: number;
}

export interface MemoryDelta {
  previous_scan_id: string | null;
  new: number;
  existing: number;
  reintroduced: number;
  resolved: number;
  severity_changed: number;
  resolved_findings: Record<string, unknown>[];
}

export interface AIExplanation {
  finding_fingerprint: string;
  provider: string;
  model: string;
  created_at: string;
  summary: string;
  root_cause: string;
  impact: string;
  recommendation: string;
  suggested_tests: string[];
  caveats: string;
}

export interface GraphSummary {
  modules: number;
  functions: number;
  classes: number;
  routes: number;
  tests: number;
  edges: number;
}

export interface Report {
  schema_version: string;
  tool: string;
  version: string;
  scan_id: string;
  repository: RepositoryInfo;
  started_at: string;
  finished_at: string;
  status: ScanStatus;
  summary: Summary;
  findings: Finding[];
  analyzers: AnalyzerRun[];
  graph: GraphSummary | null;
  memory: MemoryDelta | null;
  ai: Record<string, AIExplanation>;
  limitations: string[];
}

export interface StatusResponse {
  has_report: boolean;
  scan_id: string | null;
  finished_at: string | null;
  report_mtime: number | string | null;
  repository: { name: string; path: string };
  ai: {
    available: boolean;
    provider: string | null;
    model: string | null;
    reason: string | null;
  };
}

export interface ScanRow {
  scan_id: string;
  started_at: string;
  finished_at: string;
  commit: string | null;
  branch: string | null;
  status: string;
  total: number;
  health_score: number;
  by_severity: Record<string, number>;
  new: number;
  existing: number;
  resolved: number;
  reintroduced: number;
}

export type CheckStatus = "passed" | "failed" | "skipped" | "error";

export interface Check {
  name: string;
  status: CheckStatus;
  detail: string;
  command: string | null;
  duration_ms: number;
}

export interface VerificationRow {
  patch_id: string;
  finding_id: string;
  fingerprint: string;
  title: string;
  status: VerificationStatus;
  created_at: string;
  checks: Check[];
}

export interface HistoryResponse {
  scans: ScanRow[];
  verifications: VerificationRow[];
}

export type NodeKind = "module" | "class" | "function" | "route" | "test";
export type EdgeKind = "imports" | "calls" | "defines" | "routes_to" | "tests";
export type Certainty = "resolved" | "inferred";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  name: string;
  file: string | null;
  line: number | null;
  module: string | null;
  meta?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: EdgeKind;
  certainty: Certainty;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  summary: GraphSummary;
}

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface Risk {
  level: RiskLevel;
  reasons: string[];
}

export interface ImpactEntry {
  symbol: string;
  callers: string[];
  dependent_modules: string[];
  routes: { id: string; method: string; path: string; handler: string }[];
  tests: { id: string; nodeid: string; file: string; certainty: Certainty }[];
  risk: Risk;
}

export interface ImpactReport {
  base: string | null;
  mode: "git" | "symbol";
  generated_at: string;
  changed_files: { path: string; status: string; changed_symbols: string[] }[];
  changed_symbols: {
    id: string;
    name: string;
    kind: string;
    file: string;
    line: number | null;
  }[];
  impacts: ImpactEntry[];
  overall_risk: Risk;
  suggested_commands: string[];
  limitations: string[];
}

export interface PlanTask {
  priority: number;
  title: string;
  why: string;
  resolution: string;
  finding_ids: string[];
  tests: string[];
  effort: "small" | "medium" | "large";
}

export interface Plan {
  source: "ai" | "deterministic";
  provider: string | null;
  model: string | null;
  created_at: string;
  scan_id: string;
  summary: string;
  tasks: PlanTask[];
}

export type PatchStatus =
  | "proposed"
  | "verified"
  | "partially_verified"
  | "failed"
  | "not_verified"
  | "applied"
  | "discarded";

export interface PatchVerification {
  status: string;
  checks: Check[];
  mode: "git-worktree" | "temp-copy";
  finished_at: string;
}

export interface Patch {
  patch_id: string;
  finding_id: string;
  fingerprint: string;
  title: string;
  engine: "ruff" | "ai";
  summary: string;
  status: PatchStatus;
  created_at: string;
  diff: string;
  files: string[];
  verification: PatchVerification | null;
}

export type FixEngine = "auto" | "ruff" | "ai";
