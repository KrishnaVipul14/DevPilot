"use client";

import { useState } from "react";
import Link from "next/link";
import { ListChecks, Sparkles } from "lucide-react";
import { useData } from "@/components/DataProvider";
import { AIGeneratedTag, Badge } from "@/components/ui/Badge";
import { Button, Spinner } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/Card";
import { CommandLine, EmptyState, ErrorBanner, NoScanState } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function PlanPage() {
  const { reportState, version } = useData();
  const planState = useApi(api.plan, version);
  const [generating, setGenerating] = useState(false);
  const [genErr, setGenErr] = useState<string | null>(null);

  if (reportState === "loading" || planState.loading) return <Spinner />;
  if (reportState === "missing") {
    return (
      <>
        <PageHeader title="AI Action Plan" />
        <NoScanState />
      </>
    );
  }

  const handleGenerate = async () => {
    setGenerating(true);
    setGenErr(null);
    try {
      const res = await api.generatePlan();
      planState.setData(res);
    } catch (err) {
      setGenErr(errorMessage(err));
    } finally {
      setGenerating(false);
    }
  };

  const plan = planState.data?.plan ?? null;

  return (
    <>
      <PageHeader
        title="AI Action Plan"
        description="Prioritized engineering improvement roadmap generated from scan findings"
        actions={
          <Button
            variant="primary"
            loading={generating}
            icon={<Sparkles className="h-3.5 w-3.5" />}
            onClick={() => void handleGenerate()}
          >
            {plan ? "Regenerate Plan" : "Generate Action Plan"}
          </Button>
        }
      />

      {genErr && <ErrorBanner message={genErr} />}
      {planState.error && <ErrorBanner message={planState.error} />}

      {!plan ? (
        <EmptyState
          title="No improvement plan generated yet"
          icon={<ListChecks className="h-7 w-7" />}
        >
          Click <strong>Generate Action Plan</strong> above (or run <code>devpilot plan</code>) to
          build a prioritized roadmap. Works both with Groq AI and offline via deterministic
          triage.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <Card
            title="Plan Summary"
            actions={
              plan.source === "ai" ? (
                <AIGeneratedTag provider={plan.provider} model={plan.model} />
              ) : (
                <Badge tone="info">Deterministic prioritization · Offline / AI fallback</Badge>
              )
            }
          >
            <div className="text-sm text-zinc-200">{plan.summary}</div>
            <div className="mt-1 text-xs text-zinc-500">
              Generated {formatDate(plan.created_at)} · Scan ID{" "}
              <span className="font-mono">{plan.scan_id}</span>
            </div>
          </Card>

          <div className="space-y-3">
            {plan.tasks.map((task) => (
              <Card
                key={`${task.priority}-${task.title}`}
                title={`Priority #${task.priority} · ${task.title}`}
                actions={<Badge tone="neutral">effort: {task.effort}</Badge>}
                bodyClassName="space-y-3 p-4 text-sm"
              >
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Why It Matters
                  </div>
                  <p className="mt-0.5 text-zinc-300">{task.why}</p>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Suggested Resolution
                  </div>
                  <p className="mt-0.5 text-zinc-300">{task.resolution}</p>
                </div>
                {task.finding_ids.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-zinc-500">Linked findings:</span>
                    {task.finding_ids.map((id) => (
                      <Link
                        key={id}
                        href={`/findings/?id=${encodeURIComponent(id)}`}
                        className="rounded border border-zinc-800 bg-zinc-950 px-2 py-0.5 font-mono text-xs text-violet-400 hover:border-violet-500"
                      >
                        {id}
                      </Link>
                    ))}
                  </div>
                )}
                {task.tests.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      Recommended Verification
                    </div>
                    {task.tests.map((cmd) => (
                      <CommandLine key={cmd} command={cmd} />
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
