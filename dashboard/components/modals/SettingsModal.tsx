"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, Eye, EyeOff, KeyRound, RefreshCw, Sparkles, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";
import { useData } from "../DataProvider";
import { Button } from "../ui/Button";
import { ErrorBanner } from "../ui/States";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { refreshAll } = useData();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [provider, setProvider] = useState<"groq" | "gemini">("groq");
  const [groqKey, setGroqKey] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [model, setModel] = useState("");
  const [persist, setPersist] = useState(true);
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const data = await api.settings();
      setSettings(data);
      if (data.ai.provider === "gemini" || data.ai.provider === "groq") {
        setProvider(data.ai.provider);
      }
      setModel(data.ai.model ?? "");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setError(null);
      setSuccess(null);
      setGroqKey("");
      setGeminiKey("");
      void fetchSettings();
    }
  }, [open]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) {
        onClose();
      }
    };
    if (open) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, saving, onClose]);

  if (!open) return null;

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await api.updateSettings({
        provider,
        model: model.trim() || undefined,
        groq_api_key: groqKey.trim() || undefined,
        gemini_api_key: geminiKey.trim() || undefined,
        persist_to_env: persist,
      });
      setSettings(updated);
      setGroqKey("");
      setGeminiKey("");
      await refreshAll();
      if (updated.ai.available) {
        setSuccess(`AI settings saved. Active provider: ${updated.ai.provider} (${updated.ai.model})`);
      } else {
        setSuccess("Settings updated, but AI provider reports: " + (updated.ai.reason || "unavailable. Check API key."));
      }
      setTimeout(() => {
        onClose();
      }, 1200);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const hasKey =
    provider === "groq" ? settings?.ai.has_groq_key : settings?.ai.has_gemini_key;
  const keyPreview =
    provider === "groq" ? settings?.ai.groq_key_preview : settings?.ai.gemini_key_preview;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-lg rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-modal-title"
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600/20 text-violet-400">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <h2 id="settings-modal-title" className="text-sm font-semibold text-zinc-100">
                AI & Provider Configuration
              </h2>
              <p className="text-[11px] text-zinc-400">
                Configure your API key and AI models for explanations and auto-fixes.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          {error && <ErrorBanner message={error} />}
          {success && (
            <div className="flex items-center gap-2 rounded-md border border-emerald-900/60 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>{success}</span>
            </div>
          )}

          {/* Current AI Status */}
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-300">Status</span>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  settings?.ai.available
                    ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60"
                    : "bg-amber-950 text-amber-400 border border-amber-800/60"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    settings?.ai.available ? "bg-emerald-400" : "bg-amber-400"
                  }`}
                />
                {settings?.ai.available ? "Ready" : "Key Needed"}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-zinc-400">
              {settings?.ai.reason || (settings?.ai.available ? "AI provider is active." : "API key is not configured.")}
            </p>
          </div>

          {/* Provider Selection */}
          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-2">
              Select AI Provider
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setProvider("groq");
                  if (model.toLowerCase().includes("gemini")) setModel("");
                }}
                className={`flex flex-col items-start p-3 rounded-lg border text-left transition-colors ${
                  provider === "groq"
                    ? "border-violet-500 bg-violet-950/20 text-zinc-100"
                    : "border-zinc-800 bg-zinc-950/40 text-zinc-400 hover:border-zinc-700"
                }`}
              >
                <div className="flex items-center gap-1.5 font-medium text-xs">
                  <span>Groq</span>
                  <span className="rounded bg-violet-900/60 px-1 py-0.2 text-[9px] text-violet-300">
                    Fast / Free tier
                  </span>
                </div>
                <span className="text-[10px] text-zinc-500 mt-1">
                  Default: llama-3.3-70b-versatile
                </span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setProvider("gemini");
                  const m = model.toLowerCase();
                  if (m.includes("llama") || m.includes("mixtral") || m.includes("gemma") || m.includes("qwen")) {
                    setModel("");
                  }
                }}
                className={`flex flex-col items-start p-3 rounded-lg border text-left transition-colors ${
                  provider === "gemini"
                    ? "border-violet-500 bg-violet-950/20 text-zinc-100"
                    : "border-zinc-800 bg-zinc-950/40 text-zinc-400 hover:border-zinc-700"
                }`}
              >
                <div className="font-medium text-xs">Google Gemini</div>
                <span className="text-[10px] text-zinc-500 mt-1">
                  Default: gemini-flash-lite-latest
                </span>
              </button>
            </div>
          </div>

          {/* API Key Input */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium text-zinc-300">
                {provider === "groq" ? "Groq API Key" : "Gemini API Key"}
              </label>
              {hasKey && (
                <span className="text-[11px] text-emerald-400 font-mono">
                  Configured: {keyPreview}
                </span>
              )}
            </div>

            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={provider === "groq" ? groqKey : geminiKey}
                onChange={(e) =>
                  provider === "groq" ? setGroqKey(e.target.value) : setGeminiKey(e.target.value)
                }
                placeholder={hasKey ? "Leave blank to keep existing key, or enter new key…" : "Enter API key…"}
                disabled={saving || loading}
                className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 pr-10 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-2.5 text-zinc-500 hover:text-zinc-300"
                title={showKey ? "Hide key" : "Show key"}
              >
                {showKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              </button>
            </div>

            <div className="mt-1.5 flex items-center justify-between text-[11px] text-zinc-500">
              <span>Never shared externally; kept local to your machine.</span>
              <a
                href={provider === "groq" ? "https://console.groq.com/keys" : "https://aistudio.google.com/app/apikey"}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-violet-400 hover:text-violet-300 hover:underline"
              >
                Get API key <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </div>

          {/* Custom Model */}
          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-1.5">
              Custom Model Override (optional)
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={provider === "groq" ? "llama-3.3-70b-versatile" : "gemini-flash-lite-latest"}
              disabled={saving || loading}
              className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none disabled:opacity-50"
            />
          </div>

          {/* Persist checkbox */}
          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="persist-checkbox"
              checked={persist}
              onChange={(e) => setPersist(e.target.checked)}
              disabled={saving}
              className="rounded border-zinc-700 bg-zinc-950 text-violet-600 focus:ring-0 focus:ring-offset-0"
            />
            <label htmlFor="persist-checkbox" className="text-xs text-zinc-300 cursor-pointer">
              Persist to local <code className="font-mono text-zinc-400">.env</code> file (so it persists across server restarts)
            </label>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-950/50 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
          >
            Cancel
          </button>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={saving || loading}
          >
            {saving ? (
              <>
                <RefreshCw className="mr-1.5 h-3 w-3 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <KeyRound className="mr-1.5 h-3 w-3" />
                Save AI Settings
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
