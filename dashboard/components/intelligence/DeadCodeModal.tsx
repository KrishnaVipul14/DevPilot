"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, FileCode, Trash2, X, RefreshCw } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/States";

interface DeadCodeModalProps {
  open: boolean;
  onClose: () => void;
}

export function DeadCodeModal({ open, onClose }: DeadCodeModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<{
    dead_symbols_count: number;
    lines_reclaimable: number;
    symbols: Array<{
      id: string;
      name: string;
      kind: string;
      file: string;
      line: number | null;
      lines_of_code: number;
      reason: string;
    }>;
  } | null>(null);

  const fetchDeadCode = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.deadcode();
      setData(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && !data) {
      fetchDeadCode();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-rose-600/20 text-rose-400">
              <Trash2 className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-zinc-100">Dead Code & Orphaned Symbol Detector</h2>
              <p className="text-xs text-zinc-400">
                Identifies unused functions and classes with 0 AST incoming callers and no route bindings
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" loading={loading} onClick={fetchDeadCode}>
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Scan
            </Button>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Summary Metric Bar */}
        {data && (
          <div className="grid grid-cols-2 border-b border-zinc-800/80 bg-zinc-900/40 px-6 py-3">
            <div>
              <span className="text-xs text-zinc-400">Unreferenced Symbols</span>
              <div className="text-lg font-bold text-zinc-100">{data.dead_symbols_count}</div>
            </div>
            <div>
              <span className="text-xs text-zinc-400">Potential Lines Reclaimable</span>
              <div className="text-lg font-bold text-emerald-400">~{data.lines_reclaimable} LOC</div>
            </div>
          </div>
        )}

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && <ErrorBanner message={error} />}

          {loading && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-rose-500 border-t-transparent" />
              <p className="mt-3 text-sm text-zinc-300">Traversing call graph for orphaned symbols...</p>
            </div>
          )}

          {!loading && data && data.symbols.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <CheckCircle2 className="h-10 w-10 text-emerald-400" />
              <h3 className="mt-3 text-sm font-semibold text-zinc-100">Zero Dead Code Detected!</h3>
              <p className="mt-1 text-xs text-zinc-400">All parsed functions and classes have active callers or route attachments.</p>
            </div>
          )}

          {!loading && data && data.symbols.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-zinc-800 bg-zinc-900/80 text-zinc-400">
                  <tr>
                    <th className="px-3 py-2 font-medium">Symbol</th>
                    <th className="px-3 py-2 font-medium">Kind</th>
                    <th className="px-3 py-2 font-medium">File & Line</th>
                    <th className="px-3 py-2 font-medium">Lines</th>
                    <th className="px-3 py-2 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60 bg-zinc-950 font-mono text-zinc-300">
                  {data.symbols.map((sym, idx) => (
                    <tr key={idx} className="hover:bg-zinc-900/50">
                      <td className="px-3 py-2 font-semibold text-zinc-100">{sym.name}</td>
                      <td className="px-3 py-2 text-zinc-400 capitalize">{sym.kind}</td>
                      <td className="px-3 py-2 text-zinc-400">
                        {sym.file}:{sym.line ?? 1}
                      </td>
                      <td className="px-3 py-2 text-emerald-400">{sym.lines_of_code} LOC</td>
                      <td className="px-3 py-2 text-zinc-400 font-sans text-[11px]">{sym.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
