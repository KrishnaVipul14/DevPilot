"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Bug,
  GitPullRequestArrow,
  History,
  LayoutDashboard,
  ListChecks,
  Network,
  Sparkles,
  WifiOff,
} from "lucide-react";
import { useData } from "./DataProvider";
import { relativeTime } from "@/lib/format";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/findings/", label: "Findings", icon: Bug },
  { href: "/intelligence/", label: "Code Intelligence", icon: Network },
  { href: "/plan/", label: "AI Action Plan", icon: ListChecks },
  { href: "/fixes/", label: "Fix Review", icon: GitPullRequestArrow },
  { href: "/memory/", label: "Repository Memory", icon: History },
];

function normalize(p: string): string {
  return p.length > 1 ? p.replace(/\/+$/, "") : p;
}

export function Sidebar() {
  const pathname = normalize(usePathname() ?? "/");
  const { status, connection, justUpdated } = useData();

  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-zinc-800 bg-zinc-950 md:sticky md:top-0 md:h-screen md:w-56 md:border-b-0 md:border-r">
      <div className="flex items-center gap-2 px-4 py-3.5">
        <div className="flex h-6 w-6 items-center justify-center rounded bg-violet-600">
          <Activity className="h-3.5 w-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold tracking-tight text-zinc-100">DevPilot</span>
      </div>

      <div className="mx-3 mb-3 rounded-md border border-zinc-800 bg-zinc-900/60 px-2.5 py-2">
        <div className="text-[10px] uppercase tracking-wide text-zinc-500">Repository</div>
        <div className="truncate text-sm font-medium text-zinc-200" title={status?.repository.path}>
          {status?.repository.name ?? "—"}
        </div>
        {status?.finished_at && (
          <div className="mt-0.5 text-[11px] text-zinc-500">
            Last scan {relativeTime(status.finished_at)}
          </div>
        )}
      </div>

      <nav className="flex gap-0.5 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === normalize(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex shrink-0 items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-zinc-800/80 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
            >
              <Icon className={`h-4 w-4 ${active ? "text-violet-400" : ""}`} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto hidden space-y-1.5 border-t border-zinc-800 px-4 py-3 text-[11px] md:block">
        <ConnectionIndicator connection={connection} justUpdated={justUpdated} />
        <div className="flex items-center gap-1.5 text-zinc-500" title={status?.ai.reason ?? undefined}>
          <Sparkles className={`h-3 w-3 ${status?.ai.available ? "text-violet-400" : ""}`} />
          {status?.ai.available
            ? `AI: ${[status.ai.provider, status.ai.model].filter(Boolean).join("/")}`
            : "AI unavailable"}
        </div>
      </div>
    </aside>
  );
}

function ConnectionIndicator({
  connection,
  justUpdated,
}: {
  connection: string;
  justUpdated: boolean;
}) {
  if (connection === "offline") {
    return (
      <div className="flex items-center gap-1.5 text-red-400">
        <WifiOff className="h-3 w-3" /> Disconnected
      </div>
    );
  }
  if (connection === "connecting") {
    return (
      <div className="flex items-center gap-1.5 text-zinc-500">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" /> Connecting…
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 text-zinc-500">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      Live
      {justUpdated && <span className="ml-1 text-emerald-400">· Updated</span>}
    </div>
  );
}
