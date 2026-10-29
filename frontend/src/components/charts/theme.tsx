import type { ReactNode } from "react";

export const C = {
  accent: "#7C83FF",
  accent2: "#A5B4FC",
  ok: "#34D399",
  warn: "#FBBF24",
  danger: "#F87171",
  info: "#38BDF8",
  violet: "#A78BFA",
  muted: "#6B7186",
  grid: "rgba(127,135,160,0.16)",
};

export const SECTION_COLORS: Record<string, string> = { QUANT: C.accent, LOGICAL: C.info, VERBAL: C.violet };
export const BAND_COLORS: Record<string, string> = { easy: C.ok, medium: C.accent, hard: C.violet };

export const axis = { stroke: C.muted, fontSize: 11, tickLine: false, axisLine: false } as const;

export function ChartTooltip({ active, payload, label, formatter }: {
  active?: boolean; payload?: any[]; label?: ReactNode; formatter?: (v: any, name: string, p: any) => ReactNode;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line-strong bg-surface-3 px-3 py-2 text-xs shadow-pop">
      {label !== undefined && <div className="mb-1 font-medium text-fg">{label}</div>}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2 text-fg-muted">
          <span className="size-2 rounded-full" style={{ background: p.color ?? p.fill }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 font-medium text-fg tabular">{formatter ? formatter(p.value, p.name, p) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-fg-muted">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-sm" style={{ background: i.dashed ? "transparent" : i.color, border: i.dashed ? `1.5px dashed ${i.color}` : undefined }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
