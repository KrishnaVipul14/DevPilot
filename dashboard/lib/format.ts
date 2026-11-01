import type { Severity } from "./types";

export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

export function severityRank(s: string): number {
  const i = SEVERITIES.indexOf(s as Severity);
  return i === -1 ? SEVERITIES.length : i;
}

/** Hex colours used by charts; keep aligned with the badge classes below. */
export const SEVERITY_HEX: Record<Severity, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#f59e0b",
  low: "#3b82f6",
  info: "#71717a",
};

export const SEVERITY_BADGE: Record<Severity, string> = {
  critical: "bg-red-500/15 text-red-400 ring-red-500/30",
  high: "bg-orange-500/15 text-orange-400 ring-orange-500/30",
  medium: "bg-amber-500/15 text-amber-400 ring-amber-500/30",
  low: "bg-blue-500/15 text-blue-400 ring-blue-500/30",
  info: "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30",
};

export const ACCENT_HEX = "#8b5cf6";

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 8) : "—";
}

export function fileLoc(file: string | null, line: number | null): string {
  if (!file) return "—";
  return line != null ? `${file}:${line}` : file;
}

export function healthColor(score: number): string {
  if (score >= 85) return "text-emerald-400";
  if (score >= 65) return "text-amber-400";
  if (score >= 40) return "text-orange-400";
  return "text-red-400";
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ");
}
