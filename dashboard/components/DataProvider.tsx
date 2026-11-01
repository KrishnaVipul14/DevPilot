"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, errorMessage, isNetworkError, isNotFound } from "@/lib/api";
import type { Report, StatusResponse } from "@/lib/types";

const POLL_MS = 2500;
const UPDATED_FLASH_MS = 6000;

export type Connection = "connecting" | "online" | "offline";
export type ReportState = "loading" | "ready" | "missing" | "error";

interface DataContextValue {
  status: StatusResponse | null;
  connection: Connection;
  report: Report | null;
  reportState: ReportState;
  reportError: string | null;
  /** Increments whenever a new scan is detected; pages use it to refetch derived data. */
  version: number;
  /** True for a few seconds after a new scan was picked up. */
  justUpdated: boolean;
  refreshReport: () => Promise<void>;
  refreshAll: () => Promise<void>;
}

const DataContext = createContext<DataContextValue | null>(null);

export function useData(): DataContextValue {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used within <DataProvider>");
  return ctx;
}

export function DataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [report, setReport] = useState<Report | null>(null);
  const [reportState, setReportState] = useState<ReportState>("loading");
  const [reportError, setReportError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [justUpdated, setJustUpdated] = useState(false);

  const lastKey = useRef<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshReport = useCallback(async () => {
    try {
      const r = await api.report();
      setReport(r);
      setReportState("ready");
      setReportError(null);
    } catch (err) {
      if (isNotFound(err)) {
        setReport(null);
        setReportState("missing");
        setReportError(null);
      } else {
        setReportState((prev) => (prev === "ready" ? prev : "error"));
        setReportError(errorMessage(err));
      }
    }
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setConnection("online");
      const key = `${s.repository?.path ?? ""}|${s.has_report}|${s.scan_id ?? ""}|${s.report_mtime ?? ""}`;
      lastKey.current = key;
      await refreshReport();
      setVersion((v) => v + 1);
    } catch (err) {
      if (isNetworkError(err)) setConnection("offline");
    }
  }, [refreshReport]);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const s = await api.status();
        if (cancelled) return;
        setStatus(s);
        setConnection("online");
        const key = `${s.repository?.path ?? ""}|${s.has_report}|${s.scan_id ?? ""}|${s.report_mtime ?? ""}`;
        if (key !== lastKey.current) {
          const isFirst = lastKey.current === null;
          lastKey.current = key;
          await refreshReport();
          if (cancelled) return;
          setVersion((v) => v + 1);
          if (!isFirst) {
            setJustUpdated(true);
            if (flashTimer.current) clearTimeout(flashTimer.current);
            flashTimer.current = setTimeout(() => setJustUpdated(false), UPDATED_FLASH_MS);
          }
        }
      } catch (err) {
        if (cancelled) return;
        if (isNetworkError(err)) {
          setConnection("offline");
          // Force a refetch once the server comes back.
          lastKey.current = lastKey.current === null ? null : "__reconnect__";
        } else {
          setConnection("online");
        }
      }
    };

    void tick();
    const id = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
      if (flashTimer.current) clearTimeout(flashTimer.current);
    };
  }, [refreshReport]);

  return (
    <DataContext.Provider
      value={{
        status,
        connection,
        report,
        reportState,
        reportError,
        version,
        justUpdated,
        refreshReport,
        refreshAll,
      }}
    >
      {children}
    </DataContext.Provider>
  );
}
