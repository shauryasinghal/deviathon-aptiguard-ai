import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, CheckCircle2, Download, Rocket, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { EmptyState, ErrorState, KeyValue, LoadingRows, PageHeader } from "@/components/ui/page";
import { Badge, Card, CardBody, CardHeader, Input, Label, Mono, Switch } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/ui/status";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, fmtDate, titleCase } from "@/lib/utils";

const DEF = { drive: "Campus Drive 2026-Q4 (rerun)", n_slots: 10, quant: 10, logical: 10, verbal: 10, easy: 30, medium: 40, hard: 30,
  max_adjacent_overlap_pct: 10, max_slot_exposures: 3, min_slot_spacing: 2, separate_families_adjacent: true, seed: 107 };

export default function Assembler() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [c, setC] = useState(DEF);
  const runs = useQuery({ queryKey: ["asm-runs"], queryFn: () => api<any[]>("/assembly/runs") });
  const runId = params.get("run") || (runs.data?.find((r) => r.status === "succeeded")?.id?.toString() ?? "");
  const run = useQuery({ queryKey: ["asm-run", runId], queryFn: () => api<any>(`/assembly/runs/${runId}`), enabled: !!runId });
  const [formIdx, setFormIdx] = useState(0);
  useEffect(() => setFormIdx(0), [runId]);
  const body = () => {
    const mix = { easy: c.easy / 100, medium: c.medium / 100, hard: c.hard / 100 };
    return { drive: c.drive, n_slots: c.n_slots, per_section: { QUANT: c.quant, LOGICAL: c.logical, VERBAL: c.verbal },
      difficulty_mix: { QUANT: mix, LOGICAL: mix, VERBAL: mix }, max_adjacent_overlap_pct: c.max_adjacent_overlap_pct,
      max_slot_exposures: c.max_slot_exposures, min_slot_spacing: c.min_slot_spacing, separate_families_adjacent: c.separate_families_adjacent,
      seed: c.seed, start_date: "2026-11-16T04:00:00" };
  };
  const mixOk = c.easy + c.medium + c.hard === 100;
  const gen = useMutation({
    mutationFn: () => api<any>("/assembly/runs", { body: body() }),
    onSuccess: (r) => { r.status === "succeeded" ? toast.success(`Run #${r.id}: ${r.form_count} forms, constraints verified`) : toast.error(`Assembly failed: ${r.diagnostics.explanation}`); setParams({ run: String(r.id) }); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const validate = useMutation({
    mutationFn: () => api<any>("/assembly/validate", { body: body() }),
    onSuccess: (r) => r.feasible_preflight ? toast.success(`Feasible: ${r.eligible_pool} eligible items, ≤${r.allowed_shared_items_adjacent} shared items allowed between adjacent slots`) : toast.error(r.issues[0].reason),
    onError: (e: ApiError) => toast.error(e.message),
  });
  const publish = useMutation({
    mutationFn: () => api<any>(`/assembly/runs/${runId}/publish`, { method: "POST" }),
    onSuccess: (r) => {
      r.blocked?.length
        ? toast.warning(`Published ${r.published}; ${r.blocked.length} form(s) blocked — ${r.blocked[0].items.map((i: any) => `${i.code} (${i.reason})`).join(", ")}`)
        : toast.success(`Published ${r.published} form(s)`);
      qc.invalidateQueries();
    },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const num = (k: keyof typeof DEF, label: string, max = 100) => (
    <div><Label htmlFor={k}>{label}</Label><Input id={k} type="number" min={0} max={max} value={c[k] as number} onChange={(e) => setC({ ...c, [k]: Number(e.target.value) })} /></div>
  );
  const r = run.data;
  const forms = r?.forms ?? [];
  const exportCsv = () => {
    const rows = [["form", "slot", "position", "item", "family", "section", "difficulty"], ...forms.flatMap((f: any) => f.items.map((i: any) => [f.code, f.slot.sequence, i.position, i.code, i.family_code, i.section, i.difficulty]))];
    const blob = new Blob([rows.map((x) => x.join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `manifest-run-${r.id}.csv`; a.click();
  };
  const n = forms.length;
  const ov = (i: number, j: number) => r.overlap.find((o: any) => (o.a === i && o.b === j) || (o.a === j && o.b === i));
  return (
    <div>
      <PageHeader eyebrow="Delivery" title="Test assembler" description="Build distinct, reproducible forms for every slot. Hard constraints are verified after assembly; infeasible plans fail with the bottleneck named." />
      <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
        <Card className="h-fit">
          <CardHeader title="Constraints" icon={<Boxes />} />
          <CardBody className="space-y-3">
            <div><Label htmlFor="drive">Drive name</Label><Input id="drive" value={c.drive} onChange={(e) => setC({ ...c, drive: e.target.value })} /></div>
            <div className="grid grid-cols-2 gap-3">{num("n_slots", "Slots", 30)}{num("seed", "Random seed", 2 ** 31)}</div>
            <div className="grid grid-cols-3 gap-3">{num("quant", "Quant", 60)}{num("logical", "Logical", 60)}{num("verbal", "Verbal", 60)}</div>
            <div className="grid grid-cols-3 gap-3">{num("easy", "Easy %")}{num("medium", "Medium %")}{num("hard", "Hard %")}</div>
            {!mixOk && <p className="text-xs text-danger">Difficulty mix must total 100%.</p>}
            <div className="grid grid-cols-2 gap-3">{num("max_adjacent_overlap_pct", "Max adjacent overlap %")}{num("max_slot_exposures", "Max slot exposures", 50)}</div>
            {num("min_slot_spacing", "Min slots between reuse", 20)}
            <label className="flex items-center justify-between text-[13px]">Separate variant families in adjacent slots<Switch checked={c.separate_families_adjacent} onCheckedChange={(v) => setC({ ...c, separate_families_adjacent: v })} label="Separate families" /></label>
            <div className="flex gap-2 pt-1">
              <Button variant="outline" disabled={!mixOk} loading={validate.isPending} onClick={() => validate.mutate()}>Check feasibility</Button>
              <Button variant="primary" disabled={!mixOk || !can("assembly.run")} loading={gen.isPending} onClick={() => gen.mutate()}>Generate forms</Button>
            </div>
            <p className="text-[11.5px] text-fg-subtle">Only approved items with no suspected/confirmed leak and within exposure limits are eligible. Same seed + same pool ⇒ identical forms.</p>
          </CardBody>
        </Card>
        <div className="space-y-5">
          <Card><CardHeader title="Assembly runs" actions={<Select ariaLabel="Run" value={runId} onChange={(v) => setParams({ run: v })} className="min-w-[280px]"
            options={(runs.data ?? []).map((x) => ({ value: String(x.id), label: `#${x.id} · ${x.drive} · ${x.status}` }))} />} />
            {run.isLoading ? <LoadingRows /> : run.isError ? <ErrorState error={run.error} /> : !r ? <EmptyState title="No runs yet" /> : (
              <CardBody className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  {r.status === "succeeded" ? <Badge tone="ok"><CheckCircle2 className="size-3" />Verified</Badge> : <Badge tone="danger"><XCircle className="size-3" />Failed</Badge>}
                  <span className="text-[13px] text-fg-muted">{r.diagnostics.explanation}</span>
                </div>
                <KeyValue cols={4} items={[["Seed", r.seed], ["Forms", r.form_count], ["Published", r.published], ["Eligible pool", r.diagnostics.pool_size],
                  ["Adjacent overlap limit", `${r.config.max_adjacent_overlap_pct}% (≤${r.diagnostics.allowed_shared_items_adjacent ?? "—"} items)`],
                  ["Backtracks", r.diagnostics.backtracks ?? "—"], ["Created", fmtDate(r.created_at)], ["Duration", `${r.duration_ms} ms`]]} />
                {r.diagnostics.excluded_before_assembly && <p className="text-[12px] text-fg-muted">Excluded before assembly: {Object.entries(r.diagnostics.excluded_before_assembly).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>}
                {r.status === "failed" && (r.diagnostics.infeasible_cells || r.diagnostics.failure) && (
                  <div className="rounded-md border border-danger/30 bg-danger-soft p-3 text-[12.5px]">
                    {(r.diagnostics.infeasible_cells ?? []).map((x: any, i: number) => <div key={i}>• {x.reason}</div>)}
                    {r.diagnostics.failure && <div>Bottleneck: {titleCase(r.diagnostics.failure.bottleneck)} · eliminated: {JSON.stringify(r.diagnostics.failure.eliminated_by)}</div>}
                  </div>
                )}
                {r.status === "succeeded" && r.comparability && (
                  <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-[12.5px]" role="note" aria-label="Form comparability">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <b>Form comparability (advisory)</b>
                      <Badge tone={r.comparability.status === "within_configured_margin" ? "ok" : r.comparability.status === "exceeds_configured_margin" ? "danger" : "warn"}>
                        {titleCase(r.comparability.status)}
                      </Badge>
                    </div>
                    <p className="text-fg-muted">{r.comparability.message}</p>
                    {r.comparability.largest_pairwise_difference && (
                      <p className="mt-1 text-fg-muted">Largest mean-difficulty gap: {r.comparability.largest_pairwise_difference.diff} logits
                        (90% interval {r.comparability.largest_pairwise_difference.ci90.join(" to ")}) between {r.comparability.largest_pairwise_difference.forms.join(" and ")};
                        configured margin ±{r.comparability.margin_logits}.</p>)}
                    <p className="mt-1 text-fg-subtle">{r.comparability.caveat} Equal easy/medium/hard counts are enforced, but that alone is not psychometric equivalence.</p>
                  </div>)}
                {r.status === "succeeded" && <div className="flex gap-2">
                  {can("assembly.run") && <Button size="sm" variant="primary" disabled={!forms.some((f: any) => f.status === "draft")} loading={publish.isPending} onClick={() => publish.mutate()}><Rocket />{forms.some((f: any) => f.status === "draft") ? "Publish draft forms" : "No draft forms"}</Button>}
                  {r.needs_review > 0 && <Badge tone="warn">{r.needs_review} form(s) need reassessment</Badge>}
                  <Button size="sm" variant="outline" onClick={exportCsv}><Download />Export manifests</Button>
                </div>}
              </CardBody>
            )}
          </Card>
          {r?.status === "succeeded" && n > 0 && (
            <>
              <Card><CardHeader title="Overlap matrix" description="Shared items as % of the smaller form (Jaccard on hover). Adjacent pairs are outlined." />
                <CardBody className="overflow-x-auto">
                  <table className="text-[11px]"><tbody>
                    <tr><td />{forms.map((f: any, j: number) => <td key={j} className="px-1 text-center text-fg-subtle">S{f.slot.sequence}</td>)}</tr>
                    {forms.map((fa: any, i: number) => (
                      <tr key={i}><td className="pr-2 text-fg-subtle">S{fa.slot.sequence}</td>
                        {forms.map((_: any, j: number) => {
                          const o = i === j ? null : ov(i, j);
                          const adj = Math.abs(i - j) === 1;
                          return <td key={j} title={o ? `${o.shared} shared · Jaccard ${o.jaccard}` : ""}
                            className={cn("size-9 text-center tabular", i === j ? "bg-accent/40" : o?.shared ? (o.constraint_ok ? "bg-warn-soft text-warn" : "bg-danger-soft text-danger") : "bg-surface-2 text-fg-subtle", adj && "ring-1 ring-inset ring-ok/60")}>
                            {i === j ? "—" : `${o?.smaller_form_pct ?? 0}`}</td>;
                        })}</tr>))}
                  </tbody></table>
                </CardBody></Card>
              <Card><CardHeader title="Per-slot manifest" actions={<Select ariaLabel="Form" value={String(formIdx)} onChange={(v) => setFormIdx(Number(v))} options={forms.map((f: any, i: number) => ({ value: String(i), label: f.code }))} />} />
                {forms[formIdx] && <>
                  {forms[formIdx].status === "needs_review" && (
                    <div className="mx-5 mt-4 rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
                      Blocked for new attempts: {forms[formIdx].validation?.reassessment?.reason}. Re-assemble, or release the item after review.</div>)}
                  {forms[formIdx].flagged_attempts > 0 && (
                    <div className="mx-5 mt-3 rounded-md border border-info/30 bg-info-soft px-3 py-2 text-[12.5px] text-info">
                      {forms[formIdx].flagged_attempts} attempt(s) on this form include a withdrawn item. They were not invalidated: the official
                      score stands and an alternative score excluding the item is recorded for staff review (API: /assembly/forms/{forms[formIdx].id}/attempts).</div>)}
                  <AssignPanel form={forms[formIdx]} canAssign={can("assembly.run")} />
                  <CardBody className="pb-0 text-[12.5px] text-fg-muted">Slot {forms[formIdx].slot.sequence} · {fmtDate(forms[formIdx].slot.starts_at)} · <StatusBadge kind="form" value={forms[formIdx].status} /> · {Object.entries(forms[formIdx].validation.difficulty_distribution).map(([k, v]) => `${k} ${v}`).join(", ")}</CardBody>
                  <Table><THead><tr><Th>#</Th><Th>Item</Th><Th>Family</Th><Th>Variant of</Th><Th>Section</Th><Th>Difficulty</Th><Th className="text-right">Prior slots</Th><Th>Leak</Th></tr></THead>
                    <tbody>{forms[formIdx].items.map((i: any) => (
                      <Tr key={i.position}><Td className="tabular">{i.position}</Td><Td><Mono className="text-fg">{i.code}</Mono></Td><Td><Mono>{i.family_code}</Mono></Td>
                        <Td><Mono className="text-fg-muted">{i.variant_of ?? "source"}</Mono></Td><Td>{i.section}</Td><Td>{i.difficulty}</Td>
                        <Td className="text-right tabular">{i.exposure_slots}</Td><Td><StatusBadge kind="leak" value={i.leak_status} /></Td></Tr>))}</tbody></Table>
                </>}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function AssignPanel({ form, canAssign }: { form: any; canAssign: boolean }) {
  const qc = useQueryClient();
  const [codes, setCodes] = useState("");
  const m = useMutation({
    mutationFn: () => api<any>(`/assembly/forms/${form.id}/assignments`, { body: { candidate_codes: codes.split(/[\s,]+/).filter(Boolean) } }),
    onSuccess: (r) => {
      toast.success(`Assigned ${r.added.length}${r.skipped.length ? `; skipped ${r.skipped.map((x: any) => `${x.code} (${x.reason})`).join(", ")}` : ""}`);
      setCodes(""); qc.invalidateQueries({ queryKey: ["asm-run"] });
    },
    onError: (e: ApiError) => toast.error(e.message + ((e.details as any)?.missing ? `: ${(e.details as any).missing.join(", ")}` : "")),
  });
  return (
    <CardBody className="space-y-2 border-b border-line">
      <div className="text-[12.5px] text-fg-muted">Assigned candidates ({form.assigned_candidates.length}): {form.assigned_candidates.length ? form.assigned_candidates.map((c: string) => <Mono key={c} className="mr-2 text-fg">{c}</Mono>) : "none — candidates can only see forms assigned to them."}</div>
      {canAssign && ["draft", "published"].includes(form.status) && (
        <div className="flex gap-2">
          <Input aria-label="Candidate codes to assign" placeholder="Candidate codes, e.g. DEMO-CAND-03" value={codes} onChange={(e) => setCodes(e.target.value)} className="max-w-sm" />
          <Button size="sm" variant="outline" disabled={!codes.trim()} loading={m.isPending} onClick={() => m.mutate()}>Assign</Button>
        </div>
      )}
    </CardBody>
  );
}
