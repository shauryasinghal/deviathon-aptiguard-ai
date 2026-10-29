import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Play, ShieldAlert } from "lucide-react";
import { useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { axis, C, ChartTooltip } from "@/components/charts/theme";
import { Button } from "@/components/ui/button";
import { Select, Sheet } from "@/components/ui/overlay";
import { DataNotice, EmptyState, ErrorState, FilterBar, KeyValue, LoadingRows, PageHeader } from "@/components/ui/page";
import { Badge, Card, CardBody, CardHeader, Mono, Textarea } from "@/components/ui/primitives";
import { SectionBadge, StatusBadge } from "@/components/ui/status";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtFixed, fmtPct, titleCase } from "@/lib/utils";

export default function Leaks() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [severity, setSeverity] = useState("all");
  const [status, setStatus] = useState("all");
  const [evidence, setEvidence] = useState("all");
  const f = { severity, status, evidence_class: evidence };
  const alerts = useQuery({ queryKey: ["alerts", f], queryFn: () => api<any>(`/leaks/alerts${qs(f)}`) });
  const datasets = useQuery({ queryKey: ["leak-datasets"], queryFn: () => api<any[]>("/leaks/datasets") });
  const runs = useQuery({ queryKey: ["leak-runs"], queryFn: () => api<any[]>("/leaks/runs") });
  const detect = useMutation({
    mutationFn: () => api<any>("/leaks/detect", { body: { replay: true } }),
    onSuccess: (r) => { toast.success(`Detection run #${r.run_id}: ${r.summary.alerts_created} new, ${r.summary.alerts_updated} updated (${r.duration_ms} ms)`); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append("file", file); fd.append("name", file.name); fd.append("source_type", "authorized_export"); return api<any>("/leaks/datasets", { form: fd }); },
    onSuccess: (r) => { toast.success(`Imported ${r.n_records} records (${r.n_duplicates} duplicates, ${r.n_rejected} rejected). Run detection to analyse.`); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const alertId = params.get("alert");
  return (
    <div>
      <PageHeader eyebrow="Integrity" title="Leak detection"
        description="Independent signals: text matches in authorised datasets, ability-adjusted performance drift (Mantel–Haenszel, FDR-controlled) and response-time drops."
        actions={<>
          {can("leaks.import") && <><input ref={fileRef} type="file" accept=".csv,.json,.jsonl" className="hidden" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            <Button variant="outline" loading={upload.isPending} onClick={() => fileRef.current?.click()}><FileUp />Import dataset</Button></>}
          {can("leaks.manage") && <Button variant="primary" loading={detect.isPending} onClick={() => detect.mutate()}><Play />Run detection</Button>}
        </>} />
      <DataNotice>AptiGuard does not monitor Telegram, social media or the internet. It analyses only the datasets imported here. The demo dataset is synthetic with a deliberately injected leak (see data/synthetic/leak_ground_truth.json).</DataNotice>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Imported datasets" />
          <ul className="divide-y divide-line">{(datasets.data ?? []).map((d) => (
            <li key={d.id} className="px-5 py-2.5 text-[13px]"><div className="flex items-center gap-2"><span className="font-medium">{d.name}</span>{d.is_synthetic && <Badge tone="info">synthetic</Badge>}</div>
              <div className="text-[12px] text-fg-muted">{d.n_records} records · {d.n_duplicates} duplicates removed · {d.n_rejected} rejected · sha256 {d.sha256.slice(0, 12)}… · {fmtDate(d.imported_at)}</div></li>))}</ul>
        </Card>
        <Card><CardHeader title="Detection runs" />
          <ul className="divide-y divide-line">{(runs.data ?? []).slice(0, 4).map((r) => (
            <li key={r.id} className="px-5 py-2.5 text-[12.5px] text-fg-muted">#{r.id} · {fmtDate(r.created_at)} · {r.summary.items_scanned} items × {r.summary.records_scanned} records · {r.summary.items_tested_for_drift} drift-tested · {r.duration_ms} ms</li>))}</ul>
        </Card>
      </div>
      <Card className="mt-5">
        <FilterBar>
          <Select ariaLabel="Severity" value={severity} onChange={setSeverity} options={[{ value: "all", label: "All severities" }, ...["critical", "high", "medium", "low"].map((s) => ({ value: s, label: titleCase(s) }))]} />
          <Select ariaLabel="Status" value={status} onChange={setStatus} options={[{ value: "all", label: "All statuses" }, ...["open", "acknowledged", "investigating", "confirmed", "dismissed"].map((s) => ({ value: s, label: titleCase(s) }))]} />
          <Select ariaLabel="Evidence" value={evidence} onChange={setEvidence} className="min-w-[220px]" options={[{ value: "all", label: "All evidence classes" }, ...Object.entries(alerts.data?.evidence_labels ?? {}).map(([k, v]) => ({ value: k, label: v as string }))]} />
        </FilterBar>
        {alerts.isError ? <ErrorState error={alerts.error} /> : alerts.isLoading ? <LoadingRows /> : !alerts.data.items.length ? <EmptyState icon={<ShieldAlert />} title="No alerts match" /> : (
          <Table>
            <THead><tr><Th>Alert</Th><Th>Severity</Th><Th>Item</Th><Th>Evidence class</Th><Th>Signals</Th><Th className="text-right">Score</Th><Th>First detectable</Th><Th>Status</Th></tr></THead>
            <tbody>{alerts.data.items.map((a: any) => (
              <Tr key={a.id} onClick={() => setParams({ alert: String(a.id) })}>
                <Td><Mono className="text-fg">{a.code}</Mono></Td><Td><StatusBadge kind="severity" value={a.severity} /></Td>
                <Td><Mono>{a.question_code}</Mono> <SectionBadge section={a.section} /></Td>
                <Td><StatusBadge kind="evidence" value={a.evidence_class} /></Td>
                <Td className="text-[12px] text-fg-muted">{a.signals.map((s: any) => titleCase(s.signal)).join(" + ")}</Td>
                <Td className="text-right tabular">{Math.round(a.score)}</Td>
                <Td className="text-[12.5px]">{a.first_detectable_slot ? `Slot ${a.first_detectable_slot}` : "—"}</Td>
                <Td><StatusBadge kind="alert" value={a.status} /></Td>
              </Tr>))}</tbody>
          </Table>
        )}
      </Card>
      <AlertSheet id={alertId ? Number(alertId) : null} onClose={() => { params.delete("alert"); setParams(params); }} />
    </div>
  );
}

function AlertSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const q = useQuery({ queryKey: ["alert", id], queryFn: () => api<any>(`/leaks/alerts/${id}`), enabled: id != null });
  const act = useMutation({
    mutationFn: (action: string) => api<any>(`/leaks/alerts/${id}/actions`, { body: { action, note: note || null } }),
    onSuccess: (r) => { toast.success(`${r.code} → ${r.status}`); setNote(""); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const a = q.data;
  const ev = a?.evidence ?? {};
  const perSlot = (ev.performance?.per_slot ?? []).map((s: any) => ({ slot: `S${s.slot_seq}`, p: Math.round(s.p * 1000) / 10 }));
  return (
    <Sheet open={id != null} onOpenChange={(o) => !o && onClose()} width="max-w-3xl"
      title={a ? <span className="flex items-center gap-2"><Mono>{a.code}</Mono><StatusBadge kind="severity" value={a.severity} /><StatusBadge kind="alert" value={a.status} /></span> : "Loading…"}
      description={a?.title}>
      {q.isLoading ? <LoadingRows /> : q.isError ? <ErrorState error={q.error} /> : a && (
        <div className="space-y-5 p-5">
          <div className="whitespace-pre-line rounded-md border border-line bg-surface-2 p-3 text-[13px] text-fg">{a.explanation}</div>
          <KeyValue cols={4} items={[["Evidence class", a.evidence_label], ["Score", Math.round(a.score)], ["Detectable from", a.first_detectable_slot ? `Slot ${a.first_detectable_slot}` : "—"], ["Detected", fmtDate(a.detected_at)]]} />
          {ev.text_matches && <Card><CardHeader title="Text-match evidence (supplied dataset)" />
            <CardBody className="space-y-3">{ev.text_matches.map((m: any) => (
              <div key={m.record_id} className="rounded-md border border-line p-3 text-[12.5px]">
                <div className="mb-1 flex flex-wrap gap-2"><Badge tone="danger">{m.level}</Badge><span className="text-fg-muted">{m.channel} · {m.channel_type} · {m.external_id} · {fmtDate(m.posted_at)}</span>{m.dataset_is_synthetic && <Badge tone="info">synthetic</Badge>}</div>
                <div className="text-fg-muted">containment {fmtFixed(m.containment)} · char-cosine {fmtFixed(m.char_cosine)} · numbers agree {m.number_agreement ?? "n/a"} · {m.reason}</div>
                <blockquote className="mt-2 border-l-2 border-danger/50 pl-3 font-mono text-[12px] text-fg">{m.excerpt}</blockquote>
              </div>))}</CardBody></Card>}
          {ev.family_matches && <Card><CardHeader title="Family-level (template) match — concept exposed, not this exact item" />
            <CardBody className="text-[12.5px] text-fg-muted">{ev.family_matches.map((m: any) => <div key={m.external_id}>{m.channel} {m.external_id}: masked similarity {fmtFixed(m.masked_score)} — “{m.excerpt}”</div>)}</CardBody></Card>}
          {ev.performance && <Card><CardHeader title="Performance evidence (ability-adjusted)" description={ev.performance.test} />
            <CardBody className="space-y-3">
              <KeyValue cols={4} items={[["Baseline p", `${fmtPct(ev.performance.p_baseline, 1)} (n ${ev.performance.n_baseline})`], ["Later p", `${fmtPct(ev.performance.p_later, 1)} (n ${ev.performance.n_later})`],
                ["ETS Δ (class)", `${fmtFixed(ev.performance.ets_delta)} (${ev.performance.ets_class})`], ["q-value (BH)", ev.performance.q_value_bh.toExponential(2)],
                ["Rest score base→later", `${fmtFixed(ev.performance.rest_baseline)} → ${fmtFixed(ev.performance.rest_later)}`],
                ["Median RT", ev.response_time?.median_rt_baseline_ms ? `${Math.round(ev.response_time.median_rt_baseline_ms / 1000)}s → ${Math.round(ev.response_time.median_rt_later_ms / 1000)}s` : "—"],
                ["RT vs slot pace", fmtFixed(ev.response_time?.ratio_vs_slot_pace)], ["RT q-value", ev.response_time?.q_value_bh != null ? Number(ev.response_time.q_value_bh).toExponential(2) : "—"]]} />
              <div className="h-[180px]"><ResponsiveContainer><LineChart data={perSlot} margin={{ left: -16, right: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="slot" {...axis} /><YAxis {...axis} domain={[0, 100]} unit="%" />
                <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} />
                {ev.performance.baseline_slots?.length && <ReferenceLine x={`S${ev.performance.baseline_slots.at(-1)}`} stroke={C.muted} strokeDasharray="4 4" label={{ value: "baseline end", fill: C.muted, fontSize: 10 }} />}
                <Line dataKey="p" name="% correct" stroke={C.danger} strokeWidth={2} dot={{ r: 3 }} /></LineChart></ResponsiveContainer></div>
            </CardBody></Card>}
          {ev.affected_family && <Card><CardHeader title={`Affected family · ${ev.affected_family.family_code}`} description={ev.affected_family.concept} />
            <CardBody className="flex flex-wrap gap-1.5">{ev.affected_family.siblings.map((s: any) => <Badge key={s.code} tone={s.leak_status === "none" ? "neutral" : "warn"}>{s.code} · {s.status}</Badge>)}</CardBody></Card>}
          <Card><CardHeader title="Investigation" description={a.recommended_action} />
            <CardBody className="space-y-3">
              <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Investigation note (≥10 characters to confirm or dismiss)" aria-label="Investigation note" />
              {can("leaks.manage") ? <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={a.status !== "open"} onClick={() => act.mutate("acknowledge")}>Acknowledge</Button>
                <Button size="sm" variant="outline" disabled={!["open", "acknowledged"].includes(a.status)} onClick={() => act.mutate("investigate")}>Investigate</Button>
                <Button size="sm" variant="danger" disabled={["confirmed", "dismissed"].includes(a.status)} onClick={() => act.mutate("confirm")}>Confirm leak & quarantine</Button>
                <Button size="sm" variant="secondary" disabled={["confirmed", "dismissed"].includes(a.status)} onClick={() => act.mutate("dismiss")}>Dismiss</Button>
                {["confirmed", "dismissed"].includes(a.status) && <Button size="sm" variant="ghost" onClick={() => act.mutate("reopen")}>Reopen</Button>}
              </div> : <p className="text-[12px] text-fg-subtle">Read-only for your role.</p>}
              {a.reviewer_decision && <p className="text-[12.5px]">Decision by {a.reviewer?.name}: {a.reviewer_decision}</p>}
              <ul className="space-y-1 text-[12px] text-fg-muted">{a.investigation?.events.map((e: any, i: number) => <li key={i}>{fmtDate(e.at)} · {e.by} · {e.action} ({e.from} → {e.to}){e.note ? ` — ${e.note}` : ""}</li>)}</ul>
            </CardBody></Card>
        </div>
      )}
    </Sheet>
  );
}
