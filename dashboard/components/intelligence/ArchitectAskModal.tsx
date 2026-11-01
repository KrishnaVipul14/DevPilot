"use client";

import { useState } from "react";
import { Bot, HelpCircle, Send, Sparkles, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/States";

interface ArchitectAskModalProps {
  open: boolean;
  onClose: () => void;
}

const PRESET_QUESTIONS = [
  "How does authentication and token verification work in this codebase?",
  "Where are all API routes defined and what handlers are attached to them?",
  "What are the highest priority security and bug findings?",
  "How do I run tests and what test coverage exists?",
];

export function ArchitectAskModal({ open, onClose }: ArchitectAskModalProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chat, setChat] = useState<
    {
      q: string;
      a: string;
      provider?: string;
      model?: string;
      offline?: boolean;
      files?: string[];
    }[]
  >([]);

  if (!open) return null;

  const handleAsk = async (query: string) => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.ask(q);
      setChat((prev) => [
        ...prev,
        {
          q: res.question,
          a: res.answer,
          provider: res.provider,
          model: res.model,
          offline: res.offline,
          files: res.referenced_files,
        },
      ]);
      setQuestion("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-3xl rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl overflow-hidden flex flex-col h-[85vh]"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600/20 text-violet-400">
              <Bot className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-1.5">
                <span>DevPilot Repository Architect</span>
                <span className="rounded bg-violet-500/20 px-1 py-0.2 text-[9px] font-bold text-violet-300 border border-violet-500/30">
                  Codebase Q&A
                </span>
              </h2>
              <p className="text-[11px] text-zinc-400">
                Ask architectural questions grounded in AST graphs, routes, findings, and documentation.
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

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {chat.length === 0 && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 space-y-3">
              <div className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
                <HelpCircle className="h-4 w-4 text-violet-400" />
                <span>Suggested Questions:</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {PRESET_QUESTIONS.map((pq) => (
                  <button
                    key={pq}
                    type="button"
                    onClick={() => void handleAsk(pq)}
                    className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2 text-left text-xs text-zinc-300 hover:border-violet-500/50 hover:bg-zinc-900 transition-colors"
                  >
                    {pq}
                  </button>
                ))}
              </div>
            </div>
          )}

          {chat.map((item, idx) => (
            <div key={idx} className="space-y-2">
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-lg bg-violet-600/30 border border-violet-500/40 px-3.5 py-2 text-xs text-violet-100">
                  {item.q}
                </div>
              </div>
              <div className="flex justify-start">
                <div className="max-w-[95%] rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs text-zinc-200 space-y-2">
                  <div className="flex items-center justify-between border-b border-zinc-800 pb-2 text-[10px] text-zinc-400">
                    <span className="flex items-center gap-1 text-violet-400 font-medium">
                      <Sparkles className="h-3 w-3" />
                      DevPilot Architect {item.offline ? "(Deterministic Mode)" : `(${item.provider})`}
                    </span>
                  </div>
                  <div className="whitespace-pre-wrap leading-relaxed font-sans">{item.a}</div>
                  {item.files && item.files.length > 0 && (
                    <div className="pt-2 text-[11px] text-zinc-400 border-t border-zinc-850">
                      Referenced assets: <code className="text-zinc-300">{item.files.join(", ")}</code>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {error && <ErrorBanner message={error} />}
        </div>

        <div className="border-t border-zinc-800 bg-zinc-950/50 p-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleAsk(question);
            }}
            className="flex items-center gap-2"
          >
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask anything about the codebase (e.g. how does billing checkout work?)…"
              disabled={loading}
              className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3.5 py-2 text-xs text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none disabled:opacity-50"
            />
            <Button
              type="submit"
              variant="primary"
              loading={loading}
              disabled={!question.trim()}
              icon={<Send className="h-3.5 w-3.5" />}
            >
              Ask
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
