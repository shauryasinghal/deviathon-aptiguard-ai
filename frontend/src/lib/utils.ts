import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...c: ClassValue[]) => twMerge(clsx(c));

export const fmtInt = (n: number | null | undefined) => (n == null ? "—" : new Intl.NumberFormat("en-IN").format(n));

export const fmtNum = (n: number | null | undefined, d = 2) =>
  n == null || Number.isNaN(n) ? "—" : Number(n).toFixed(d).replace(/\.?0+$/, (m) => (m.includes(".") ? "" : m));

export const fmtFixed = (n: number | null | undefined, d = 2) => (n == null || Number.isNaN(n) ? "—" : Number(n).toFixed(d));

export const fmtPct = (n: number | null | undefined, d = 0) => (n == null ? "—" : `${(n * 100).toFixed(d)}%`);

export const fmtSigned = (n: number | null | undefined, d = 2) =>
  n == null ? "—" : `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(d)}`;

export function fmtDate(s: string | null | undefined, withTime = true) {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
  return d.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function timeAgo(s: string | null | undefined) {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") ? s : s + "Z").getTime();
  const sec = Math.round((Date.now() - d) / 1000);
  const abs = Math.abs(sec);
  const unit: [number, Intl.RelativeTimeFormatUnit][] = [[60, "second"], [3600, "minute"], [86400, "hour"], [2592000, "day"], [31536000, "month"]];
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < 60) return rtf.format(-sec, "second");
  for (let i = 1; i < unit.length; i++) if (abs < unit[i][0]) return rtf.format(-Math.round(sec / unit[i - 1][0]), unit[i][1]);
  return rtf.format(-Math.round(sec / 31536000), "year");
}

export const SECTION_LABEL: Record<string, string> = { QUANT: "Quantitative", LOGICAL: "Logical", VERBAL: "Verbal" };
export const SECTIONS = ["QUANT", "LOGICAL", "VERBAL"] as const;

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
