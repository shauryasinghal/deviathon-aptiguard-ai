import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, FlaskConical, Play } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { DataNotice, ErrorState, FilterBar, KeyValue, LoadingRows, PageHeader, Pagination, StatCard } from "@/components/ui/page";
import { Card, CardBody, CardHeader, Mono } from "@/components/ui/primitives";
import { SectionBadge, StatusBadge } from "@/components/ui/status";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError, download, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtFixed, fmtInt, fmtPct, fmtSigned, SECTION_LABEL, titleCase } from "@/lib/utils";

const STATUSES = ["within_tolerance", "outside_tolerance", "requires_review", "insufficient_data", "calibrated_reference"];

export default function Calibration() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [section, setSection] = useState("all");
  const [status, setStatus] = useState("all");
  const [variantsOnly, setVariantsOnly] = useState(true);
  const [page, setPage] = useState(1);
  const latest = useQuery({ queryKey: ["cal-latest"], queryFn: () => api<any>("/calibration/runs/latest") });
  const f = { section, status, variants_only: variantsOnly || undefined, page, page_size: 50, sort: "code" };
  const items = useQuery({ queryKey: ["cal-items", f], queryFn: () => api<any>(`/calibration/items${qs(f)}`), placeholderData: keepPreviousData });
  const run = useMutation({
    mutationFn: () => api<any>("/calibration/runs", { body: {} }),
    onSuccess: (r) => { toast.success(`Calibration run #${r.id} complete (${r.method})`); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const r = latest.data;
  return (
    <div>
      <PageHeader eyebrow="Integrity" title="Calibration lab"
        description="Observed CTT statistics for every item with responses, Rasch difficulty when the design is linked, and equivalence decisions with explicit uncertainty."
        actions={<>
          <Button variant="outline" onClick={() => download(`/reports/calibration.csv${qs({ section })}`, "calibration.csv").catch((e) => toast.error(e.message))}><Download />Report CSV</Button>
          <Button variant="outline" onClick={() => download(`/reports/calibration.pdf${qs({ section })}`, "calibration.pdf").catch((e) => toast.error(e.message))}><Download />PDF</Button>
          {can("calibration.run") && <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}><Play />Run calibration</Button>}
        </>} />
      {latest.isError ? <Card><ErrorState error={latest.error} /></Card> : !r ? <Card><LoadingRows /></Card> : (
        <>
          <DataNotice>Data source: {r.data_source}. Raw p-values are observed statistics; Rasch b values are model estimates. Differences in raw scores between groups are confounded by ability.</DataNotice>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatCard label="Responses" value={fmtInt(r.n_responses)} icon={<FlaskConical />} />
            <StatCard label="Items with data" value={fmtInt(r.n_items)} />
            <StatCard label="Within tolerance" value={r.status_counts.within_tolerance ?? 0} tone="ok" />
            <StatCard label="Requires review" value={(r.status_counts.requires_review ?? 0) + (r.status_counts.outside_tolerance ?? 0)} tone="warn" />
            <StatCard label="Insufficient / pending" value={(r.status_counts.insufficient_data ?? 0) + (r.status_counts.pending_calibration ?? 0)} />
          </div>
          <Card className="mt-5">
            <CardHeader title={`Run #${r.id} · ${r.method}`} description={`${fmtDate(r.created_at)} · ${r.n_persons} candidates`} />
            <CardBody className="space-y-3">
              <KeyValue cols={4} items={[["Min responses", r.params.min_responses], ["Rasch floor", r.params.min_responses_rasch],
                ["Tolerance (logits)", `±${r.params.tolerance_logits}`], ["Rasch converged", r.summary?.rasch ? `${r.summary.rasch.converged ? "yes" : "no"} (${r.summary.rasch.iterations} it.)` : "not fitted"]]} />
              {r.warnings.map((w: string) => <p key={w} className="flex items-start gap-1.5 text-[12.5px] text-warn"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{w}</p>)}
            </CardBody>
          </Card>
        </>
      )}
      <Card className="mt-5">
        <FilterBar>
          <Select ariaLabel="Section" value={section} onChange={(v) => { setSection(v); setPage(1); }} options={[{ value: "all", label: "All sections" }, ...["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))]} />
          <Select ariaLabel="Status" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={[{ value: "all", label: "All statuses" }, ...STATUSES.map((s) => ({ value: s, label: titleCase(s) }))]} />
          <label className="flex items-center gap-2 text-[13px] text-fg-muted"><input type="checkbox" checked={variantsOnly} onChange={(e) => { setVariantsOnly(e.target.checked); setPage(1); }} />Variants only (compared with source)</label>
        </FilterBar>
        {items.isError ? <ErrorState error={items.error} /> : items.isLoading ? <LoadingRows rows={10} /> : (
          <Table>
            <THead><tr><Th>Item</Th><Th>Section</Th><Th>Reference</Th><Th className="text-right">n</Th><Th className="text-right">p (95% CI)</Th>
              <Th className="text-right">Item–rest r</Th><Th className="text-right">Rasch b ± SE</Th><Th className="text-right">Δ vs source (90% CI)</Th><Th>Status</Th><Th>Action</Th></tr></THead>
            <tbody>
              {items.data.items.map((i: any) => (
                <Tr key={i.question_id}>
                  <Td><Mono className="text-fg">{i.code}</Mono>{i.leak_status !== "none" && <div><StatusBadge kind="leak" value={i.leak_status} /></div>}</Td>
                  <Td><SectionBadge section={i.section} /></Td>
                  <Td><Mono className="text-fg-muted">{i.reference_code ?? "—"}</Mono></Td>
                  <Td className="text-right tabular">{i.n_valid}{i.n_valid < (r?.params?.min_responses ?? 60) && <AlertTriangle className="ml-1 inline size-3.5 text-warn" aria-label="Small sample" />}</Td>
                  <Td className="text-right tabular text-[12.5px]">{fmtPct(i.p, 0)} <span className="text-fg-subtle">({fmtPct(i.p_ci[0], 0)}–{fmtPct(i.p_ci[1], 0)})</span></Td>
                  <Td className="text-right tabular">{fmtFixed(i.item_rest_r)}</Td>
                  <Td className="text-right tabular text-[12.5px]">{i.rasch_b == null ? "—" : `${fmtFixed(i.rasch_b)} ± ${fmtFixed(i.rasch_se)}`}</Td>
                  <Td className="text-right tabular text-[12.5px]">{i.diff == null ? "—" : <>{fmtSigned(i.diff)} <span className="text-fg-subtle">[{fmtSigned(i.diff_ci[0])}, {fmtSigned(i.diff_ci[1])}]</span>{i.diff_basis === "ctt_p_preliminary" && <div className="text-[10.5px] text-warn">preliminary (p)</div>}</>}</Td>
                  <Td><StatusBadge kind="calibration" value={i.status} /></Td>
                  <Td className="max-w-[260px] text-[12px] text-fg-muted">{i.recommended_action}{i.warnings?.length > 0 && <div className="text-warn">{i.warnings[0]}</div>}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
        {items.data && <Pagination page={page} pageSize={50} total={items.data.total} onPage={setPage} />}
      </Card>
    </div>
  );
}
