import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, CheckCircle2, CircleSlash, Info, ShieldBan, Sparkles, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, Sheet, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { ErrorState, KeyValue, LoadingRows } from "@/components/ui/page";
import { Badge, Label, Mono, Progress, Textarea } from "@/components/ui/primitives";
import { DifficultyPill, SectionBadge, StatusBadge } from "@/components/ui/status";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, fmtDate, fmtFixed, fmtPct, fmtSigned, titleCase } from "@/lib/utils";

export type Option = { key: string; text: string; is_correct: boolean | null; rationale?: string | null };
export type Check = { check: string; status: "pass" | "warn" | "fail"; severity: string; message: string; details?: any };

export function OptionList({ options, compareTo }: { options: Option[]; compareTo?: Option[] }) {
  return (
    <ol className="space-y-1.5">
      {options.map((o) => (
        <li key={o.key} className={cn("flex items-start gap-2.5 rounded-md border px-3 py-2 text-[13.5px]",
          o.is_correct ? "border-ok/40 bg-ok-soft" : "border-line bg-surface-2")}>
          <span className={cn("mt-px grid size-5 shrink-0 place-items-center rounded font-mono text-[11px] font-semibold",
            o.is_correct ? "bg-ok text-[#04130d]" : "bg-surface-3 text-fg-muted")}>{o.key}</span>
          <span className="flex-1 text-fg">{o.text}</span>
          {o.is_correct && <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-label="Correct answer" />}
          {o.rationale && !o.is_correct && <span className="hidden max-w-[45%] text-right text-[11.5px] text-fg-subtle md:block">{o.rationale}</span>}
          {compareTo && compareTo.find((c) => c.key === o.key)?.text !== o.text && <span className="sr-only">changed</span>}
        </li>
      ))}
    </ol>
  );
}

export function ValidationList({ checks, compact }: { checks: Check[]; compact?: boolean }) {
  if (!checks?.length) return <p className="text-[13px] text-fg-muted">Validation has not been run.</p>;
  const order = { fail: 0, warn: 1, pass: 2 } as const;
  return (
    <ul className="space-y-1.5">
      {[...checks].sort((a, b) => order[a.status] - order[b.status]).map((c, i) => (
        <li key={i} className={cn("flex items-start gap-2 rounded-md px-2.5 py-1.5 text-[12.5px]",
          c.status === "fail" ? "bg-danger-soft" : c.status === "warn" ? "bg-warn-soft" : compact ? "" : "bg-surface-2")}>
          {c.status === "pass" ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-ok" /> : c.status === "warn" ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-danger" />}
          <span className="min-w-0">
            <span className="font-mono text-[11px] uppercase tracking-wide text-fg-subtle">{c.check.replace(/_/g, " ")}</span>
            <span className="block text-fg">{c.message}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ItemCard({ q, title, actions, highlight }: { q: any; title?: ReactNode; actions?: ReactNode; highlight?: boolean }) {
  return (
    <div className={cn("rounded-lg border bg-surface", highlight ? "border-accent/40" : "border-line")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="text-[11.5px] font-medium uppercase tracking-wider text-fg-subtle">{title}</span>
        <Mono className="text-fg">{q.code}</Mono>
        <SectionBadge section={q.section} />
        <DifficultyPill value={q.difficulty_target} />
        <span className="flex-1" />
        <StatusBadge kind="validation" value={q.validation_status} />
        <StatusBadge kind="question" value={q.status} />
        {actions}
      </div>
      <div className="space-y-3 p-4">
        <p className="prose-item text-fg">{q.stem}</p>
        <OptionList options={q.options} />
        {q.explanation && <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-[12.5px] text-fg-muted"><span className="font-medium text-fg">Explanation · </span>{q.explanation}</div>}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-fg-subtle">
          <span>Method: {titleCase(q.generation_method)}{q.template_id ? ` · ${q.template_id} v${q.template_version ?? ""}` : ""}</span>
          <span>Skill: {q.skill}</span><span>v{q.version}</span>
          {q.is_synthetic && <span>Synthetic demo item</span>}
        </div>
      </div>
    </div>
  );
}

function StateDialog({ q, action, open, onOpenChange }: { q: any; action: "quarantine" | "retire" | "release"; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [reason, setReason] = useState("");
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api(`/exposure/items/${q.id}/${action}`, { body: { reason } }),
    onSuccess: () => { toast.success(`${q.code}: ${action} recorded`); qc.invalidateQueries(); onOpenChange(false); setReason(""); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={`${titleCase(action)} ${q.code}`}
      description={action === "release" ? "Return this item to the eligible pool." : "The item will be excluded from any new assessment form."}
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant={action === "release" ? "primary" : "danger"} disabled={reason.trim().length < 5} loading={m.isPending} onClick={() => m.mutate()}>Confirm</Button></>}>
      <Label htmlFor="reason">Reason (recorded in the audit log)</Label>
      <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Appeared in a forum thread under investigation" />
      {reason.length > 0 && reason.trim().length < 5 && <p className="mt-1 text-xs text-danger">At least 5 characters.</p>}
    </Dialog>
  );
}

export function QuestionDrawer({ id, onOpenChange }: { id: number | null; onOpenChange: (o: boolean) => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["question", id], queryFn: () => api<any>(`/questions/${id}`), enabled: id != null });
  const [stateAction, setStateAction] = useState<null | "quarantine" | "retire" | "release">(null);
  const archive = useMutation({
    mutationFn: () => api(`/questions/${id}/archive`, { method: "POST" }),
    onSuccess: () => { toast.success("Item archived"); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const d = q.data;
  return (
    <Sheet open={id != null} onOpenChange={onOpenChange} width="max-w-3xl"
      title={d ? <span className="flex items-center gap-2"><Mono>{d.code}</Mono><SectionBadge section={d.section} /></span> : "Loading…"}
      description={d ? `${d.concept} · family ${d.family_code}` : undefined}>
      {q.isLoading && <LoadingRows rows={10} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && (
        <div className="space-y-5 p-5">
          <div className="flex flex-wrap gap-2">
            {can("variants.generate") && d.status !== "archived" && <Button size="sm" variant="primary" asChild><Link to={`/variants?source=${d.parent_id ?? d.id}`}><Sparkles />Generate variants</Link></Button>}
            {can("exposure.manage") && ["approved", "pending_review"].includes(d.status) && <Button size="sm" variant="outline" onClick={() => setStateAction("quarantine")}><ShieldBan />Quarantine</Button>}
            {can("exposure.manage") && ["approved", "quarantined"].includes(d.status) && <Button size="sm" variant="outline" onClick={() => setStateAction("retire")}><CircleSlash />Retire</Button>}
            {can("exposure.manage") && d.status === "quarantined" && <Button size="sm" variant="outline" onClick={() => setStateAction("release")}>Release to pool</Button>}
            {can("questions.write") && d.status !== "archived" && <Button size="sm" variant="ghost" loading={archive.isPending} onClick={() => archive.mutate()}><Archive />Archive</Button>}
            {stateAction && <StateDialog q={d} action={stateAction} open onOpenChange={(o) => !o && setStateAction(null)} />}
          </div>
          <Tabs defaultValue="item">
            <TabsList>
              <TabsTrigger value="item">Item</TabsTrigger>
              <TabsTrigger value="integrity">Exposure & leaks</TabsTrigger>
              <TabsTrigger value="calibration">Calibration</TabsTrigger>
              <TabsTrigger value="family">Family ({d.family.length})</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
            <TabsContent value="item" className="mt-4 space-y-4">
              <ItemCard q={d} title={d.is_source ? "Source" : "Variant"} />
              {d.status_reason && <div className="flex items-start gap-2 rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-warn"><Info className="mt-0.5 size-3.5" />{d.status_reason}</div>}
              <div><h4 className="mb-2 text-[13px] font-semibold">Validation</h4><ValidationList checks={d.validation} /></div>
              <KeyValue cols={3} items={[["Created", fmtDate(d.created_at)], ["Created by", d.created_by?.name ?? "—"],
                ["Approved", d.approved_at ? `${fmtDate(d.approved_at)} · ${d.approved_by?.name ?? ""}` : "—"]]} />
            </TabsContent>
            <TabsContent value="integrity" className="mt-4 space-y-4">
              <KeyValue cols={4} items={[["Slots used", d.exposure.slot_count], ["Candidates", d.exposure.candidate_exposures],
                ["Responses", d.exposure.response_count], ["Last used", fmtDate(d.exposure.last_used_at)]]} />
              <div className="rounded-lg border border-line p-4">
                <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-semibold">Exposure-risk score</span>
                  <StatusBadge kind="risk" value={d.exposure.risk.level} /></div>
                <div className="flex items-center gap-3"><Progress value={d.exposure.risk.score} tone={d.exposure.risk.level === "high" ? "danger" : d.exposure.risk.level === "elevated" ? "warn" : "ok"} />
                  <span className="w-10 text-right font-semibold tabular">{Math.round(d.exposure.risk.score)}</span></div>
                <ul className="mt-3 space-y-1 text-[12.5px] text-fg-muted">
                  {d.exposure.risk.components.map((c: any) => <li key={c.factor} className="flex justify-between"><span>{c.detail}</span><span className="tabular">+{c.points}</span></li>)}
                </ul>
              </div>
              {d.exposure.slots.length > 0 && <div className="flex flex-wrap gap-1">{d.exposure.slots.map((s: string) => <Badge key={s}>{s}</Badge>)}</div>}
              <div className="flex items-center gap-2 text-[13px]">Leak status: <StatusBadge kind="leak" value={d.leak_status} /></div>
              {d.alerts.map((a: any) => (
                <Link key={a.id} to={`/leaks?alert=${a.id}`} className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-[13px] hover:bg-surface-2">
                  <StatusBadge kind="severity" value={a.severity} /><Mono>{a.code}</Mono><span className="truncate text-fg-muted">{a.title}</span><StatusBadge kind="alert" value={a.status} className="ml-auto" />
                </Link>
              ))}
            </TabsContent>
            <TabsContent value="calibration" className="mt-4">
              {!d.calibration ? <p className="text-[13px] text-fg-muted">No response data for this item yet — status: pending calibration. Pilot it before operational use.</p> : (
                <div className="space-y-4">
                  <div className="flex items-center gap-2"><StatusBadge kind="calibration" value={d.calibration.status} /><span className="text-[12px] text-fg-subtle">Run {fmtDate(d.calibration.run_at)}</span></div>
                  <KeyValue cols={4} items={[["Valid responses", d.calibration.n], ["p (correct)", fmtPct(d.calibration.p, 1)],
                    ["95% CI", d.calibration.p_ci[0] != null ? `${fmtPct(d.calibration.p_ci[0], 1)} – ${fmtPct(d.calibration.p_ci[1], 1)}` : "—"],
                    ["Item–rest r", fmtFixed(d.calibration.item_rest_r)], ["Rasch b", fmtFixed(d.calibration.rasch_b)], ["SE(b)", fmtFixed(d.calibration.rasch_se)],
                    ["Δ vs source", fmtSigned(d.calibration.diff_from_reference)],
                    ["90% CI of Δ", d.calibration.diff_ci[0] != null ? `${fmtSigned(d.calibration.diff_ci[0])} … ${fmtSigned(d.calibration.diff_ci[1])}` : "—"]]} />
                  <p className="text-[13px] text-fg">{d.calibration.recommended_action}</p>
                  {d.calibration.warnings?.map((w: string) => <p key={w} className="flex items-start gap-1.5 text-[12.5px] text-warn"><AlertTriangle className="mt-0.5 size-3.5" />{w}</p>)}
                </div>
              )}
            </TabsContent>
            <TabsContent value="family" className="mt-4">
              <ul className="divide-y divide-line rounded-lg border border-line">
                {d.family.map((m: any) => (
                  <li key={m.id} className={cn("flex items-center gap-3 px-3 py-2 text-[13px]", m.id === d.id && "bg-accent-soft")}>
                    <Mono className="w-40 shrink-0">{m.code}</Mono>
                    <span className="flex-1 truncate text-fg-muted">{m.stem}</span>
                    <StatusBadge kind="leak" value={m.leak_status} />
                    <StatusBadge kind="question" value={m.status} />
                  </li>
                ))}
              </ul>
            </TabsContent>
            <TabsContent value="history" className="mt-4">
              <ol className="relative space-y-4 border-l border-line pl-5">
                {[...d.history.revisions.map((r: any) => ({ ...r, kind: "rev" })), ...d.history.decisions.map((x: any) => ({ ...x, kind: "dec" }))]
                  .sort((a, b) => (a.at < b.at ? 1 : -1)).map((h: any, i: number) => (
                    <li key={i}>
                      <span className={cn("absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-surface", h.kind === "dec" ? "bg-ok" : "bg-accent")} />
                      <div className="text-[13px] text-fg">{h.kind === "dec" ? <>Decision: <b>{titleCase(h.decision)}</b></> : <>{titleCase(h.change_type)} · v{h.version}</>}</div>
                      <div className="text-[12px] text-fg-muted">{h.note ?? h.comment ?? ""}</div>
                      <div className="text-[11px] text-fg-subtle">{h.by?.name ?? "system"} · {fmtDate(h.at)}</div>
                    </li>
                  ))}
              </ol>
            </TabsContent>
          </Tabs>
        </div>
      )}
    </Sheet>
  );
}
