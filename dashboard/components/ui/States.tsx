"use client";

import { useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, Inbox } from "lucide-react";

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
  return (
    <EmptyState title="No scan yet">
      Run <Code>devpilot scan .</Code> in your repository. This page updates automatically when
      the scan finishes.
    </EmptyState>
  );
}
