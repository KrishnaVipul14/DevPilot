"use client";

import { useMemo, useState } from "react";
import { Bot, FlaskConical, GitCommit, Network, Search } from "lucide-react";
import { useData } from "@/components/DataProvider";
import { Badge, InferredTag, RiskBadge } from "@/components/ui/Badge";
import { Button, Spinner } from "@/components/ui/Button";
import { Card, PageHeader, Stat } from "@/components/ui/Card";
import { CommandLine, EmptyState, ErrorBanner, NoScanState } from "@/components/ui/States";
import { ArchitectAskModal } from "@/components/intelligence/ArchitectAskModal";
import { ArchitectureMermaidModal } from "@/components/intelligence/ArchitectureMermaidModal";
import { RouteExplorer } from "@/components/intelligence/RouteExplorer";
import { TestScaffoldModal } from "@/components/intelligence/TestScaffoldModal";
import { api, errorMessage } from "@/lib/api";
import { fileLoc } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { GraphNode, ImpactReport } from "@/lib/types";

export default function IntelligencePage() {
  const { reportState, version } = useData();
  const graphState = useApi(api.graph, version);
  const gitImpactState = useApi(() => api.impactGit("HEAD"), version);

  const [symbolInput, setSymbolInput] = useState("");
  const [symbolImpact, setSymbolImpact] = useState<ImpactReport | null>(null);
  const [symbolLoading, setSymbolLoading] = useState(false);
  const [symbolErr, setSymbolErr] = useState<string | null>(null);
  const [activeMode, setActiveMode] = useState<"git" | "symbol">("git");

  const [nodeFilter, setNodeFilter] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const [askModalOpen, setAskModalOpen] = useState(false);
  const [mermaidModalOpen, setMermaidModalOpen] = useState(false);
  const [testgenOpen, setTestgenOpen] = useState(false);
  const [testgenSymbol, setTestgenSymbol] = useState("");

  const graph = graphState.data;

  const nodesById = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const n of graph?.nodes ?? []) map.set(n.id, n);
    return map;
  }, [graph]);

  const filteredNodes = useMemo(() => {
    if (!graph) return [];
    const q = nodeFilter.trim().toLowerCase();
    return graph.nodes
      .filter((n) => n.kind === "function" || n.kind === "class" || n.kind === "module")
      .filter((n) => {
        if (!q) return true;
        return `${n.id} ${n.name} ${n.file ?? ""}`.toLowerCase().includes(q);
      })
      .slice(0, 60);
  }, [graph, nodeFilter]);

  const selectedNode =
    (selectedNodeId ? nodesById.get(selectedNodeId) : undefined) ?? filteredNodes[0] ?? null;

  const selectedRelations = useMemo(() => {
    if (!graph || !selectedNode) {
      return { incoming: [], outgoing: [] };
    }
    const incoming = graph.edges.filter((e) => e.target === selectedNode.id);
    const outgoing = graph.edges.filter((e) => e.source === selectedNode.id);
    return { incoming, outgoing };
  }, [graph, selectedNode]);

  if (reportState === "loading" || graphState.loading) return <Spinner />;
  if (reportState === "missing" || graphState.notFound) {
    return (
      <>
        <PageHeader title="Code Intelligence & Change Impact" />
        <NoScanState />
      </>
    );
  }
  if (!graph) {
    return <ErrorBanner message={graphState.error ?? "Failed to load repository graph"} />;
  }

  const runSymbolImpact = async (sym: string) => {
    const clean = sym.trim();
    if (!clean) return;
    setSymbolLoading(true);
    setSymbolErr(null);
    setActiveMode("symbol");
    try {
      const res = await api.impactSymbol(clean);
      setSymbolImpact(res);
    } catch (err) {
      setSymbolErr(errorMessage(err));
    } finally {
      setSymbolLoading(false);
    }
  };

  const shownImpact: ImpactReport | null =
    activeMode === "symbol" ? symbolImpact : gitImpactState.data;

  return (
    <>
      <PageHeader
        title="Code Intelligence & Change Impact"
        description="Static AST dependency graph, call relationships, route handlers, and Git blast-radius analysis"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              icon={<Bot className="h-3.5 w-3.5 text-violet-400" />}
              onClick={() => setAskModalOpen(true)}
            >
              Ask Codebase
            </Button>
            <Button
              variant="secondary"
              icon={<Network className="h-3.5 w-3.5 text-emerald-400" />}
              onClick={() => setMermaidModalOpen(true)}
            >
              Export Architecture (Mermaid)
            </Button>
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-6">
        <Stat label="Modules" value={graph.summary.modules} />
        <Stat label="Functions" value={graph.summary.functions} />
        <Stat label="Classes" value={graph.summary.classes} />
        <Stat label="API Routes" value={graph.summary.routes} />
        <Stat label="Tests" value={graph.summary.tests} />
        <Stat label="Graph Edges" value={graph.summary.edges} />
      </div>

      {/* Change Impact Analysis Section */}
      <Card
        title="Change Impact & Blast Radius Analyzer"
        className="mb-5"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant={activeMode === "git" ? "primary" : "secondary"}
              icon={<GitCommit className="h-3.5 w-3.5" />}
              onClick={() => {
                setActiveMode("git");
                void gitImpactState.reload();
              }}
            >
              Analyze Git Diff (HEAD)
            </Button>
          </div>
        }
        bodyClassName="space-y-4 p-4"
      >
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSymbolImpact(symbolInput);
            }}
            placeholder="Inspect symbol impact (e.g. validate_token, create_invoice)…"
            className="min-w-[260px] flex-1 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none"
          />
          <Button
            variant="secondary"
            loading={symbolLoading}
            icon={<Network className="h-3.5 w-3.5" />}
            onClick={() => void runSymbolImpact(symbolInput)}
          >
            Simulate Symbol Change
          </Button>
        </div>

        {symbolErr && <ErrorBanner message={symbolErr} />}

        {shownImpact ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
              <div>
                <div className="text-xs text-zinc-400">
                  Mode:{" "}
                  <span className="font-mono text-zinc-200">
                    {shownImpact.mode === "git"
                      ? `git diff (${shownImpact.base ?? "HEAD"})`
                      : "hypothetical symbol change"}
                  </span>{" "}
                  · {shownImpact.changed_files.length} file(s) ·{" "}
                  {shownImpact.changed_symbols.length} symbol(s)
                </div>
                <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-zinc-300">
                  {shownImpact.overall_risk.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
              <RiskBadge level={shownImpact.overall_risk.level} />
            </div>

            {shownImpact.impacts.length > 0 && (
              <div className="grid gap-3 md:grid-cols-2">
                {shownImpact.impacts.map((imp) => (
                  <div
                    key={imp.symbol}
                    className="space-y-2 rounded-md border border-zinc-800 bg-zinc-950/40 p-3 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono font-semibold text-zinc-100">{imp.symbol}</span>
                      <RiskBadge level={imp.risk.level} />
                    </div>
                    <div>
                      <span className="text-zinc-500">Dependent functions ({imp.callers.length}): </span>
                      {imp.callers.length > 0 ? (
                        <span className="font-mono text-zinc-200">{imp.callers.join(", ")}</span>
                      ) : (
                        <span className="text-zinc-500">None</span>
                      )}
                    </div>
                    <div>
                      <span className="text-zinc-500">
                        Dependent modules ({imp.dependent_modules.length}):{" "}
                      </span>
                      {imp.dependent_modules.length > 0 ? (
                        <span className="font-mono text-zinc-200">
                          {imp.dependent_modules.join(", ")}
                        </span>
                      ) : (
                        <span className="text-zinc-500">None</span>
                      )}
                    </div>
                    <div>
                      <span className="text-zinc-500">API Endpoints ({imp.routes.length}): </span>
                      {imp.routes.length > 0 ? (
                        <span className="font-mono text-emerald-400">
                          {imp.routes.map((r) => `${r.method} ${r.path}`).join(", ")}
                        </span>
                      ) : (
                        <span className="text-zinc-500">None</span>
                      )}
                    </div>
                    <div>
                      <span className="text-zinc-500">Relevant tests ({imp.tests.length}): </span>
                      {imp.tests.length > 0 ? (
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {imp.tests.map((t) => (
                            <span
                              key={t.id}
                              className="inline-flex items-center gap-1 rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 font-mono text-[11px] text-zinc-200"
                            >
                              {t.nodeid}
                              {t.certainty === "inferred" && <InferredTag />}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-amber-400">No tests linked</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {shownImpact.suggested_commands.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                  Suggested Verification Commands
                </div>
                {shownImpact.suggested_commands.map((cmd) => (
                  <CommandLine key={cmd} command={cmd} />
                ))}
              </div>
            )}
          </div>
        ) : (
          <EmptyState title="No impact report selected">
            Analyze current Git changes or enter a function name above.
          </EmptyState>
        )}
      </Card>

      {/* Multi-Framework API Route Explorer */}
      <div className="mb-5">
        <RouteExplorer nodes={graph.nodes} />
      </div>

      {/* Interactive Repository Graph Explorer */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-6">
          <Card title="Repository Symbols & Modules" bodyClassName="p-3">
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
              <input
                type="text"
                value={nodeFilter}
                onChange={(e) => setNodeFilter(e.target.value)}
                placeholder="Search modules, classes, or functions…"
                className="w-full rounded-md border border-zinc-800 bg-zinc-950 py-1.5 pl-8 pr-3 text-xs text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none"
              />
            </div>
            <div className="max-h-[420px] divide-y divide-zinc-800/70 overflow-y-auto">
              {filteredNodes.map((n) => {
                const active = selectedNode?.id === n.id;
                return (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => setSelectedNodeId(n.id)}
                    className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs ${
                      active ? "bg-violet-500/10 text-zinc-100" : "hover:bg-zinc-800/40"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-mono font-medium text-zinc-200">{n.id}</div>
                      <div className="truncate font-mono text-[11px] text-zinc-500">
                        {fileLoc(n.file, n.line)}
                      </div>
                    </div>
                    <Badge tone={n.kind === "module" ? "info" : n.kind === "class" ? "accent" : "neutral"}>
                      {n.kind}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </Card>
        </div>

        <div className="lg:col-span-6">
          {selectedNode ? (
            <Card
              title={`Relationships · ${selectedNode.id}`}
              actions={
                selectedNode.kind !== "module" && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="secondary"
                      icon={<FlaskConical className="h-3.5 w-3.5 text-emerald-400" />}
                      onClick={() => {
                        setTestgenSymbol(selectedNode.name);
                        setTestgenOpen(true);
                      }}
                    >
                      Generate Test
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setSymbolInput(selectedNode.name);
                        void runSymbolImpact(selectedNode.id);
                      }}
                    >
                      Analyze Impact
                    </Button>
                  </div>
                )
              }
              bodyClassName="space-y-4 p-4 text-xs"
            >
              <div className="flex flex-wrap items-center gap-2 text-zinc-400">
                <Badge tone="neutral">{selectedNode.kind}</Badge>
                <span className="font-mono">{fileLoc(selectedNode.file, selectedNode.line)}</span>
              </div>

              <div>
                <div className="mb-1.5 font-semibold uppercase tracking-wide text-zinc-400">
                  Incoming Edges (Callers / Importers / Routes) ({selectedRelations.incoming.length})
                </div>
                {selectedRelations.incoming.length === 0 ? (
                  <div className="text-zinc-500">No incoming edges in static graph.</div>
                ) : (
                  <ul className="space-y-1">
                    {selectedRelations.incoming.map((e, i) => (
                      <li
                        key={`${e.source}-${e.kind}-${i}`}
                        className="flex items-center justify-between rounded border border-zinc-800/80 bg-zinc-950/50 px-2.5 py-1.5"
                      >
                        <button
                          type="button"
                          onClick={() => setSelectedNodeId(e.source)}
                          className="truncate font-mono text-zinc-200 hover:text-violet-400"
                        >
                          {e.source}
                        </button>
                        <div className="flex items-center gap-1.5">
                          <Badge tone="neutral">{e.kind}</Badge>
                          {e.certainty === "inferred" && <InferredTag />}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <div className="mb-1.5 font-semibold uppercase tracking-wide text-zinc-400">
                  Outgoing Edges (Calls / Imports / Defines) ({selectedRelations.outgoing.length})
                </div>
                {selectedRelations.outgoing.length === 0 ? (
                  <div className="text-zinc-500">No outgoing edges in static graph.</div>
                ) : (
                  <ul className="space-y-1">
                    {selectedRelations.outgoing.map((e, i) => (
                      <li
                        key={`${e.target}-${e.kind}-${i}`}
                        className="flex items-center justify-between rounded border border-zinc-800/80 bg-zinc-950/50 px-2.5 py-1.5"
                      >
                        <button
                          type="button"
                          onClick={() => setSelectedNodeId(e.target)}
                          className="truncate font-mono text-zinc-200 hover:text-violet-400"
                        >
                          {e.target}
                        </button>
                        <div className="flex items-center gap-1.5">
                          <Badge tone="neutral">{e.kind}</Badge>
                          {e.certainty === "inferred" && <InferredTag />}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          ) : (
            <EmptyState title="Select a symbol to inspect its relationships" />
          )}
        </div>
      </div>

      <ArchitectAskModal open={askModalOpen} onClose={() => setAskModalOpen(false)} />
      <ArchitectureMermaidModal
        open={mermaidModalOpen}
        onClose={() => setMermaidModalOpen(false)}
      />
      <TestScaffoldModal
        open={testgenOpen}
        onClose={() => setTestgenOpen(false)}
        defaultSymbol={testgenSymbol}
      />
    </>
  );
}
