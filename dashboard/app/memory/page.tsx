"use client";

import Link from "next/link";
import { useData } from "@/components/DataProvider";
import {
  HealthTrendChart,
  NewResolvedChart,
  SeverityOverTimeChart,
} from "@/components/charts/HistoryCharts";
import { StatusBadge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/Card";
import { ErrorBanner, NoScanState } from "@/components/ui/States";
import { api } from "@/lib/api";
import { formatDate, healthColor, shortSha } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function MemoryPage() {
  const { version } = useData();
  const historyState = useApi(api.history, version);

  if (historyState.loading) return <Spinner />;
  if (historyState.error) return <ErrorBanner message={historyState.error} />;

  const scans = historyState.data?.scans ?? [];
  const verifications = historyState.data?.verifications ?? [];

  if (scans.length === 0) {
    return (
      <>
        <PageHeader title="Repository Memory" />
        <NoScanState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Repository Memory"
        description="SQLite-backed scan history, finding lifecycle tracking (new / existing / resolved / reintroduced), and verification audit log"
      />

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <Card title="Health Score Over Time">
          <HealthTrendChart scans={scans} height={200} />
        </Card>
        <Card title="New vs Resolved Findings">
          <NewResolvedChart scans={scans} height={200} />
        </Card>
        <Card title="Severity Breakdown Over Time">
          <SeverityOverTimeChart scans={scans} height={200} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <Card title={`Recorded Scans (${scans.length})`} bodyClassName="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-800 text-[11px] uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5">Scan ID</th>
                  <th className="px-3 py-2.5">Finished</th>
                  <th className="px-3 py-2.5">Git</th>
                  <th className="px-3 py-2.5 text-right">Health</th>
                  <th className="px-3 py-2.5 text-right">Total</th>
                  <th className="px-3 py-2.5 text-right">+New</th>
                  <th className="px-3 py-2.5 text-right">Resolved</th>
                  <th className="px-3 py-2.5 text-right">Reintro</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/70">
                {scans.map((s) => (
                  <tr key={s.scan_id} className="hover:bg-zinc-800/30">
                    <td className="px-4 py-2 font-mono text-zinc-200">{s.scan_id}</td>
                    <td className="px-3 py-2 text-zinc-400">{formatDate(s.finished_at)}</td>
                    <td className="px-3 py-2 font-mono text-zinc-400">
                      {s.branch ? `${s.branch}@` : ""}
                      {shortSha(s.commit)}
                    </td>
                    <td className={`px-3 py-2 text-right font-semibold ${healthColor(s.health_score)}`}>
                      {s.health_score}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-zinc-200">{s.total}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-orange-400">+{s.new}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-emerald-400">
                      {s.resolved}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-red-400">
                      {s.reintroduced}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="lg:col-span-5">
          <Card
            title={`Verification Outcomes (${verifications.length})`}
            bodyClassName="divide-y divide-zinc-800/70"
          >
            {verifications.length === 0 ? (
              <div className="p-4 text-sm text-zinc-500">
                No patches have been verified yet. Propose and verify a patch in{" "}
                <Link href="/fixes/" className="text-violet-400 hover:underline">
                  Fix Review
                </Link>
                .
              </div>
            ) : (
              verifications.map((v) => (
                <Link
                  key={v.patch_id}
                  href={`/fixes/?patch=${encodeURIComponent(v.patch_id)}`}
                  className="block px-4 py-3 text-xs hover:bg-zinc-800/40"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-zinc-300">
                      {v.patch_id} · <span className="text-violet-400">{v.finding_id}</span>
                    </span>
                    <StatusBadge status={v.status} />
                  </div>
                  <div className="mt-1 font-medium text-zinc-100">{v.title}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
                    <span>{formatDate(v.created_at)}</span>
                    <span>·</span>
                    <span>
                      {v.checks.map((c) => `${c.name}:${c.status}`).join(", ")}
                    </span>
                  </div>
                </Link>
              ))
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
