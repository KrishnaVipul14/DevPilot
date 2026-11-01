"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, GitPullRequestArrow, ShieldCheck, Trash2 } from "lucide-react";
import { useData } from "@/components/DataProvider";
import { AIGeneratedTag, Badge, StatusBadge } from "@/components/ui/Badge";
import { Button, Spinner } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/Card";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { CommandLine, EmptyState, ErrorBanner } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api";
import { formatDate, formatDuration } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Patch } from "@/lib/types";

export default function FixesPage() {
  return (
    <Suspense fallback={<Spinner label="Loading patches…" />}>
      <FixesContent />
    </Suspense>
  );
}

function FixesContent() {
  const { version, refreshReport } = useData();
  const patchesState = useApi(api.patches, version);
  const searchParams = useSearchParams();

  const [selectedPatchId, setSelectedPatchId] = useState<string | null>(
    searchParams.get("patch")
  );
  const [actionLoading, setActionLoading] = useState<"verify" | "apply" | "discard" | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  useEffect(() => {
    const p = searchParams.get("patch");
    if (p) setSelectedPatchId(p);
  }, [searchParams]);

  if (patchesState.loading) return <Spinner />;
  if (patchesState.error) return <ErrorBanner message={patchesState.error} />;

  const patches = patchesState.data?.patches ?? [];
  const selected: Patch | null =
    patches.find((p) => p.patch_id === selectedPatchId) ?? patches[0] ?? null;

  const updatePatchInList = (updated: Patch) => {
    patchesState.setData({
      patches: patches.map((p) => (p.patch_id === updated.patch_id ? updated : p)),
    });
    setSelectedPatchId(updated.patch_id);
  };

  const handleAction = async (patch: Patch, action: "verify" | "apply" | "discard") => {
    if (action === "apply") {
      const ok = window.confirm(
        `Apply verified patch ${patch.patch_id} (${patch.files.join(", ")}) to your working tree?`
      );
      if (!ok) return;
    }
    setActionLoading(action);
    setActionErr(null);
    try {
      const res =
        action === "verify"
          ? await api.verifyPatch(patch.patch_id)
          : action === "apply"
          ? await api.applyPatch(patch.patch_id)
          : await api.discardPatch(patch.patch_id);
      updatePatchInList(res.patch);
      await refreshReport();
    } catch (err) {
      setActionErr(errorMessage(err));
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Safe Fix Review & Isolated Verification"
        description="Review proposed unified diffs, verify in an isolated Git worktree, and explicitly approve changes"
      />

      {patches.length === 0 ? (
        <EmptyState
          title="No proposed patches yet"
          icon={<GitPullRequestArrow className="h-7 w-7" />}
        >
          Select a finding on the <strong>Findings</strong> page and click{" "}
          <strong>Propose Fix Patch</strong>, or run <code>devpilot fix DP001</code> in your
          terminal.
        </EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="lg:col-span-4">
            <Card title={`Patches (${patches.length})`} bodyClassName="divide-y divide-zinc-800/70">
              {patches.map((p) => {
                const active = selected?.patch_id === p.patch_id;
                return (
                  <button
                    key={p.patch_id}
                    type="button"
                    onClick={() => {
                      setSelectedPatchId(p.patch_id);
                      setActionErr(null);
                    }}
                    className={`flex w-full items-start justify-between gap-2 px-4 py-3 text-left text-xs ${
                      active ? "bg-violet-500/10" : "hover:bg-zinc-800/40"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 font-mono text-zinc-300">
                        <span>{p.patch_id}</span>
                        <span>·</span>
                        <span className="text-violet-400">{p.finding_id}</span>
                      </div>
                      <div className="mt-1 truncate font-medium text-zinc-100">{p.title}</div>
                      <div className="mt-0.5 truncate font-mono text-[11px] text-zinc-500">
                        {p.files.join(", ")}
                      </div>
                    </div>
                    <StatusBadge status={p.status} />
                  </button>
                );
              })}
            </Card>
          </div>

          <div className="lg:col-span-8">
            {selected && (
              <Card
                title={`${selected.patch_id} · ${selected.finding_id}`}
                actions={<StatusBadge status={selected.status} />}
                bodyClassName="space-y-4 p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-base font-semibold text-zinc-100">{selected.title}</h3>
                    <p className="mt-0.5 text-sm text-zinc-400">{selected.summary}</p>
                    <div className="mt-1 text-xs text-zinc-500">
                      Created {formatDate(selected.created_at)} · Target:{" "}
                      <span className="font-mono text-zinc-300">{selected.files.join(", ")}</span>
                    </div>
                  </div>
                  {selected.engine === "ai" ? (
                    <AIGeneratedTag />
                  ) : (
                    <Badge tone="info">Deterministic fix (Ruff / manifest)</Badge>
                  )}
                </div>

                {/* Action Bar */}
                <div className="flex flex-wrap items-center gap-2 border-y border-zinc-800 py-3">
                  <Button
                    variant="primary"
                    loading={actionLoading === "verify"}
                    disabled={selected.status === "discarded" || selected.status === "applied"}
                    icon={<ShieldCheck className="h-3.5 w-3.5" />}
                    onClick={() => void handleAction(selected, "verify")}
                  >
                    Approve & Verify in Isolated Worktree
                  </Button>
                  <Button
                    variant="secondary"
                    loading={actionLoading === "apply"}
                    disabled={
                      selected.status !== "verified" && selected.status !== "partially_verified"
                    }
                    icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                    onClick={() => void handleAction(selected, "apply")}
                  >
                    Apply to Working Tree
                  </Button>
                  <Button
                    variant="danger"
                    loading={actionLoading === "discard"}
                    disabled={selected.status === "discarded" || selected.status === "applied"}
                    icon={<Trash2 className="h-3.5 w-3.5" />}
                    onClick={() => void handleAction(selected, "discard")}
                  >
                    Discard Patch
                  </Button>
                </div>

                {actionErr && <ErrorBanner message={actionErr} />}

                {/* Unified Diff Viewer */}
                <div>
                  <CodeBlock
                    code={selected.diff}
                    isDiff={true}
                    title={`Unified Diff · ${selected.files.join(", ")}`}
                    maxHeight="450px"
                  />
                </div>

                {/* Direct CLI Execution Snippet */}
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-3">
                  <div className="mb-1.5 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-zinc-400">
                    <span>Terminal Direct Verification</span>
                    <span className="font-mono text-[10px] text-zinc-500">Isolated Worktree</span>
                  </div>
                  <CommandLine
                    command={`devpilot fix ${selected.finding_id} --verify --apply -y`}
                  />
                </div>

                {/* Verification Results */}
                {selected.verification && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                        Isolated Verification Checks ({selected.verification.mode})
                      </div>
                      <StatusBadge status={selected.verification.status} />
                    </div>
                    <div className="divide-y divide-zinc-800 rounded-md border border-zinc-800 bg-zinc-950/60">
                      {selected.verification.checks.map((c) => (
                        <div key={c.name} className="space-y-1.5 p-3 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono font-semibold text-zinc-200">{c.name}</span>
                            <div className="flex items-center gap-2">
                              <span className="text-zinc-500">{formatDuration(c.duration_ms)}</span>
                              <StatusBadge status={c.status} />
                            </div>
                          </div>
                          {c.command && (
                            <div className="font-mono text-[11px] text-zinc-500">$ {c.command}</div>
                          )}
                          {c.detail && (
                            <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-zinc-900 p-2 font-mono text-[11px] text-zinc-300">
                              {c.detail}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
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
