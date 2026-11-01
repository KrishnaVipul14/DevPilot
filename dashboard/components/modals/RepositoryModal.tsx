"use client";

import { useEffect, useState } from "react";
import { FolderGit2, Play, RefreshCw, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useData } from "../DataProvider";
import { Button } from "../ui/Button";
import { ErrorBanner } from "../ui/States";

interface RepositoryModalProps {
  open: boolean;
  onClose: () => void;
}

export function RepositoryModal({ open, onClose }: RepositoryModalProps) {
  const { status, refreshAll } = useData();
  const [pathInput, setPathInput] = useState("");
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingAction, setLoadingAction] = useState<"switch" | "scan" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (open && status?.repository.path) {
      setPathInput(status.repository.path);
      setError(null);
      setSuccess(null);
    }
  }, [open, status?.repository.path]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) {
        onClose();
      }
    };
    if (open) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, loading, onClose]);

  if (!open) return null;

  const handleLoadDemo = async () => {
    setLoading(true);
    setLoadingAction("switch");
    setError(null);
    setSuccess(null);
    try {
      await api.demo();
      await refreshAll();
      setSuccess("Loaded Demo Project successfully!");
      setTimeout(() => {
        onClose();
      }, 700);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      setLoadingAction(null);
    }
  };

  const handleSwitchOnly = async () => {
    const target = pathInput.trim();
    if (!target) {
      setError("Please specify a directory path.");
      return;
    }
    setLoading(true);
    setLoadingAction("switch");
    setError(null);
    setSuccess(null);
    try {
      await api.changeRepository(target);
      await refreshAll();
      setSuccess("Repository directory updated.");
      setTimeout(() => {
        onClose();
      }, 700);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      setLoadingAction(null);
    }
  };

  const handleScan = async () => {
    const target = pathInput.trim();
    if (!target) {
      setError("Please specify a directory path.");
      return;
    }
    setLoading(true);
    setLoadingAction("scan");
    setError(null);
    setSuccess(null);
    try {
      await api.scan({ path: target, offline });
      await refreshAll();
      setSuccess("Scan completed successfully!");
      setTimeout(() => {
        onClose();
      }, 700);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      setLoadingAction(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-xl rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="repo-modal-title"
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600/20 text-violet-400">
              <FolderGit2 className="h-4 w-4" />
            </div>
            <div>
              <h2 id="repo-modal-title" className="text-sm font-semibold text-zinc-100">
                Change Target Repository
              </h2>
              <p className="text-[11px] text-zinc-400">
                Switch directory or run a fresh scan without restarting DevPilot.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {error && <ErrorBanner message={error} />}
          {success && (
            <div className="rounded-md border border-emerald-900/60 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300">
              {success}
            </div>
          )}

          <div className="rounded-lg border border-violet-800/40 bg-violet-950/20 p-3 flex items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-violet-200">
                <span>🚀 Built-in Demo Project</span>
                <span className="rounded bg-violet-500/20 px-1 py-0.2 text-[10px] text-violet-300">demo-app</span>
              </div>
              <div className="text-[11px] text-zinc-400 mt-0.5">
                Auth routes, billing logic, vulnerabilities, test cases, and action plans.
              </div>
            </div>
            <Button
              variant="secondary"
              onClick={handleLoadDemo}
              disabled={loading}
              className="shrink-0 border-violet-700 bg-violet-900/30 text-violet-200 hover:bg-violet-800/50 text-xs py-1 px-2.5"
            >
              Load Demo
            </Button>
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-1.5">
              Repository Directory Path
            </label>
            <input
              type="text"
              value={pathInput}
              onChange={(e) => setPathInput(e.target.value)}
              placeholder="/path/to/target/repository"
              disabled={loading}
              className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none disabled:opacity-50"
            />
            <p className="mt-1 text-[11px] text-zinc-500">
              Current: <code className="text-zinc-400">{status?.repository.path ?? "—"}</code>
            </p>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="offline-checkbox"
              checked={offline}
              onChange={(e) => setOffline(e.target.checked)}
              disabled={loading}
              className="rounded border-zinc-700 bg-zinc-950 text-violet-600 focus:ring-0 focus:ring-offset-0"
            />
            <label htmlFor="offline-checkbox" className="text-xs text-zinc-300 cursor-pointer">
              Offline scan (skip external network calls to vulnerability databases)
            </label>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-950/50 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
          >
            Cancel
          </button>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleSwitchOnly}
              disabled={loading}
            >
              {loadingAction === "switch" ? (
                <>
                  <RefreshCw className="mr-1.5 h-3 w-3 animate-spin" />
                  Switching…
                </>
              ) : (
                "Switch Only"
              )}
            </Button>
            <Button
              variant="primary"
              onClick={handleScan}
              disabled={loading}
            >
              {loadingAction === "scan" ? (
                <>
                  <RefreshCw className="mr-1.5 h-3 w-3 animate-spin" />
                  Scanning…
                </>
              ) : (
                <>
                  <Play className="mr-1.5 h-3 w-3" />
                  Scan Now
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
