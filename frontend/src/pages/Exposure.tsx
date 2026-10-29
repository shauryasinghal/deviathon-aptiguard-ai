import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Radar, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { axis, C, ChartTooltip, Legend } from "@/components/charts/theme";
import { QuestionDrawer } from "@/features/questions";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { ErrorState, FilterBar, LoadingRows, PageHeader, Pagination, StatCard } from "@/components/ui/page";
import { Card, CardBody, CardHeader, Input, Label, Mono, Progress } from "@/components/ui/primitives";
import { SectionBadge, StatusBadge } from "@/components/ui/status";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtInt, SECTION_LABEL } from "@/lib/utils";

export default function Exposure() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [section, setSection] = useState("all");
  const [level, setLevel] = useState("all");
  const [sort, setSort] = useState("risk");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const f = { section, level, sort, page, page_size: 25 };
  const items = useQuery({ queryKey: ["exposure", f], queryFn: () => api<any>(`/exposure/items${qs(f)}`), placeholderData: keepPreviousData });
  const tl = useQuery({ queryKey: ["exposure-tl"], queryFn: () => api<any>("/exposure/timeline") });
  const pol = items.data?.policy;
  const [draft, setDraft] = useState<any>(null);
  useEffect(() => { if (pol && !draft) setDraft(pol); }, [pol, draft]);
  const save = useMutation({
    mutationFn: () => api("/exposure/policy", { method: "PUT", body: { max_slot_exposures: Number(draft.max_slot_exposures), max_candidate_exposures: Number(draft.max_candidate_exposures), min_slot_spacing: Number(draft.min_slot_spacing) } }),
    onSuccess: () => { toast.success("Exposure policy updated"); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const drives: string[] = tl.data?.drives ?? [];
  const timeline = (tl.data?.slots ?? []).filter((s: any) => s.items_exposed > 0)
    .map((s: any) => ({ ...s, label: `D${drives.indexOf(s.drive) + 1}·S${s.sequence}` }));
  return (
    <div>
      <PageHeader eyebrow="Integrity" title="Exposure intelligence" description="How often each item has been seen, by how many candidates, and how risky it is to use again." />
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="High risk" value={items.data?.levels?.high ?? "—"} tone="danger" icon={<Radar />} onClick={() => { setLevel("high"); setPage(1); }} />
        <StatCard label="Elevated" value={items.data?.levels?.elevated ?? "—"} tone="warn" onClick={() => { setLevel("elevated"); setPage(1); }} />
        <StatCard label="Low" value={items.data?.levels?.low ?? "—"} tone="ok" onClick={() => { setLevel("low"); setPage(1); }} />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Exposure timeline" description={`Items administered per slot — first exposure vs. reuse. ${drives.map((d, i) => `D${i + 1} = ${d}`).join("; ")}`} />
          <CardBody>
            {tl.isLoading ? <LoadingRows /> : <div className="h-[220px]"><ResponsiveContainer>
              <BarChart data={timeline} margin={{ left: -16, right: 8 }}>
                <CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="label" {...axis} interval={0} fontSize={10} /><YAxis {...axis} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(127,135,160,0.08)" }} />
                <Bar dataKey="new_items" name="New items" stackId="a" fill={C.accent} /><Bar dataKey="reused_items" name="Reused items" stackId="a" fill={C.danger} />
              </BarChart></ResponsiveContainer></div>}
            <Legend items={[{ label: "New items", color: C.accent }, { label: "Reused items", color: C.danger }]} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Exposure policy" description="Used by the assembler to exclude items" />
          {draft && <CardBody className="space-y-3">
            {[["max_slot_exposures", "Max slots per item"], ["max_candidate_exposures", "Max candidates per item"], ["min_slot_spacing", "Min slot gap before reuse"]].map(([k, l]) => (
              <div key={k}><Label htmlFor={k}>{l}</Label><Input id={k} type="number" min={0} value={draft[k]} disabled={!can("exposure.manage")} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} /></div>
            ))}
            <p className="text-[12px] text-fg-subtle">Items with leak status {pol.exclude_leak_statuses.join(" / ")} are always excluded.</p>
            {can("exposure.manage") && <Button variant="primary" size="sm" loading={save.isPending} onClick={() => save.mutate()}><Save />Save policy</Button>}
          </CardBody>}
        </Card>
      </div>
      <Card className="mt-5">
        <FilterBar>
          <Select ariaLabel="Section" value={section} onChange={(v) => { setSection(v); setPage(1); }} options={[{ value: "all", label: "All sections" }, ...["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))]} />
          <Select ariaLabel="Risk level" value={level} onChange={(v) => { setLevel(v); setPage(1); }} options={[{ value: "all", label: "All risk levels" }, { value: "high", label: "High" }, { value: "elevated", label: "Elevated" }, { value: "low", label: "Low" }]} />
          <Select ariaLabel="Sort" value={sort} onChange={setSort} options={[{ value: "risk", label: "Sort: risk" }, { value: "slots", label: "Sort: slots used" }, { value: "candidates", label: "Sort: candidates" }, { value: "recent", label: "Sort: recently used" }]} />
          <span className="ml-auto text-[12px] text-fg-subtle">Click a row to quarantine, retire or inspect the risk explanation.</span>
        </FilterBar>
        {items.isError ? <ErrorState error={items.error} /> : items.isLoading ? <LoadingRows rows={8} /> : (
          <Table>
            <THead><tr><Th>Item</Th><Th>Section</Th><Th>Status</Th><Th>Leak</Th><Th className="text-right">Slots</Th><Th className="text-right">Candidates</Th><Th>Last used</Th><Th className="w-48">Risk</Th><Th>Why</Th></tr></THead>
            <tbody>{items.data.items.map((i: any) => (
              <Tr key={i.id} onClick={() => setOpen(i.id)}>
                <Td><Mono className="text-fg">{i.code}</Mono></Td><Td><SectionBadge section={i.section} /></Td>
                <Td><StatusBadge kind="question" value={i.status} /></Td><Td><StatusBadge kind="leak" value={i.leak_status} /></Td>
                <Td className="text-right tabular">{i.exposure_slots}</Td><Td className="text-right tabular">{fmtInt(i.candidate_exposures)}</Td>
                <Td className="text-[12px] text-fg-muted">{fmtDate(i.last_used_at, false)}</Td>
                <Td><div className="flex items-center gap-2"><Progress value={i.risk.score} tone={i.risk.level === "high" ? "danger" : i.risk.level === "elevated" ? "warn" : "ok"} /><span className="w-8 text-right tabular text-[12px]">{Math.round(i.risk.score)}</span></div></Td>
                <Td className="max-w-[260px] truncate text-[12px] text-fg-muted">{i.risk.components.filter((c: any) => c.points > 0).map((c: any) => c.detail).join(" · ") || "Never administered"}</Td>
              </Tr>))}</tbody>
          </Table>
        )}
        {items.data && <Pagination page={page} pageSize={25} total={items.data.total} onPage={setPage} />}
      </Card>
      <QuestionDrawer id={open} onOpenChange={(o) => !o && setOpen(null)} />
    </div>
  );
}
