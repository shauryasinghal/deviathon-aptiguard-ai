import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldQuestion } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingRows, Segmented } from "@/components/ui/page";
import { Badge, Card, CardBody, CardHeader, Label, Mono, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, titleCase } from "@/lib/utils";

type Flagged = {
  attempt_id: number; candidate: string; form: string; slot: string; status: string; submitted_at: string | null;
  official_score: number | null; official_max: number | null; alternative_score: number | null; alternative_max: number | null;
  decision: string; reopened_at: string | null;
  items: { code: string; reason: string; flagged_at: string; released_at?: string; attempt_status_when_flagged: string }[];
  resolutions: { decision: string; reason: string; by: { name: string }; at: string; final_score: number | null; final_max: number | null }[];
};

const DECISIONS = [
  { value: "retain_original", label: "Retain original score", help: "Exposure did not affect this candidate (e.g. it happened after the slot)." },
  { value: "use_alternative", label: "Use alternative score", help: "Exclude the withdrawn question(s) from this candidate's score." },
  { value: "reassessment", label: "Arrange reassessment", help: "Invalidate neither score; schedule a re-sit via a new assignment." },
] as const;

export function FlaggedAttempts() {
  const { can } = useAuth();
  const [state, setState] = useState<"pending" | "resolved" | "all">("pending");
  const q = useQuery({ queryKey: ["flagged", state], queryFn: () => api<{ items: Flagged[]; total: number }>(`/integrity/flagged-attempts?state=${state}`), enabled: can("review.decide") });
  if (!can("review.decide")) return <Card><EmptyState title="Reviewer permission required" description="Only reviewers and administrators resolve flagged attempts." /></Card>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented ariaLabel="Decision state" value={state} onChange={setState}
          options={[{ value: "pending", label: "Pending" }, { value: "resolved", label: "Resolved" }, { value: "all", label: "All" }]} />
        <p className="text-[12.5px] text-fg-muted">Attempts that included a question withdrawn during or after the slot. Official scores are never overwritten; your decision is recorded alongside them.</p>
      </div>
      {q.isError ? <Card><ErrorState error={q.error} /></Card> : q.isLoading ? <Card><LoadingRows /></Card> : !q.data!.items.length ? (
        <Card><EmptyState icon={<ShieldQuestion />} title={state === "pending" ? "No attempts awaiting a decision" : "Nothing here"}
          description="When a question is quarantined, retired or confirmed leaked, affected attempts appear here." /></Card>
      ) : q.data!.items.map((f) => <FlaggedCard key={f.attempt_id} f={f} />)}
    </div>
  );
}

function FlaggedCard({ f }: { f: Flagged }) {
  const qc = useQueryClient();
  const [decision, setDecision] = useState<string>("");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/integrity/attempts/${f.attempt_id}/resolution`, { body: { decision, reason } }),
    onSuccess: () => { toast.success(`Attempt #${f.attempt_id}: ${titleCase(decision)} recorded`); setReason(""); setDecision(""); qc.invalidateQueries({ queryKey: ["flagged"] }); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const submitted = f.status === "submitted";
  return (
    <Card>
      <CardHeader title={<span className="flex flex-wrap items-center gap-2">Attempt #{f.attempt_id} · <Mono>{f.candidate}</Mono> · {f.form}
        <Badge tone={f.decision === "pending" ? "warn" : "ok"}>{f.decision === "pending" ? "Decision pending" : titleCase(f.decision)}</Badge>
        {f.reopened_at && <Badge tone="info">Reopened by new evidence</Badge>}</span>}
        description={`${f.slot} · ${submitted ? `submitted ${fmtDate(f.submitted_at)}` : "still in progress — decide after submission"}`} />
      <CardBody className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-center">
            <div className="rounded-md border border-line p-3"><div className="text-[11.5px] uppercase tracking-wider text-fg-subtle">Official score</div>
              <div className="text-[22px] font-semibold tabular">{f.official_score ?? "—"} / {f.official_max ?? "—"}</div></div>
            <div className="rounded-md border border-line p-3"><div className="text-[11.5px] uppercase tracking-wider text-fg-subtle">Excluding withdrawn</div>
              <div className="text-[22px] font-semibold tabular">{f.alternative_score ?? "—"} / {f.alternative_max ?? "—"}</div></div>
          </div>
          <div>
            <div className="mb-1 text-[12px] font-medium text-fg-muted">Withdrawn questions (evidence)</div>
            <ul className="space-y-1.5 text-[12.5px]">
              {f.items.map((i) => (
                <li key={i.code + i.flagged_at} className="rounded-md bg-surface-2 px-3 py-2">
                  <Mono className="text-fg">{i.code}</Mono> — {i.reason}
                  <div className="text-[11.5px] text-fg-subtle">flagged {fmtDate(i.flagged_at)} while the attempt was {i.attempt_status_when_flagged.replace("_", " ")}{i.released_at ? ` · question later released ${fmtDate(i.released_at)}` : ""}</div>
                </li>))}
            </ul>
          </div>
          {f.resolutions.length > 0 && (
            <div>
              <div className="mb-1 text-[12px] font-medium text-fg-muted">Decision history</div>
              <ul className="space-y-1 text-[12px] text-fg-muted">{f.resolutions.map((r, k) => (
                <li key={k}>{fmtDate(r.at)} · <span className="text-fg">{r.by.name}</span> · {titleCase(r.decision)}{r.final_score != null ? ` → ${r.final_score}/${r.final_max}` : ""} — {r.reason}</li>))}</ul>
            </div>
          )}
        </div>
        <fieldset className="space-y-3" disabled={!submitted || m.isPending}>
          <legend className="mb-1 text-[12.5px] font-medium text-fg-muted">Decision</legend>
          {DECISIONS.map((d) => (
            <label key={d.value} className="flex cursor-pointer items-start gap-2 rounded-md border border-line px-3 py-2 text-[13px] has-[:checked]:border-accent has-[:checked]:bg-accent-soft">
              <input type="radio" name={`dec-${f.attempt_id}`} value={d.value} checked={decision === d.value} onChange={() => setDecision(d.value)} className="mt-1" />
              <span><span className="font-medium text-fg">{d.label}</span><span className="block text-[12px] text-fg-muted">{d.help}</span></span>
            </label>
          ))}
          <div>
            <Label htmlFor={`reason-${f.attempt_id}`}>Reason (required, recorded and audited)</Label>
            <Textarea id={`reason-${f.attempt_id}`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What evidence supports this decision?" />
          </div>
          <Button variant="primary" disabled={!decision || reason.trim().length < 10} loading={m.isPending} onClick={() => m.mutate()}>Record decision</Button>
        </fieldset>
      </CardBody>
    </Card>
  );
}
