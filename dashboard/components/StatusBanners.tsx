"use client";

import { RefreshCw, WifiOff } from "lucide-react";
import { useData } from "./DataProvider";
import { API_BASE } from "@/lib/api";

/** Top-of-content banners: connection lost and "new scan loaded". */
export function StatusBanners() {
  const { connection, justUpdated, status } = useData();
  return (
    <>
      {connection === "offline" && (
        <div className="flex items-center gap-2 border-b border-red-900/60 bg-red-950/40 px-6 py-2 text-sm text-red-300">
          <WifiOff className="h-4 w-4" />
          Connection to the DevPilot server{API_BASE ? ` (${API_BASE})` : ""} was lost. Retrying
          every few seconds — make sure <code className="font-mono">devpilot dashboard</code> is
          still running.
        </div>
      )}
      {justUpdated && connection === "online" && (
        <div className="flex items-center gap-2 border-b border-emerald-900/50 bg-emerald-950/30 px-6 py-1.5 text-xs text-emerald-300">
          <RefreshCw className="h-3.5 w-3.5" />
          Updated — loaded scan {status?.scan_id ?? ""}
        </div>
      )}
    </>
  );
}
