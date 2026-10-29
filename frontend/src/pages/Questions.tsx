import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Plus, Search, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { QuestionDrawer } from "@/features/questions";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { EmptyState, ErrorState, FilterBar, LoadingRows, PageHeader, Pagination } from "@/components/ui/page";
import { Badge, Card, FieldError, Input, Label, Mono, Textarea } from "@/components/ui/primitives";
import { DifficultyPill, SectionBadge, StatusBadge } from "@/components/ui/status";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtInt, SECTION_LABEL, timeAgo, titleCase } from "@/lib/utils";

const STATUS = ["approved", "pending_review", "rejected", "quarantined", "retired", "archived"];

export default function Questions() {
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [section, setSection] = useState("all");
  const [status, setStatus] = useState(params.get("status") ?? "all");
  const [difficulty, setDifficulty] = useState("all");
  const [leak, setLeak] = useState("all");
  const [sourceOnly, setSourceOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(params.get("open") ? Number(params.get("open")) : null);
  const [creating, setCreating] = useState(false);
  const [bulk, setBulk] = useState<null | "archive" | "submit_for_review">(null);

  useEffect(() => { const t = setTimeout(() => { setDebounced(search); setPage(1); }, 250); return () => clearTimeout(t); }, [search]);
  useEffect(() => { const o = params.get("open"); if (o) setOpenId(Number(o)); }, [params]);
  const filters = { q: debounced, section, status, difficulty, leak_status: leak, source_only: sourceOnly || undefined, page, page_size: 25 };
  const q = useQuery({ queryKey: ["questions", filters], queryFn: () => api<any>(`/questions${qs(filters)}`), placeholderData: keepPreviousData });

  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allOnPage = q.data?.items.every((i: any) => selected.has(i.id));

  return (
    <div>
      <PageHeader eyebrow="Content" title="Question bank" description="Source items and their parallel variants across quantitative, logical and verbal sections."
        actions={can("questions.write") && <Button variant="primary" onClick={() => setCreating(true)}><Plus />New source question</Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        {Object.entries(q.data?.status_counts ?? {}).map(([k, v]) => (
          <button key={k} onClick={() => { setStatus(status === k ? "all" : k); setPage(1); }} aria-pressed={status === k}>
            <Badge tone={status === k ? "accent" : "neutral"}>{titleCase(k)} · {fmtInt(v as number)}</Badge>
          </button>
        ))}
      </div>
      <Card>
        <FilterBar>
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-fg-subtle" />
            <Input aria-label="Search questions" placeholder="Search code, stem or skill…" className="pl-8" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select ariaLabel="Section" value={section} onChange={(v) => { setSection(v); setPage(1); }} options={[{ value: "all", label: "All sections" }, ...["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))]} />
          <Select ariaLabel="Status" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={[{ value: "all", label: "Active statuses" }, ...STATUS.map((s) => ({ value: s, label: titleCase(s) }))]} />
          <Select ariaLabel="Difficulty" value={difficulty} onChange={(v) => { setDifficulty(v); setPage(1); }} options={[{ value: "all", label: "Any difficulty" }, ...["easy", "medium", "hard"].map((s) => ({ value: s, label: titleCase(s) }))]} />
          <Select ariaLabel="Leak status" value={leak} onChange={(v) => { setLeak(v); setPage(1); }} options={[{ value: "all", label: "Any leak status" }, ...["none", "suspected", "confirmed", "cleared"].map((s) => ({ value: s, label: titleCase(s) }))]} />
          <label className="flex items-center gap-2 text-[13px] text-fg-muted"><input type="checkbox" checked={sourceOnly} onChange={(e) => { setSourceOnly(e.target.checked); setPage(1); }} className="accent-[var(--ag-accent)]" />Sources only</label>
          {selected.size > 0 && can("questions.write") && (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-[13px] text-fg-muted">{selected.size} selected</span>
              <Button size="sm" variant="outline" onClick={() => setBulk("submit_for_review")}><Send />Submit for review</Button>
              <Button size="sm" variant="outline" onClick={() => setBulk("archive")}><Archive />Archive</Button>
            </div>
          )}
        </FilterBar>
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : q.isLoading ? <LoadingRows rows={10} /> : !q.data.items.length ? (
          <EmptyState title="No questions match these filters" description="Clear a filter or search for a different code." />
        ) : (
          <Table>
            <THead><tr>
              {can("questions.write") && <Th className="w-8"><input type="checkbox" aria-label="Select page" checked={!!allOnPage}
                onChange={() => setSelected((s) => { const n = new Set(s); q.data.items.forEach((i: any) => (allOnPage ? n.delete(i.id) : n.add(i.id))); return n; })} /></Th>}
              <Th>Code</Th><Th>Section</Th><Th className="min-w-[280px]">Stem</Th><Th>Difficulty</Th><Th>Status</Th><Th>Validation</Th>
              <Th className="text-right">Exposure</Th><Th>Leak</Th><Th>Updated</Th>
            </tr></THead>
            <tbody>
              {q.data.items.map((i: any) => (
                <Tr key={i.id} onClick={() => setOpenId(i.id)}>
                  {can("questions.write") && <Td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${i.code}`} checked={selected.has(i.id)} onChange={() => toggle(i.id)} /></Td>}
                  <Td><Mono className="text-fg">{i.code}</Mono>{i.is_source && <Badge tone="accent" className="ml-1.5">source</Badge>}</Td>
                  <Td><SectionBadge section={i.section} /></Td>
                  <Td className="max-w-[420px]"><span className="line-clamp-2 text-[13px] text-fg-muted">{i.stem}</span></Td>
                  <Td><DifficultyPill value={i.difficulty_target} /></Td>
                  <Td><StatusBadge kind="question" value={i.status} /></Td>
                  <Td><StatusBadge kind="validation" value={i.validation_status} /></Td>
                  <Td className="text-right tabular text-[13px]">{i.exposure_slots} slot{i.exposure_slots === 1 ? "" : "s"}<div className="text-[11px] text-fg-subtle">{fmtInt(i.candidate_exposures)} cand.</div></Td>
                  <Td><StatusBadge kind="leak" value={i.leak_status} /></Td>
                  <Td className="whitespace-nowrap text-[12px] text-fg-subtle">{timeAgo(i.updated_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
        {q.data && <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />}
      </Card>
      <QuestionDrawer id={openId} onOpenChange={(o) => { if (!o) { setOpenId(null); if (params.get("open")) { params.delete("open"); setParams(params, { replace: true }); } } }} />
      <CreateQuestionDialog open={creating} onOpenChange={setCreating} onCreated={(id) => { qc.invalidateQueries({ queryKey: ["questions"] }); setOpenId(id); }} />
      <BulkDialog action={bulk} ids={[...selected]} onDone={() => { setBulk(null); setSelected(new Set()); }} />
    </div>
  );
}

function BulkDialog({ action, ids, onDone }: { action: null | "archive" | "submit_for_review"; ids: number[]; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api<any>("/questions/bulk", { body: { ids, action, reason } }),
    onSuccess: (r) => { toast.success(`${r.updated.length} updated${r.skipped.length ? `, ${r.skipped.length} skipped (not applicable)` : ""}`); qc.invalidateQueries(); setReason(""); onDone(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  return (
    <Dialog open={!!action} onOpenChange={(o) => !o && onDone()} title={action === "archive" ? `Archive ${ids.length} item(s)` : `Submit ${ids.length} item(s) for review`}
      description="Only items whose status allows this action are changed; others are skipped and reported."
      footer={<><Button variant="ghost" onClick={onDone}>Cancel</Button><Button variant="primary" disabled={reason.trim().length < 5} loading={m.isPending} onClick={() => m.mutate()}>Apply</Button></>}>
      <Label htmlFor="bulk-reason">Reason</Label>
      <Textarea id="bulk-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Recorded on every affected item and in the audit log" />
    </Dialog>
  );
}

const optionSchema = z.object({ key: z.enum(["A", "B", "C", "D"]), text: z.string().trim().min(1, "Required").max(500) });
const createSchema = z.object({
  section: z.enum(["QUANT", "LOGICAL", "VERBAL"]),
  concept: z.string().trim().min(2, "Required").max(200),
  skill: z.string().trim().min(2, "Required").max(80),
  difficulty_target: z.enum(["easy", "medium", "hard"]),
  stem: z.string().trim().min(15, "At least 15 characters").max(4000),
  explanation: z.string().trim().min(5, "Explain the solution").max(4000),
  correct: z.enum(["A", "B", "C", "D"]),
  options: z.array(optionSchema).length(4),
}).refine((v) => new Set(v.options.map((o) => o.text.trim().toLowerCase())).size === 4, { message: "Options must be distinct", path: ["options"] });
type CreateForm = z.infer<typeof createSchema>;

function CreateQuestionDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (id: number) => void }) {
  const { register, control, handleSubmit, watch, setValue, reset, formState: { errors } } = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { section: "QUANT", difficulty_target: "medium", correct: "A", concept: "", skill: "", stem: "", explanation: "",
      options: ["A", "B", "C", "D"].map((k) => ({ key: k as "A", text: "" })) },
  });
  const { fields } = useFieldArray({ control, name: "options" });
  const m = useMutation({
    mutationFn: (v: CreateForm) => api<any>("/questions", { body: {
      section: v.section, concept: v.concept, skill: v.skill, difficulty_target: v.difficulty_target, stem: v.stem, explanation: v.explanation,
      options: v.options.map((o) => ({ key: o.key, text: o.text, is_correct: o.key === v.correct })) } }),
    onSuccess: (r) => { toast.success(`Created ${r.code} — sent to the review queue (validation: ${r.validation_status})`); reset(); onOpenChange(false); onCreated(r.id); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg" title="New source question"
      description="Human-authored items enter the review queue and are validated automatically. Nothing is published without approval."
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" loading={m.isPending} onClick={handleSubmit((v) => m.mutate(v))}>Create & validate</Button></>}>
      <form className="grid gap-4 md:grid-cols-3" onSubmit={(e) => e.preventDefault()} noValidate>
        <div><Label>Section</Label><Select ariaLabel="Section" value={watch("section")} onChange={(v) => setValue("section", v as any)} options={["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))} className="w-full" /></div>
        <div><Label>Target difficulty</Label><Select ariaLabel="Difficulty" value={watch("difficulty_target")} onChange={(v) => setValue("difficulty_target", v as any)} options={["easy", "medium", "hard"].map((s) => ({ value: s, label: titleCase(s) }))} className="w-full" /></div>
        <div><Label htmlFor="skill">Skill tag</Label><Input id="skill" {...register("skill")} placeholder="e.g. averages" /><FieldError>{errors.skill?.message}</FieldError></div>
        <div className="md:col-span-3"><Label htmlFor="concept">Concept</Label><Input id="concept" {...register("concept")} placeholder="e.g. Weighted averages" /><FieldError>{errors.concept?.message}</FieldError></div>
        <div className="md:col-span-3"><Label htmlFor="stem">Question stem</Label><Textarea id="stem" rows={3} {...register("stem")} /><FieldError>{errors.stem?.message}</FieldError></div>
        <fieldset className="md:col-span-3">
          <legend className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Options — select the single correct answer</legend>
          <div className="grid gap-2 md:grid-cols-2">
            {fields.map((f, i) => (
              <div key={f.id} className="flex items-center gap-2">
                <input type="radio" name="correct" aria-label={`Option ${f.key} is correct`} checked={watch("correct") === f.key} onChange={() => setValue("correct", f.key as any)} className="accent-[var(--ag-ok)]" />
                <span className="w-4 font-mono text-[12px] text-fg-subtle">{f.key}</span>
                <Input aria-label={`Option ${f.key}`} {...register(`options.${i}.text` as const)} />
              </div>
            ))}
          </div>
          <FieldError>{(errors.options as any)?.message ?? errors.options?.find?.((o) => o)?.text?.message}</FieldError>
        </fieldset>
        <div className="md:col-span-3"><Label htmlFor="expl">Explanation / worked solution</Label><Textarea id="expl" rows={2} {...register("explanation")} /><FieldError>{errors.explanation?.message}</FieldError></div>
      </form>
    </Dialog>
  );
}
