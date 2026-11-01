"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Play,
  RefreshCw,
  Sparkles,
  Terminal,
  Wrench,
  Zap,
} from "lucide-react";
import { useData } from "@/components/DataProvider";
import { api, errorMessage } from "@/lib/api";
import { CopyButton } from "@/components/ui/States";
import type { Report } from "@/lib/types";

export function QuickActionsBar({ report }: { report: Report }) {
  const { refreshAll } = useData();
  const [scanning, setScanning] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleScan = async () => {
    setScanning(true);
    setError(null);
    try {
      await api.scan({ offline });
      await refreshAll();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setScanning(false);
    }
  };

  const total = report.summary.total;
  const critical = report.summary.by_severity["critical"] ?? 0;
  const high = report.summary.by_severity["high"] ?? 0;
  const fixable = report.findings.filter((f) => f.fixable).length;

  return (
    <div className="rounded-xl border border-zinc-800 bg-gradient-to-r from-zinc-900/90 via-zinc-900/40 to-zinc-900/90 p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-violet-600/20 text-violet-400">
            <Zap className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
              Developer Quick Actions
            </div>
            <div className="text-xs text-zinc-500">
              Instant scan execution, fix triage, and developer workflow tools
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={offline}
              onChange={(e) => setOffline(e.target.checked)}
              disabled={scanning}
              className="rounded border-zinc-700 bg-zinc-950 text-violet-600 focus:ring-0 focus:ring-offset-0"
            />
            <span>Offline</span>
          </label>

          <button
            type="button"
            onClick={handleScan}
            disabled={scanning}
            className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-violet-500 transition-colors disabled:opacity-50"
          >
            {scanning ? (
              <>
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                Scanning…
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5 fill-current" />
                Run Scan Now
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-rose-900/50 bg-rose-950/30 px-3 py-1.5 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Quick Filter Pills */}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-zinc-800/80 pt-3">
        <Link
          href="/findings/"
          className="inline-flex items-center gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 px-2.5 py-1 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
        >
          <span>All Findings</span>
          <span className="rounded bg-zinc-800 px-1.5 py-0.2 text-[10px] font-mono text-zinc-400">
            {total}
          </span>
        </Link>

        {critical > 0 && (
          <Link
            href="/findings/?severity=critical"
            className="inline-flex items-center gap-1.5 rounded-md border border-rose-900/50 bg-rose-950/30 px-2.5 py-1 text-xs text-rose-300 hover:border-rose-700 transition-colors"
          >
            <AlertCircle className="h-3 w-3 text-rose-400" />
            <span>Critical Issues</span>
            <span className="rounded bg-rose-900/60 px-1.5 py-0.2 text-[10px] font-mono font-bold text-rose-200">
              {critical}
            </span>
          </Link>
        )}

        {high > 0 && (
          <Link
            href="/findings/?severity=high"
            className="inline-flex items-center gap-1.5 rounded-md border border-amber-900/50 bg-amber-950/30 px-2.5 py-1 text-xs text-amber-300 hover:border-amber-700 transition-colors"
          >
            <span>High Severity</span>
            <span className="rounded bg-amber-900/60 px-1.5 py-0.2 text-[10px] font-mono font-semibold text-amber-200">
              {high}
            </span>
          </Link>
        )}

        {fixable > 0 && (
          <Link
            href="/findings/"
            className="inline-flex items-center gap-1.5 rounded-md border border-emerald-900/50 bg-emerald-950/30 px-2.5 py-1 text-xs text-emerald-300 hover:border-emerald-700 transition-colors"
          >
            <Wrench className="h-3 w-3 text-emerald-400" />
            <span>Auto-Fixable Patches</span>
            <span className="rounded bg-emerald-900/60 px-1.5 py-0.2 text-[10px] font-mono font-bold text-emerald-200">
              {fixable}
            </span>
          </Link>
        )}

        <Link
          href="/plan/"
          className="inline-flex items-center gap-1.5 rounded-md border border-violet-900/40 bg-violet-950/20 px-2.5 py-1 text-xs text-violet-300 hover:border-violet-700 transition-colors"
        >
          <Sparkles className="h-3 w-3 text-violet-400" />
          <span>AI Roadmap</span>
          <ChevronRight className="h-3 w-3 text-zinc-500" />
        </Link>
      </div>
    </div>
  );
}
