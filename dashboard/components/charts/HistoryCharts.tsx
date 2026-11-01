"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ACCENT_HEX, SEVERITIES, SEVERITY_HEX, formatShortDate } from "@/lib/format";
import type { ScanRow } from "@/lib/types";

const AXIS = { stroke: "#52525b", fontSize: 11, tickLine: false } as const;
const GRID = { stroke: "#27272a", strokeDasharray: "3 3" } as const;
const TOOLTIP = {
  contentStyle: {
    background: "#18181b",
    border: "1px solid #3f3f46",
    fontSize: 12,
    color: "#e4e4e7",
  },
  labelStyle: { color: "#a1a1aa" },
  cursor: { fill: "rgba(255,255,255,0.03)" },
} as const;

/** Scans in chronological order with a short label for the x-axis. */
function chronological(scans: ScanRow[]) {
  return [...scans]
    .sort((a, b) => (a.finished_at || a.started_at).localeCompare(b.finished_at || b.started_at))
    .map((s) => ({ ...s, label: formatShortDate(s.finished_at || s.started_at) }));
}

export function HealthTrendChart({ scans, height = 180 }: { scans: ScanRow[]; height?: number }) {
  const data = chronological(scans);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
        <CartesianGrid {...GRID} vertical={false} />
        <XAxis dataKey="label" {...AXIS} minTickGap={24} />
        <YAxis domain={[0, 100]} {...AXIS} />
        <Tooltip {...TOOLTIP} />
        <Line
          type="monotone"
          dataKey="health_score"
          name="Health"
          stroke={ACCENT_HEX}
          strokeWidth={2}
          dot={{ r: 2.5, fill: ACCENT_HEX }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function NewResolvedChart({ scans, height = 220 }: { scans: ScanRow[]; height?: number }) {
  const data = chronological(scans);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
        <CartesianGrid {...GRID} vertical={false} />
        <XAxis dataKey="label" {...AXIS} minTickGap={24} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TOOLTIP} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="new" name="New" stackId="d" fill="#f97316" isAnimationActive={false} />
        <Bar dataKey="reintroduced" name="Reintroduced" stackId="d" fill="#ef4444" isAnimationActive={false} />
        <Bar dataKey="resolved" name="Resolved" stackId="d" fill="#10b981" isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SeverityOverTimeChart({ scans, height = 220 }: { scans: ScanRow[]; height?: number }) {
  const data = chronological(scans).map((s) => {
    const row: Record<string, string | number> = { label: s.label };
    for (const sev of SEVERITIES) row[sev] = s.by_severity?.[sev] ?? 0;
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
        <CartesianGrid {...GRID} vertical={false} />
        <XAxis dataKey="label" {...AXIS} minTickGap={24} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TOOLTIP} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {SEVERITIES.map((sev) => (
          <Bar key={sev} dataKey={sev} stackId="s" fill={SEVERITY_HEX[sev]} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
