import { AlertTriangle, ChevronLeft, ChevronRight, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { cn, fmtInt } from "@/lib/utils";
import { Button } from "./button";
import { Card, Skeleton, Tip } from "./primitives";

export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-[11.5px] font-medium uppercase tracking-[0.14em] text-accent">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint, icon, tone = "neutral", loading, onClick, help }: {
  label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "neutral" | "accent" | "ok" | "warn" | "danger";
  loading?: boolean; onClick?: () => void; help?: string;
}) {
  const ring = { neutral: "text-fg-subtle", accent: "text-accent", ok: "text-ok", warn: "text-warn", danger: "text-danger" }[tone];
  const Comp = onClick ? "button" : "div";
  return (
    <Card className={cn("group relative overflow-hidden text-left", onClick && "transition-colors hover:border-line-strong")}>
      <Comp onClick={onClick} className="block w-full p-4 text-left">
        <div className="flex items-center justify-between">
          <span className="text-[12.5px] font-medium text-fg-muted">
            {help ? <Tip content={help}><span className="cursor-help border-b border-dotted border-fg-subtle/60">{label}</span></Tip> : label}
          </span>
          {icon && <span className={cn("[&_svg]:size-4", ring)}>{icon}</span>}
        </div>
        <div className="mt-2.5 text-[26px] font-semibold leading-none tracking-tight tabular">
          {loading ? <Skeleton className="h-7 w-16" /> : value}
        </div>
        {hint && <div className="mt-2 text-xs text-fg-subtle">{hint}</div>}
      </Comp>
    </Card>
  );
}

export function EmptyState({ title, description, action, icon }: { title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 grid size-10 place-items-center rounded-lg border border-line bg-surface-2 text-fg-subtle [&_svg]:size-5">{icon ?? <Inbox />}</div>
      <h3 className="text-sm font-medium text-fg">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-[13px] text-fg-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Something went wrong";
  const code = error instanceof ApiError ? `${error.status || ""} ${error.code}` : "";
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center" role="alert">
      <div className="mb-3 grid size-10 place-items-center rounded-lg border border-danger/30 bg-danger-soft text-danger"><AlertTriangle className="size-5" /></div>
      <h3 className="text-sm font-medium">Could not load this data</h3>
      <p className="mt-1 max-w-md text-[13px] text-fg-muted">{msg}</p>
      {code && <p className="mt-1 font-mono text-[11px] text-fg-subtle">{code}</p>}
      {onRetry && <Button size="sm" className="mt-4" onClick={onRetry}><RefreshCw />Retry</Button>}
    </div>
  );
}

export function LoadingRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-5" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={cn("h-5", i % 3 === 0 ? "w-3/4" : "w-full")} />)}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-[13px] text-fg-muted">
      <span className="tabular">{total === 0 ? "No results" : `${fmtInt((page - 1) * pageSize + 1)}–${fmtInt(Math.min(page * pageSize, total))} of ${fmtInt(total)}`}</span>
      <div className="flex items-center gap-1">
        <Button size="icon-sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
        <span className="px-2 tabular">{page} / {pages}</span>
        <Button size="icon-sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
      </div>
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, ariaLabel }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; ariaLabel: string }) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="inline-flex items-center rounded-md border border-line-strong bg-surface-2 p-0.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn("h-7 rounded-[5px] px-2.5 text-[12.5px] font-medium transition-colors", value === o.value ? "bg-surface-3 text-fg shadow-card" : "text-fg-muted hover:text-fg")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function FilterBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-center gap-2 border-b border-line px-4 py-3", className)}>{children}</div>;
}

export function DataNotice({ children }: { children: ReactNode }) {
  return (
    <div className="mb-5 flex items-start gap-2 rounded-md border border-info/25 bg-info-soft px-3 py-2 text-[12.5px] text-info">
      <span className="mt-0.5 size-1.5 shrink-0 rounded-full bg-info" aria-hidden />
      <span>{children}</span>
    </div>
  );
}

export function KeyValue({ items, cols = 2 }: { items: [ReactNode, ReactNode][]; cols?: 1 | 2 | 3 | 4 }) {
  const grid = { 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-2 md:grid-cols-3", 4: "grid-cols-2 md:grid-cols-4" }[cols];
  return (
    <dl className={cn("grid gap-x-6 gap-y-3", grid)}>
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-[11.5px] uppercase tracking-wider text-fg-subtle">{k}</dt>
          <dd className="mt-0.5 truncate text-sm text-fg tabular">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
