"use client";

import { useData } from "@/components/DataProvider";
import { Card, PageHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Button";
import { ErrorBanner, NoScanState } from "@/components/ui/States";
import { HealthTrendChart } from "@/components/charts/HistoryCharts";
import {
  AnalyzerList,
  HealthCard,
  MemoryDeltaCard,
  ScanInfo,
  SeverityTotals,
  TopFindings,
} from "@/components/overview/OverviewCards";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function OverviewPage() {
  const { report, reportState, reportError, version } = useData();
  const history = useApi(api.history, version);

  if (reportState === "loading") return <Spinner />;
  if (reportState === "missing") {
    return (
      <>
        <PageHeader title="Overview" />
        <NoScanState />
      </>
    );
  }
  if (!report) return <ErrorBanner message={reportError ?? "Failed to load report"} />;

  const scans = history.data?.scans ?? [];

  return (
    <>
      <PageHeader
        title="Overview"
        description={`${report.repository.name} · ${report.repository.path}`}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <HealthCard report={report} />
        <div className="lg:col-span-2">
          <SeverityTotals bySeverity={report.summary.by_severity} />
        </div>
        <ScanInfo report={report} />
        <MemoryDeltaCard memory={report.memory} />
        <Card title="Health trend">
          {scans.length >= 2 ? (
            <HealthTrendChart scans={scans} height={150} />
          ) : (
            <div className="text-sm text-zinc-500">
              {history.error
                ? `History unavailable: ${history.error}`
                : "A trend appears after at least two scans."}
            </div>
          )}
        </Card>
        <div className="lg:col-span-2">
          <TopFindings findings={report.findings} />
        </div>
        <AnalyzerList analyzers={report.analyzers} />
      </div>
      {report.limitations.length > 0 && (
        <Card title="Limitations" className="mt-4">
          <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-400">
            {report.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
