import { Badge, type Tone } from "./primitives";
import { titleCase } from "@/lib/utils";

const QUESTION: Record<string, Tone> = {
  approved: "ok", pending_review: "warn", draft: "neutral", rejected: "danger", quarantined: "violet", retired: "neutral", archived: "neutral",
};
const LEAK: Record<string, Tone> = { none: "neutral", suspected: "warn", confirmed: "danger", cleared: "ok" };
const SEVERITY: Record<string, Tone> = { critical: "danger", high: "danger", medium: "warn", low: "info" };
const VALIDATION: Record<string, Tone> = { passed: "ok", warning: "warn", failed: "danger", not_run: "neutral" };
const CALIBRATION: Record<string, Tone> = {
  within_tolerance: "ok", outside_tolerance: "danger", requires_review: "warn", insufficient_data: "neutral",
  pending_calibration: "neutral", calibrated_reference: "accent",
};
const RISK: Record<string, Tone> = { low: "ok", elevated: "warn", high: "danger" };
const ALERT_STATUS: Record<string, Tone> = { open: "danger", acknowledged: "warn", investigating: "info", confirmed: "violet", dismissed: "neutral" };
const EVIDENCE: Record<string, Tone> = { confirmed_text_match: "danger", statistical_suspicion: "warn", unverified_external: "info", human_confirmed: "violet" };

const LABELS: Record<string, string> = {
  pending_review: "Pending review", within_tolerance: "Within tolerance", outside_tolerance: "Outside tolerance",
  requires_review: "Requires review", insufficient_data: "Insufficient data", pending_calibration: "Pending calibration",
  calibrated_reference: "Calibrated", confirmed_text_match: "Text match (dataset)", statistical_suspicion: "Statistical suspicion",
  unverified_external: "Family / unverified", human_confirmed: "Human-confirmed",
};

type Kind = "question" | "leak" | "severity" | "validation" | "calibration" | "risk" | "alert" | "evidence";
const MAPS: Record<Kind, Record<string, Tone>> = {
  question: QUESTION, leak: LEAK, severity: SEVERITY, validation: VALIDATION, calibration: CALIBRATION, risk: RISK,
  alert: ALERT_STATUS, evidence: EVIDENCE,
};

export function StatusBadge({ kind, value, className }: { kind: Kind; value: string | null | undefined; className?: string }) {
  if (!value) return <span className="text-fg-subtle">—</span>;
  const tone = MAPS[kind][value] ?? "neutral";
  const label = kind === "leak" && value === "none" ? "No signal" : LABELS[value] ?? titleCase(value);
  return <Badge tone={tone} dot={kind !== "severity"} className={className}>{kind === "severity" ? value.toUpperCase() : label}</Badge>;
}

export function SectionBadge({ section }: { section: string }) {
  const tone: Record<string, Tone> = { QUANT: "accent", LOGICAL: "info", VERBAL: "violet" };
  const label: Record<string, string> = { QUANT: "Quant", LOGICAL: "Logical", VERBAL: "Verbal" };
  return <Badge tone={tone[section] ?? "neutral"}>{label[section] ?? section}</Badge>;
}

export function DifficultyPill({ value }: { value: string }) {
  const dots = { easy: 1, medium: 2, hard: 3 }[value] ?? 0;
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px] text-fg-muted" aria-label={`Difficulty ${value}`}>
      <span className="flex gap-0.5" aria-hidden>
        {[1, 2, 3].map((i) => <span key={i} className={`h-2.5 w-1 rounded-sm ${i <= dots ? "bg-fg-muted" : "bg-surface-3"}`} />)}
      </span>
      {titleCase(value)}
    </span>
  );
}
