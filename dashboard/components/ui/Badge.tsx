import type { ReactNode } from "react";
import { SEVERITY_BADGE } from "@/lib/format";
import type { RiskLevel, Severity } from "@/lib/types";

const BASE =
  "inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset";

export function Badge({
  children,
  tone = "neutral",
  className = "",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger" | "info";
  className?: string;
  title?: string;
}) {
  const tones = {
    neutral: "bg-zinc-500/10 text-zinc-300 ring-zinc-500/25",
    accent: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
    success: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
    warning: "bg-amber-500/15 text-amber-400 ring-amber-500/30",
    danger: "bg-red-500/15 text-red-400 ring-red-500/30",
    info: "bg-blue-500/15 text-blue-400 ring-blue-500/30",
  } as const;
  return (
    <span title={title} className={`${BASE} ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  const cls = SEVERITY_BADGE[severity as Severity] ?? SEVERITY_BADGE.info;
  return <span className={`${BASE} uppercase tracking-wide ${cls}`}>{severity}</span>;
}

export function RiskBadge({ level }: { level: RiskLevel | string }) {
  const map: Record<string, string> = {
    critical: SEVERITY_BADGE.critical,
    high: SEVERITY_BADGE.high,
    medium: SEVERITY_BADGE.medium,
    low: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  };
  return (
    <span className={`${BASE} uppercase tracking-wide ${map[level] ?? SEVERITY_BADGE.info}`}>
      {level} risk
    </span>
  );
}

/** Status for verification / patch / check / analyzer states. */
export function StatusBadge({ status }: { status: string }) {
  const tone: Record<string, "success" | "warning" | "danger" | "neutral" | "info" | "accent"> = {
    ok: "success",
    passed: "success",
    verified: "success",
    completed: "success",
    applied: "accent",
    partially_verified: "warning",
    partial: "warning",
    skipped: "neutral",
    not_verified: "neutral",
    proposed: "info",
    discarded: "neutral",
    failed: "danger",
    error: "danger",
  };
  return <Badge tone={tone[status] ?? "neutral"}>{status.replace(/_/g, " ")}</Badge>;
}

export function InferredTag() {
  return (
    <Badge
      tone="warning"
      className="!px-1 !py-0 text-[10px]"
      title="Inferred from naming/heuristics, not statically resolved"
    >
      inferred
    </Badge>
  );
}

export function AIGeneratedTag({ provider, model }: { provider?: string | null; model?: string | null }) {
  const via = [provider, model].filter(Boolean).join("/");
  return (
    <Badge tone="accent" title="Non-deterministic content produced by an AI model">
      AI-generated{via ? ` · ${via}` : ""}
    </Badge>
  );
}
