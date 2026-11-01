"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Bug,
  Compass,
  FileCode,
  GitPullRequestArrow,
  History,
  LayoutDashboard,
  ListChecks,
  Network,
  Search,
  Settings,
  X,
} from "lucide-react";
import { useData } from "@/components/DataProvider";
import { SeverityBadge } from "@/components/ui/Badge";
import type { Finding } from "@/lib/types";

export function QuickCommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const { report } = useData();
  const [query, setQuery] = useState("");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) onClose();
      }
      if (e.key === "Escape" && open) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  const findings = useMemo(() => {
    if (!report?.findings) return [];
    const q = query.trim().toLowerCase();
    if (!q) return report.findings.slice(0, 8);
    return report.findings
      .filter((f) => {
        return (
          f.id.toLowerCase().includes(q) ||
          f.title.toLowerCase().includes(q) ||
          f.rule.toLowerCase().includes(q) ||
          (f.file && f.file.toLowerCase().includes(q))
        );
      })
      .slice(0, 10);
  }, [report, query]);

  const navItems = [
    { label: "Overview", href: "/", icon: LayoutDashboard },
    { label: "Findings", href: "/findings/", icon: Bug },
    { label: "Code Intelligence & Routes", href: "/intelligence/", icon: Network },
    { label: "AI Action Plan", href: "/plan/", icon: ListChecks },
    { label: "Fix Review & Worktree", href: "/fixes/", icon: GitPullRequestArrow },
    { label: "Repository Memory", href: "/memory/", icon: History },
  ];

  const filteredNav = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return navItems;
    return navItems.filter((item) => item.label.toLowerCase().includes(q));
  }, [query]);

  if (!open) return null;

  const navigateTo = (href: string) => {
    onClose();
    router.push(href);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/75 p-4 backdrop-blur-sm sm:pt-20">
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl animate-in fade-in zoom-in-95 duration-100"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center border-b border-zinc-800 px-4 py-3">
          <Search className="mr-3 h-4 w-4 shrink-0 text-violet-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search findings (DP001, rule, file) or pages..."
            autoFocus
            className="w-full bg-transparent text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[380px] overflow-y-auto p-2 space-y-4">
          {filteredNav.length > 0 && (
            <div>
              <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Navigation
              </div>
              <div className="space-y-0.5">
                {filteredNav.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.href}
                      type="button"
                      onClick={() => navigateTo(item.href)}
                      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs text-zinc-300 hover:bg-zinc-800/80 hover:text-zinc-100 transition-colors"
                    >
                      <Icon className="h-3.5 w-3.5 text-zinc-400" />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {findings.length > 0 && (
            <div>
              <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Findings ({findings.length})
              </div>
              <div className="space-y-1">
                {findings.map((f: Finding) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => navigateTo(`/findings/?id=${encodeURIComponent(f.id)}`)}
                    className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left text-xs text-zinc-300 hover:bg-zinc-800/80 hover:text-zinc-100 transition-colors"
                  >
                    <span className="font-mono text-[11px] text-zinc-500">{f.id}</span>
                    <SeverityBadge severity={f.severity} />
                    <div className="min-w-0 flex-1 truncate">
                      <div className="font-medium text-zinc-200 truncate">{f.title}</div>
                      <div className="text-[11px] text-zinc-500 truncate">
                        {f.file ? `${f.file}:${f.line ?? 1}` : f.module} · {f.rule}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {filteredNav.length === 0 && findings.length === 0 && (
            <div className="py-8 text-center text-xs text-zinc-500">
              No results found for &ldquo;{query}&rdquo;
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-zinc-800/80 bg-zinc-900/40 px-4 py-2 text-[11px] text-zinc-500">
          <div className="flex items-center gap-2">
            <kbd className="rounded border border-zinc-700 bg-zinc-800 px-1 py-0.5 text-[10px]">ESC</kbd>
            <span>to close</span>
          </div>
          <span>DevPilot Developer Palette</span>
        </div>
      </div>
    </div>
  );
}
