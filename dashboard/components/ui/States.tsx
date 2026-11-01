"use client";

import { useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, FolderGit2, Inbox, Play, RefreshCw } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useData } from "../DataProvider";
import { RepositoryModal } from "../modals/RepositoryModal";

export function EmptyState({
  title,
  children,
  icon,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-zinc-800 px-6 py-12 text-center">
      <div className="mb-3 text-zinc-600">{icon ?? <Inbox className="h-7 w-7" />}</div>
      <div className="text-sm font-medium text-zinc-300">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-zinc-500">{children}</div>}
    </div>
  );
}

export function ErrorBanner({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="break-words">{message}</div>
        {children}
      </div>
    </div>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-zinc-800/80 px-1 py-0.5 font-mono text-[12px] text-zinc-200">
      {children}
    </code>
  );
}

export function CopyButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title="Copy to clipboard"
      className={`rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 ${className}`}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

export function CommandLine({ command }: { command: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 py-1.5">
      <span className="select-none font-mono text-xs text-zinc-600">$</span>
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-xs text-zinc-200">
        {command}
      </code>
      <CopyButton text={command} />
    </div>
  );
}

export function NoScanState() {
  const { status, refreshAll } = useData();
  const [scanning, setScanning] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repoModalOpen, setRepoModalOpen] = useState(false);

  const handleScanNow = async () => {
    setScanning(true);
    setError(null);
    try {
      await api.scan({ offline });
      await refreshAll();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setScanning(false);
    }
  };

  return (
    <>
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-zinc-800 bg-zinc-900/20 px-6 py-12 text-center">
        <div className="mb-3 text-zinc-600">
          <Inbox className="h-8 w-8" />
        </div>
        <div className="text-base font-semibold text-zinc-200">No scan report found</div>
        <div className="mt-1.5 max-w-md text-sm text-zinc-400">
          Target: <code className="rounded bg-zinc-800/80 px-1 py-0.5 font-mono text-xs text-zinc-300">{status?.repository.path ?? "."}</code>
        </div>
        <p className="mt-2 max-w-lg text-xs text-zinc-500">
          Run your first scan to analyze code health, dependencies, and architecture graph, or switch to a different project repository.
        </p>

        {error && (
          <div className="mt-4 max-w-md text-left w-full">
            <ErrorBanner message={error} />
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={handleScanNow}
            disabled={scanning}
            className="flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-violet-500 transition-colors disabled:opacity-50"
          >
            {scanning ? (
              <>
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                Scanning Repository…
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5" />
                Scan Now
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => setRepoModalOpen(true)}
            disabled={scanning}
            className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-800/60 px-3.5 py-2 text-xs font-medium text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors disabled:opacity-50"
          >
            <FolderGit2 className="h-3.5 w-3.5 text-zinc-400" />
            Change Repository
          </button>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <input
            type="checkbox"
            id="noscan-offline-toggle"
            checked={offline}
            onChange={(e) => setOffline(e.target.checked)}
            disabled={scanning}
            className="rounded border-zinc-700 bg-zinc-950 text-violet-600 focus:ring-0 focus:ring-offset-0"
          />
          <label htmlFor="noscan-offline-toggle" className="text-xs text-zinc-400 cursor-pointer">
            Offline scan mode (skip OSV vulnerability database query)
          </label>
        </div>

        <div className="mt-6 border-t border-zinc-800/80 pt-4 text-xs text-zinc-500">
          Or run in terminal: <Code>devpilot scan .</Code>
        </div>
      </div>

      <RepositoryModal
        open={repoModalOpen}
        onClose={() => setRepoModalOpen(false)}
      />
    </>
  );
}
