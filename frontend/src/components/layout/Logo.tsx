import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <defs>
        <linearGradient id="ag-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#A5B4FC" />
          <stop offset="1" stopColor="#6366F1" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" className="fill-surface-3" />
      <path d="M16 5.5l8.5 3.3v6.3c0 5.3-3.6 9.9-8.5 11.3-4.9-1.4-8.5-6-8.5-11.3V8.8L16 5.5z" fill="none" stroke="url(#ag-g)" strokeWidth="1.8" />
      <path d="M11.8 16.1l2.9 2.9 5.6-6" fill="none" stroke="#C7D2FE" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && (
        <div className="leading-none">
          <div className="text-[14px] font-semibold tracking-tight text-fg">AptiGuard <span className="text-accent">AI</span></div>
          <div className="mt-1 text-[10.5px] uppercase tracking-[0.16em] text-fg-subtle">Assessment integrity</div>
        </div>
      )}
    </div>
  );
}
