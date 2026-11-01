"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { Card, Stat } from "@/components/ui/Card";
import { SeverityBadge, StatusBadge } from "@/components/ui/Badge";
import {
  SEVERITIES,
  SEVERITY_HEX,
  fileLoc,
  formatDate,
  formatDuration,
  healthColor,
  relativeTime,
  severityRank,
  shortSha,
} from "@/lib/format";
import type { AnalyzerRun, Finding, MemoryDelta, Report } from "@/lib/types";

export function HealthCard({ report }: { report: Report }) {
  const { health_score, health_formula, total, files_scanned } = report.summary;
  return (
    <Card title="Health score">
      <div className="flex items-end gap-3">
        <div className={`text-5xl font-semibold tabular-nums ${healthColor(health_score)}`}>
          {health_score}
        </div>
        <div className="pb-1.5 text-sm text-zinc-500">/ 100</div>
        <div className="group relative mb-2 ml-auto">
          <Info className="h-4 w-4 cursor-help text-zinc-500" />
          <div className="pointer-events-none absolute right-0 top-6 z-20 hidden w-72 rounded-md border border-zinc-700 bg-zinc-900 p-3 text-xs text-zinc-300 shadow-xl group-hover:block">
            <div className="mb-1 font-medium text-zinc-100">How this is computed</div>
            <div className="font-mono text-[11px] leading-relaxed text-zinc-400">
              {health_formula || "Formula not reported by the engine."}
            </div>
            <div className="mt-2 text-zinc-500">
              Deterministic — derived only from analyzer findings.
            </div>
          </div>
        </div>
      </div>
      <div className="mt-3 text-xs text-zinc-500">
        {total} finding{total === 1 ? "" : "s"} across {files_scanned} scanned file
        {files_scanned === 1 ? "" : "s"}
      </div>
    </Card>
  );
}

export function SeverityTotals({ bySeverity }: { bySeverity: Record<string, number> }) {
  return (
    <Card title="Findings by severity">
      <div className="grid grid-cols-5 gap-2">
        {SEVERITIES.map((s) => (
          <Link
            key={s}
            href={`/findings/?severity=${s}`}
            className="rounded-md border border-zinc-800 bg-zinc-950/50 px-2 py-2 hover:border-zinc-700"
          >
            <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-zinc-500">
              <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_HEX[s] }} />
              {s}
            </div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-zinc-100">
              {bySeverity[s] ?? 0}
            </div>
          </Link>
        ))}
      </div>
    </Card>
  );
}

export function ScanInfo({ report }: { report: Report }) {
  const r = report.repository;
  const rows: [string, ReactNode][] = [
    ["Finished", <span key="f" title={formatDate(report.finished_at)}>{formatDate(report.finished_at)} · {relativeTime(report.finished_at)}</span>],
    ["Status", <StatusBadge key="s" status={report.status} />],
    ["Branch", r.branch ?? "—"],
    ["Commit", <span key="c" className="font-mono">{shortSha(r.commit)}{r.dirty ? " (dirty)" : ""}</span>],
    ["Scan ID", <span key="i" className="font-mono">{report.scan_id}</span>],
    ["Engine", `devpilot ${report.version}`],
  ];
  return (
    <Card title="Latest scan">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-zinc-500">{k}</dt>
            <dd className="min-w-0 truncate text-zinc-200">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export function AnalyzerList({ analyzers }: { analyzers: AnalyzerRun[] }) {
  return (
    <Card title="Analyzers" bodyClassName="divide-y divide-zinc-800/70">
      {analyzers.length === 0 && <div className="p-4 text-sm text-zinc-500">No analyzers ran.</div>}
      {analyzers.map((a) => (
        <div key={a.name} className="flex items-start gap-3 px-4 py-2 text-sm">
          <div className="w-32 shrink-0 truncate font-mono text-xs text-zinc-300 pt-0.5">{a.name}</div>
          <StatusBadge status={a.status} />
          <div className="min-w-0 flex-1 text-xs text-zinc-500">
            {a.message && <div className="break-words">{a.message}</div>}
          </div>
          <div className="shrink-0 text-right text-xs tabular-nums text-zinc-500">
            {a.findings} · {formatDuration(a.duration_ms)}
          </div>
        </div>
      ))}
    </Card>
  );
}

export function MemoryDeltaCard({ memory }: { memory: MemoryDelta | null }) {
  return (
    <Card title="Since previous scan">
      {!memory || !memory.previous_scan_id ? (
        <div className="text-sm text-zinc-500">
          This is the first recorded scan — there is nothing to compare against yet.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="New" value={<span className="text-orange-400">{memory.new}</span>} />
            <Stat label="Resolved" value={<span className="text-emerald-400">{memory.resolved}</span>} />
            <Stat label="Reintroduced" value={<span className="text-red-400">{memory.reintroduced}</span>} />
          </div>
          <div className="mt-2 text-xs text-zinc-500">
            {memory.existing} unchanged · {memory.severity_changed} severity changes · vs{" "}
            <span className="font-mono">{memory.previous_scan_id}</span>
          </div>
        </>
      )}
    </Card>
  );
}

export function TopFindings({ findings, limit = 8 }: { findings: Finding[]; limit?: number }) {
  const top = [...findings]
    .sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
    .filter((f) => f.severity !== "info")
    .slice(0, limit);
  return (
    <Card
      title="Top actionable findings"
      actions={
        <Link href="/findings/" className="text-xs text-violet-400 hover:text-violet-300">
          View all →
        </Link>
      }
      bodyClassName="divide-y divide-zinc-800/70"
    >
      {top.length === 0 && (
        <div className="p-4 text-sm text-zinc-500">No actionable findings. Nice.</div>
      )}
      {top.map((f) => (
        <Link
          key={f.fingerprint || f.id}
          href={`/findings/?id=${encodeURIComponent(f.id)}`}
          className="flex items-center gap-3 px-4 py-2 text-sm hover:bg-zinc-800/40"
        >
          <span className="w-14 shrink-0 font-mono text-xs text-zinc-500">{f.id}</span>
          <SeverityBadge severity={f.severity} />
          <span className="min-w-0 flex-1 truncate text-zinc-200">{f.title}</span>
          <span className="hidden max-w-[40%] truncate font-mono text-xs text-zinc-500 sm:block">
            {fileLoc(f.file, f.line)}
          </span>
        </Link>
      ))}
    </Card>
  );
}
