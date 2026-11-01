"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ExternalLink, Search, Sparkles, Wrench } from "lucide-react";
import { useData } from "@/components/DataProvider";
import { AIGeneratedTag, Badge, SeverityBadge, StatusBadge } from "@/components/ui/Badge";
import { Button, Spinner } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/Card";
import { EmptyState, ErrorBanner, NoScanState } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api";
import { SEVERITIES, fileLoc, humanize } from "@/lib/format";
import type { AIExplanation, Finding } from "@/lib/types";

export default function FindingsPage() {
  return (
    <Suspense fallback={<Spinner label="Loading findings…" />}>
      <FindingsContent />
    </Suspense>
  );
}

function FindingsContent() {
  const { report, reportState, reportError, refreshReport } = useData();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [query, setQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState<string>(
    searchParams.get("severity") ?? "all"
  );
  const [moduleFilter, setModuleFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("id"));

  const [explaining, setExplaining] = useState(false);
  const [explainErr, setExplainErr] = useState<string | null>(null);
  const [localAi, setLocalAi] = useState<Record<string, AIExplanation>>({});

  const [proposing, setProposing] = useState(false);
  const [proposeErr, setProposeErr] = useState<string | null>(null);

  useEffect(() => {
    const sev = searchParams.get("severity");
    if (sev) setSeverityFilter(sev);
    const id = searchParams.get("id");
    if (id) setSelectedId(id);
  }, [searchParams]);

  const modules = useMemo(() => {
    if (!report) return [];
    return Array.from(new Set(report.findings.map((f) => f.module))).sort();
  }, [report]);

  const filtered = useMemo(() => {
    if (!report) return [];
    const q = query.trim().toLowerCase();
    return report.findings.filter((f) => {
      if (severityFilter !== "all" && f.severity !== severityFilter) return false;
      if (moduleFilter !== "all" && f.module !== moduleFilter) return false;
      if (statusFilter !== "all" && f.status !== statusFilter) return false;
      if (q) {
        const hay = `${f.id} ${f.title} ${f.rule} ${f.file ?? ""} ${f.evidence}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [report, query, severityFilter, moduleFilter, statusFilter]);

  if (reportState === "loading") return <Spinner />;
  if (reportState === "missing") {
    return (
      <>
        <PageHeader title="Findings" />
        <NoScanState />
      </>
    );
  }
  if (!report) return <ErrorBanner message={reportError ?? "Failed to load report"} />;

  const selected: Finding | null =
    filtered.find((f) => f.id === selectedId || f.fingerprint === selectedId) ??
    filtered[0] ??
    null;

  const currentAi: AIExplanation | undefined = selected
    ? localAi[selected.fingerprint] ?? report.ai?.[selected.fingerprint]
    : undefined;

  const handleExplain = async (f: Finding) => {
    setExplaining(true);
    setExplainErr(null);
    try {
      const res = await api.explain(f.id);
      setLocalAi((prev) => ({ ...prev, [f.fingerprint]: res.explanation }));
      await refreshReport();
    } catch (err) {
      setExplainErr(errorMessage(err));
    } finally {
      setExplaining(false);
    }
  };

  const handleProposeFix = async (f: Finding) => {
    setProposing(true);
    setProposeErr(null);
    try {
      const res = await api.fix(f.id, "auto");
      router.push(`/fixes/?patch=${encodeURIComponent(res.patch.patch_id)}`);
    } catch (err) {
      setProposeErr(errorMessage(err));
    } finally {
      setProposeErr((e) => e);
      setProposing(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Findings"
        description={`${filtered.length} of ${report.findings.length} findings shown`}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by ID, file, rule, or evidence…"
            className="w-full rounded-md border border-zinc-800 bg-zinc-900 py-1.5 pl-8 pr-3 text-sm text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none"
          />
        </div>
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          aria-label="Filter by severity"
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200"
        >
          <option value="all">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s.toUpperCase()}
            </option>
          ))}
        </select>
        <select
          value={moduleFilter}
          onChange={(e) => setModuleFilter(e.target.value)}
          aria-label="Filter by module"
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200"
        >
          <option value="all">All modules</option>
          {modules.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by lifecycle status"
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200"
        >
          <option value="all">All lifecycle states</option>
          <option value="new">New</option>
          <option value="existing">Existing</option>
          <option value="reintroduced">Reintroduced</option>
        </select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No matching findings">
          Adjust your search or severity/module filters.
        </EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <Card title="Detected issues" bodyClassName="divide-y divide-zinc-800/70">
              {filtered.map((f) => {
                const isSelected = selected?.id === f.id;
                return (
                  <button
                    key={f.fingerprint || f.id}
                    type="button"
                    onClick={() => {
                      setSelectedId(f.id);
                      setExplainErr(null);
                      setProposeErr(null);
                    }}
                    className={`flex w-full items-start gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                      isSelected ? "bg-violet-500/10" : "hover:bg-zinc-800/40"
                    }`}
                  >
                    <span className="w-12 shrink-0 pt-0.5 font-mono text-xs text-zinc-400">
                      {f.id}
                    </span>
                    <div className="pt-0.5">
                      <SeverityBadge severity={f.severity} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-zinc-100">{f.title}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                        <span className="font-mono">{fileLoc(f.file, f.line)}</span>
                        <span>·</span>
                        <span>{f.module}</span>
                        <span>·</span>
                        <span className="font-mono">{f.rule}</span>
                        {f.fixable && (
                          <Badge tone="info" className="!py-0 text-[10px]">
                            auto-fixable
                          </Badge>
                        )}
                      </div>
                    </div>
                    <StatusBadge status={f.status} />
                  </button>
                );
              })}
            </Card>
          </div>

          <div className="lg:col-span-5">
            {selected && (
              <Card
                title={`${selected.id} · ${selected.rule}`}
                actions={<StatusBadge status={selected.verification} />}
                bodyClassName="space-y-4 p-4"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={selected.severity} />
                    <Badge tone="neutral">{selected.module}</Badge>
                    <Badge tone="neutral">confidence: {selected.confidence}</Badge>
                    <Badge tone="neutral">{humanize(selected.status)}</Badge>
                  </div>
                  <h3 className="mt-2 text-base font-semibold text-zinc-100">{selected.title}</h3>
                  <div className="mt-1 font-mono text-xs text-zinc-400">
                    {fileLoc(selected.file, selected.line)}
                    {selected.symbol ? ` · symbol: ${selected.symbol}` : ""}
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Deterministic Evidence
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-zinc-800 bg-zinc-950 p-3 font-mono text-xs text-zinc-200">
                    {selected.evidence}
                  </pre>
                </div>

                {selected.suggestion && (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      Recommended Action
                    </div>
                    <p className="text-sm text-zinc-300">{selected.suggestion}</p>
                  </div>
                )}

                {selected.references.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      References
                    </div>
                    <ul className="space-y-1 text-xs">
                      {selected.references.map((r) => (
                        <li key={r}>
                          <a
                            href={r}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-violet-400 hover:underline"
                          >
                            {r} <ExternalLink className="h-3 w-3" />
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-3">
                  <Button
                    variant="primary"
                    loading={proposing}
                    icon={<Wrench className="h-3.5 w-3.5" />}
                    onClick={() => void handleProposeFix(selected)}
                  >
                    Propose Fix Patch
                  </Button>
                  <Button
                    variant="secondary"
                    loading={explaining}
                    icon={<Sparkles className="h-3.5 w-3.5" />}
                    onClick={() => void handleExplain(selected)}
                  >
                    {currentAi ? "Refresh AI Explanation" : "Explain with AI"}
                  </Button>
                </div>

                {proposeErr && <ErrorBanner message={proposeErr} />}
                {explainErr && <ErrorBanner message={explainErr} />}

                {currentAi && (
                  <div className="space-y-2.5 rounded-md border border-violet-500/30 bg-violet-950/15 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <AIGeneratedTag provider={currentAi.provider} model={currentAi.model} />
                      <span className="text-[11px] text-zinc-500">Non-deterministic</span>
                    </div>
                    <div className="text-sm font-medium text-zinc-100">{currentAi.summary}</div>
                    <div className="text-xs text-zinc-300">
                      <span className="font-semibold text-zinc-400">Root cause: </span>
                      {currentAi.root_cause}
                    </div>
                    <div className="text-xs text-zinc-300">
                      <span className="font-semibold text-zinc-400">Impact: </span>
                      {currentAi.impact}
                    </div>
                    <div className="text-xs text-zinc-300">
                      <span className="font-semibold text-zinc-400">Recommendation: </span>
                      {currentAi.recommendation}
                    </div>
                    {currentAi.suggested_tests.length > 0 && (
                      <div className="text-xs text-zinc-300">
                        <div className="font-semibold text-zinc-400">Suggested tests:</div>
                        <ul className="mt-1 list-disc pl-4 font-mono text-[11px]">
                          {currentAi.suggested_tests.map((t) => (
                            <li key={t}>{t}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {currentAi.caveats && (
                      <div className="text-[11px] text-zinc-500">{currentAi.caveats}</div>
                    )}
                  </div>
                )}
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}
