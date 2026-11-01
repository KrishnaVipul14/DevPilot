"use client";

import { useMemo, useState } from "react";
import { Check, Copy, ExternalLink, Globe, Search } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import type { GraphNode } from "@/lib/types";

interface RouteExplorerProps {
  nodes: GraphNode[];
}

export function RouteExplorer({ nodes }: RouteExplorerProps) {
  const [query, setQuery] = useState("");
  const [methodFilter, setMethodFilter] = useState("all");
  const [frameworkFilter, setFrameworkFilter] = useState("all");
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const routeNodes = useMemo(() => {
    return nodes.filter((n) => n.kind === "route");
  }, [nodes]);

  const frameworks = useMemo(() => {
    const set = new Set<string>();
    for (const r of routeNodes) {
      const fw = (r.meta?.framework as string) || "generic";
      set.add(fw);
    }
    return Array.from(set).sort();
  }, [routeNodes]);

  const methods = useMemo(() => {
    const set = new Set<string>();
    for (const r of routeNodes) {
      const m = (r.meta?.method as string) || (r.name.split(" ")[0] ?? "ALL");
      set.add(m.toUpperCase());
    }
    return Array.from(set).sort();
  }, [routeNodes]);

  const filteredRoutes = useMemo(() => {
    const q = query.trim().toLowerCase();
    return routeNodes.filter((r) => {
      const m = ((r.meta?.method as string) || r.name.split(" ")[0] || "").toUpperCase();
      const fw = ((r.meta?.framework as string) || "generic").toLowerCase();
      const path = ((r.meta?.path as string) || r.name.split(" ")[1] || r.name).toLowerCase();

      if (methodFilter !== "all" && m !== methodFilter.toUpperCase()) return false;
      if (frameworkFilter !== "all" && fw !== frameworkFilter.toLowerCase()) return false;
      if (q && !path.includes(q) && !r.name.toLowerCase().includes(q) && !(r.file ?? "").toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [routeNodes, query, methodFilter, frameworkFilter]);

  const handleCopy = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(path);
      setTimeout(() => setCopiedPath(null), 1500);
    } catch {
      setCopiedPath(null);
    }
  };

  const getMethodBadge = (m: string) => {
    switch (m.toUpperCase()) {
      case "GET":
        return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
      case "POST":
        return "bg-blue-500/15 text-blue-400 border-blue-500/30";
      case "PUT":
        return "bg-amber-500/15 text-amber-400 border-amber-500/30";
      case "DELETE":
        return "bg-rose-500/15 text-rose-400 border-rose-500/30";
      case "PATCH":
        return "bg-purple-500/15 text-purple-400 border-purple-500/30";
      default:
        return "bg-zinc-800 text-zinc-300 border-zinc-700";
    }
  };

  return (
    <Card
      title={`API Routes & HTTP Endpoints (${filteredRoutes.length})`}
      actions={
        <div className="flex items-center gap-1.5 text-xs text-zinc-400">
          <Globe className="h-3.5 w-3.5 text-violet-400" />
          <span>Multi-Framework Detection</span>
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search endpoint path, file, or method..."
            className="w-full rounded-md border border-zinc-800 bg-zinc-900 py-1.5 pl-8 pr-3 text-xs text-zinc-200 placeholder-zinc-500 focus:border-violet-500 focus:outline-none"
          />
        </div>

        <select
          value={methodFilter}
          onChange={(e) => setMethodFilter(e.target.value)}
          aria-label="Filter by HTTP method"
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs text-zinc-200"
        >
          <option value="all">All Methods</option>
          {methods.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>

        <select
          value={frameworkFilter}
          onChange={(e) => setFrameworkFilter(e.target.value)}
          aria-label="Filter by framework"
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs text-zinc-200"
        >
          <option value="all">All Frameworks</option>
          {frameworks.map((fw) => (
            <option key={fw} value={fw}>
              {fw.toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      {filteredRoutes.length === 0 ? (
        <div className="py-8 text-center text-xs text-zinc-500">
          No API endpoints matching the selected filters.
        </div>
      ) : (
        <div className="max-h-[400px] overflow-y-auto divide-y divide-zinc-800/60 rounded-md border border-zinc-800 bg-zinc-950/60">
          {filteredRoutes.map((r) => {
            const m = (r.meta?.method as string) || r.name.split(" ")[0] || "ALL";
            const path = (r.meta?.path as string) || r.name.split(" ")[1] || r.name;
            const fw = (r.meta?.framework as string) || "generic";

            return (
              <div
                key={r.id}
                className="flex items-center justify-between gap-3 px-3 py-2 text-xs hover:bg-zinc-900/50 transition-colors"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold tracking-wider ${getMethodBadge(
                      m
                    )}`}
                  >
                    {m.toUpperCase()}
                  </span>
                  <span className="font-mono font-medium text-zinc-200 truncate">{path}</span>
                  <Badge tone="neutral" className="!py-0 text-[10px]">
                    {fw}
                  </Badge>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  {r.file && (
                    <span className="font-mono text-[11px] text-zinc-500">
                      {r.file}:{r.line ?? 1}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleCopy(path)}
                    title="Copy route path"
                    className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
                  >
                    {copiedPath === path ? (
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
