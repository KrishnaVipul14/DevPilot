"use client";

import { useEffect, useState } from "react";
import { Check, Copy, FlaskConical, Play, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/States";

interface TestScaffoldModalProps {
  open: boolean;
  onClose: () => void;
  defaultSymbol?: string;
}

export function TestScaffoldModal({ open, onClose, defaultSymbol = "" }: TestScaffoldModalProps) {
  const [symbolInput, setSymbolInput] = useState(defaultSymbol);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [result, setResult] = useState<{
    symbol: string;
    target_file: string;
    suggested_test_file: string;
    language: string;
    framework: string;
    command: string;
    test_code: string;
  } | null>(null);

  useEffect(() => {
    if (open) {
      setSymbolInput(defaultSymbol);
      setError(null);
      setCopied(false);
      if (defaultSymbol.trim()) {
        void handleGenerate(defaultSymbol.trim());
      } else {
        setResult(null);
      }
    }
  }, [open, defaultSymbol]);

  if (!open) return null;

  const handleGenerate = async (targetSymbol: string) => {
    const sym = targetSymbol.trim();
    if (!sym) {
      setError("Please specify a function, method, or class name.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.testgen(sym);
      if (!data.success) {
        setError(data.error || "Failed to generate test scaffold.");
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(errorMessage(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!result?.test_code) return;
    try {
      await navigator.clipboard.writeText(result.test_code);
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
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-600/20 text-emerald-400">
              <FlaskConical className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Automated Unit Test Scaffold Generator
              </h2>
              <p className="text-[11px] text-zinc-400">
                Generates robust, runnable pytest or vitest test cases from AST signatures.
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

        <div className="p-5 flex-1 overflow-y-auto space-y-4">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleGenerate(symbolInput);
              }}
              placeholder="Target function or class (e.g. validate_token, SimpleRouter.get)…"
              className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none"
            />
            <Button
              variant="primary"
              loading={loading}
              onClick={() => void handleGenerate(symbolInput)}
            >
              Generate Scaffold
            </Button>
          </div>

          {error && <ErrorBanner message={error} />}

          {result && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-xs">
                <div>
                  <div className="text-[11px] text-zinc-400">Target File</div>
                  <div className="font-mono text-zinc-200">{result.target_file}</div>
                </div>
                <div>
                  <div className="text-[11px] text-zinc-400">Suggested Test File</div>
                  <div className="font-mono text-emerald-300">{result.suggested_test_file}</div>
                </div>
                <div>
                  <div className="text-[11px] text-zinc-400">Run Command</div>
                  <div className="font-mono text-violet-300">{result.command}</div>
                </div>
              </div>

              <div className="relative rounded-lg border border-zinc-800 bg-zinc-950 p-3 font-mono text-xs text-zinc-200 overflow-x-auto whitespace-pre max-h-[40vh]">
                {result.test_code}
              </div>
            </div>
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
            disabled={!result?.test_code || loading}
            icon={copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          >
            {copied ? "Copied Test Code!" : "Copy Test Code"}
          </Button>
        </div>
      </div>
    </div>
  );
}
