import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Table({ className, ...p }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)} {...p} />
    </div>
  );
}
export function THead(p: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="bg-surface-2/60 text-left" {...p} />;
}
export function Th({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("h-9 whitespace-nowrap border-b border-line px-3 text-[11.5px] font-medium uppercase tracking-wider text-fg-subtle first:pl-4 last:pr-4", className)} {...p} />;
}
export function Tr({ className, onClick, ...p }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn("border-b border-line/70 transition-colors last:border-0", onClick && "cursor-pointer hover:bg-surface-2/70 focus-within:bg-surface-2/70", className)}
      onClick={onClick}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(e as any); } : undefined}
      {...p}
    />
  );
}
export function Td({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-2.5 align-middle first:pl-4 last:pr-4", className)} {...p} />;
}
