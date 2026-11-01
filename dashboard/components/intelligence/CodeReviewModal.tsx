"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, AlertTriangle, MessageSquare, Copy, Check, GitPullRequest, ShieldAlert, Sparkles, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/States";

interface CodeReviewModalProps {
  open: boolean;
  onClose: () => void;
  initialMode?: "review" | "pr";
}

export function CodeReviewModal({ open, onClose, initialMode = "review" }: CodeReviewModalProps) {
  const [mode, setMode] = useState<"review" | "pr">(initialMode);
  const [base, setBase] = useState("HEAD~1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [reviewResult, setReviewResult] = useState<{
    verdict: string;
    summary: string;
    key_strengths: string[];
    critical_risks: string[];
    actionable_suggestions: string[];
    markdown_review: string;
    provider: string;
  } | null>(null);

  const [prResult, setPrResult] = useState<{
    title: string;
    summary: string;
    changes: string[];
    impact: string;
    testing_plan: string[];
    markdown_pr: string;
    provider: string;
  } | null>(null);

  useEffect(() => {
    if (open) {
      setMode(initialMode);
      if (initialMode === "review" && !reviewResult) {
        handleRunReview();
      } else if (initialMode === "pr" && !prResult) {
        handleRunPr();
      }
    }
  }, [open, initialMode]);

  if (!open) return null;

  const handleRunReview = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.review(base);
      setReviewResult(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleRunPr = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.pr(base);
      setPrResult(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-600/20 text-violet-400">
              <GitPullRequest className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-zinc-100">
                {mode === "review" ? "Automated PR Code Reviewer" : "Automated PR Description Generator"}
              </h2>
              <p className="text-xs text-zinc-400">
                Staff-engineer quality review grounded in AST impact analysis
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-zinc-800 bg-zinc-900/60 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => {
                  setMode("review");
                  if (!reviewResult) handleRunReview();
                }}
                className={`rounded px-2.5 py-1 font-medium transition ${
                  mode === "review" ? "bg-violet-600 text-white" : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                Code Review
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("pr");
                  if (!prResult) handleRunPr();
                }}
                className={`rounded px-2.5 py-1 font-medium transition ${
                  mode === "pr" ? "bg-violet-600 text-white" : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                PR Generator
              </button>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Base Controls */}
        <div className="flex items-center justify-between border-b border-zinc-800/80 bg-zinc-900/40 px-6 py-2.5 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-zinc-400">Git Base Ref:</span>
            <input
              type="text"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder="e.g. HEAD~1, main"
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-xs text-zinc-200 focus:border-violet-500 focus:outline-none"
            />
            <Button
              variant="secondary"
              loading={loading}
              onClick={() => (mode === "review" ? handleRunReview() : handleRunPr())}
            >
              Re-run
            </Button>
          </div>
          {(reviewResult || prResult) && (
            <button
              type="button"
              onClick={() =>
                copyToClipboard(
                  mode === "review"
                    ? reviewResult?.markdown_review ?? ""
                    : prResult?.markdown_pr ?? ""
                )
              }
              className="flex items-center gap-1.5 rounded border border-zinc-700 bg-zinc-800/80 px-2.5 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied!" : "Copy Markdown"}
            </button>
          )}
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && <ErrorBanner message={error} />}

          {loading && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
              <p className="mt-3 text-sm text-zinc-300">
                {mode === "review" ? "Analyzing git diff & AST blast radius..." : "Generating PR summary & test plan..."}
              </p>
              <p className="text-xs text-zinc-500">Checking routes, callers, and regression tests</p>
            </div>
          )}

          {!loading && mode === "review" && reviewResult && (
            <div className="space-y-4">
              {/* Verdict header banner */}
              <div
                className={`flex items-center justify-between rounded-lg border p-4 ${
                  reviewResult.verdict === "APPROVE"
                    ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-200"
                    : reviewResult.verdict === "REQUEST_CHANGES"
                    ? "border-rose-500/30 bg-rose-950/20 text-rose-200"
                    : "border-amber-500/30 bg-amber-950/20 text-amber-200"
                }`}
              >
                <div className="flex items-center gap-3">
                  {reviewResult.verdict === "APPROVE" ? (
                    <CheckCircle2 className="h-6 w-6 text-emerald-400" />
                  ) : reviewResult.verdict === "REQUEST_CHANGES" ? (
                    <ShieldAlert className="h-6 w-6 text-rose-400" />
                  ) : (
                    <MessageSquare className="h-6 w-6 text-amber-400" />
                  )}
                  <div>
                    <div className="font-semibold tracking-wide text-sm uppercase">
                      Verdict: {reviewResult.verdict.replace("_", " ")}
                    </div>
                    <div className="text-xs opacity-90">{reviewResult.summary}</div>
                  </div>
                </div>
                <div className="text-right text-[11px] opacity-75">
                  Engine: {reviewResult.provider}
                </div>
              </div>

              {/* Strengths & Risks */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {reviewResult.key_strengths.length > 0 && (
                  <div className="rounded-lg border border-emerald-900/40 bg-zinc-900/60 p-3">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Key Strengths
                    </div>
                    <ul className="mt-2 space-y-1 text-xs text-zinc-300">
                      {reviewResult.key_strengths.map((s, idx) => (
                        <li key={idx} className="flex items-start gap-1.5">
                          <span className="text-emerald-500">•</span> {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {reviewResult.critical_risks.length > 0 && (
                  <div className="rounded-lg border border-rose-900/40 bg-zinc-900/60 p-3">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-400">
                      <AlertTriangle className="h-3.5 w-3.5" /> Critical Risks
                    </div>
                    <ul className="mt-2 space-y-1 text-xs text-zinc-300">
                      {reviewResult.critical_risks.map((r, idx) => (
                        <li key={idx} className="flex items-start gap-1.5">
                          <span className="text-rose-500">•</span> {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Actionable Suggestions */}
              {reviewResult.actionable_suggestions.length > 0 && (
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-violet-400">
                    <Sparkles className="h-3.5 w-3.5" /> Actionable Suggestions
                  </div>
                  <ul className="mt-2 space-y-1 text-xs text-zinc-300">
                    {reviewResult.actionable_suggestions.map((sug, idx) => (
                      <li key={idx} className="flex items-start gap-1.5">
                        <span className="text-violet-500">→</span> {sug}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Raw Markdown PR Comment */}
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="text-xs font-semibold text-zinc-400 mb-2">GitHub PR Markdown Preview:</div>
                <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-zinc-300 bg-zinc-950 p-3 rounded border border-zinc-800/80">
                  {reviewResult.markdown_review}
                </pre>
              </div>
            </div>
          )}

          {!loading && mode === "pr" && prResult && (
            <div className="space-y-4">
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
                <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Suggested PR Title</div>
                <div className="mt-1 font-mono text-sm font-semibold text-zinc-100">{prResult.title}</div>
              </div>

              <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
                <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Executive Summary</div>
                <div className="mt-1 text-xs text-zinc-200">{prResult.summary}</div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
                  <div className="text-xs font-semibold text-violet-400">Modified Files / Components</div>
                  <ul className="mt-2 space-y-1 text-xs font-mono text-zinc-300">
                    {prResult.changes.slice(0, 8).map((c, idx) => (
                      <li key={idx}>• {c}</li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
                  <div className="text-xs font-semibold text-emerald-400">Targeted Test Plan</div>
                  <ul className="mt-2 space-y-1 font-mono text-xs text-zinc-300">
                    {prResult.testing_plan.map((cmd, idx) => (
                      <li key={idx} className="bg-zinc-950 px-2 py-0.5 rounded border border-zinc-800">
                        $ {cmd}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="text-xs font-semibold text-zinc-400 mb-2">GitHub PR Description Preview:</div>
                <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-zinc-300 bg-zinc-950 p-3 rounded border border-zinc-800/80">
                  {prResult.markdown_pr}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
