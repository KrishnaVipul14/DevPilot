"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Network, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/States";

interface ArchitectureMermaidModalProps {
  open: boolean;
  onClose: () => void;
}

export function ArchitectureMermaidModal({ open, onClose }: ArchitectureMermaidModalProps) {
  const [mermaidCode, setMermaidCode] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCopied(false);

    api
      .mermaid()
      .then((res) => {
        if (!cancelled) setMermaidCode(res.mermaid);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const handleCopy = async () => {
    if (!mermaidCode) return;
    try {
      await navigator.clipboard.writeText(mermaidCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-2xl rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600/20 text-violet-400">
              <Network className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Repository Architecture Flowchart (Mermaid)
              </h2>
              <p className="text-[11px] text-zinc-400">
                Ready to paste into GitHub README, PR descriptions, or Mermaid Live Editor.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 flex-1 overflow-y-auto space-y-3">
          {error && <ErrorBanner message={error} />}
          {loading ? (
            <div className="flex items-center justify-center py-12 text-xs text-zinc-500">
              Generating architecture flowchart from AST graph…
            </div>
          ) : (
            <>
              <div className="relative rounded-lg border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs text-zinc-300 overflow-x-auto whitespace-pre max-h-[50vh]">
                {mermaidCode || "No graph elements found."}
              </div>
              <p className="text-[11px] text-zinc-500">
                Tip: In Markdown, wrap this block inside <code className="text-zinc-400">```mermaid ... ```</code> to render interactive diagrams.
              </p>
            </>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-950/50 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          >
            Close
          </button>
          <Button
            variant="primary"
            onClick={handleCopy}
            disabled={!mermaidCode || loading}
            icon={copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          >
            {copied ? "Copied Diagram!" : "Copy Mermaid Code"}
          </Button>
        </div>
      </div>
    </div>
  );
}
