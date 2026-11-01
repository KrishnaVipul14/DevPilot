"use client";

import { useState } from "react";
import { Check, Copy, Terminal } from "lucide-react";

interface CodeBlockProps {
  code: string;
  language?: string;
  title?: string;
  maxHeight?: string;
  isDiff?: boolean;
}

export function CodeBlock({
  code,
  language,
  title,
  maxHeight = "450px",
  isDiff = false,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  const lines = code.split("\n");

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-inner">
      <div className="flex items-center justify-between border-b border-zinc-800/80 bg-zinc-900/70 px-3.5 py-1.5 text-xs">
        <div className="flex items-center gap-2 text-zinc-400">
          <Terminal className="h-3.5 w-3.5 text-violet-400" />
          <span className="font-mono font-medium text-zinc-300">
            {title || (isDiff ? "Unified Diff" : language || "Code")}
          </span>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      <div
        className="overflow-auto font-mono text-[11px] leading-relaxed select-text"
        style={{ maxHeight }}
      >
        {isDiff ? (
          <div className="p-2 space-y-0.5">
            {lines.map((line, idx) => {
              let rowCls = "text-zinc-300 px-2 py-0.5";
              if (line.startsWith("+++") || line.startsWith("---")) {
                rowCls = "text-zinc-400 font-bold bg-zinc-900/50 px-2 py-0.5";
              } else if (line.startsWith("@@")) {
                rowCls = "text-violet-300 bg-violet-950/30 px-2 py-0.5 border-y border-violet-900/40 my-1 font-semibold";
              } else if (line.startsWith("+")) {
                rowCls = "text-emerald-300 bg-emerald-950/35 border-l-2 border-emerald-500 px-2 py-0.5";
              } else if (line.startsWith("-")) {
                rowCls = "text-rose-300 bg-rose-950/35 border-l-2 border-rose-500 px-2 py-0.5";
              }

              return (
                <div key={idx} className={`flex items-start font-mono text-xs ${rowCls}`}>
                  <span className="w-8 shrink-0 select-none text-right pr-3 text-[10px] text-zinc-600">
                    {idx + 1}
                  </span>
                  <span className="min-w-0 flex-1 whitespace-pre break-all">{line || " "}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <pre className="p-3 text-zinc-200 whitespace-pre-wrap">{code}</pre>
        )}
      </div>
    </div>
  );
}
