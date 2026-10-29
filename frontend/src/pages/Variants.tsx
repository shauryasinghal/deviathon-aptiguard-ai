import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ItemCard, ValidationList } from "@/features/questions";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/page";
import { Badge, Card, CardBody, CardHeader, Input, Label } from "@/components/ui/primitives";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SECTION_LABEL, titleCase } from "@/lib/utils";

export default function Variants() {
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [section, setSection] = useState("QUANT");
  const sourceId = params.get("source");
  const [n, setN] = useState(3);
  const [difficulty, setDifficulty] = useState("same");
  const [seed, setSeed] = useState("");
  const [result, setResult] = useState<any>(null);

  const sources = useQuery({ queryKey: ["sources", section], queryFn: () => api<any>(`/questions${qs({ section, source_only: true, page_size: 200, status: "approved,pending_review" })}`) });
  const compare = useQuery({ queryKey: ["compare", sourceId], queryFn: () => api<any>(`/questions/${sourceId}/compare`), enabled: !!sourceId });
  const tpl = useQuery({ queryKey: ["templates"], queryFn: () => api<any>("/variants/templates") });
  const runs = useQuery({ queryKey: ["gen-runs", sourceId], queryFn: () => api<any[]>(`/generation-runs${qs({ source_id: sourceId })}`), enabled: !!sourceId });

  const gen = useMutation({
    mutationFn: () => api<any>(`/questions/${sourceId}/variants:generate`, { body: { n, difficulty: difficulty === "same" ? null : difficulty, seed: seed ? Number(seed) : null, method: "auto" } }),
    onSuccess: (r) => { setResult(r); toast.success(r.run.message); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });

  return (
    <div>
      <PageHeader eyebrow="Content" title="AI Variant Studio"
        description="Generate parallel versions of a source item. Every candidate is re-verified and de-duplicated; survivors go to the review queue — never straight to production." />
      <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
        <Card className="h-fit">
          <CardHeader title="Generation settings" icon={<Sparkles />} />
          <CardBody className="space-y-4">
            <div><Label>Section</Label><Select ariaLabel="Section" className="w-full" value={section} onChange={(v) => { setSection(v); params.delete("source"); setParams(params); }}
              options={["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))} /></div>
            <div><Label>Source question</Label>
              <Select ariaLabel="Source question" className="w-full" value={sourceId ?? ""} placeholder={sources.isLoading ? "Loading…" : "Choose a source item"}
                onChange={(v) => { setResult(null); setParams({ source: v }); }}
                options={(sources.data?.items ?? []).map((q: any) => ({ value: String(q.id), label: `${q.code} · ${q.concept}` }))} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label htmlFor="n">Variants</Label><Input id="n" type="number" min={1} max={10} value={n} onChange={(e) => setN(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} /></div>
              <div><Label htmlFor="seed">Seed (optional)</Label><Input id="seed" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} placeholder="random" /></div>
            </div>
            <div><Label>Target difficulty</Label><Select ariaLabel="Target difficulty" className="w-full" value={difficulty} onChange={setDifficulty}
              options={[{ value: "same", label: "Same as source (parallel form)" }, ...["easy", "medium", "hard"].map((d) => ({ value: d, label: titleCase(d) }))]} /></div>
            <Button variant="primary" className="w-full" disabled={!sourceId || !can("variants.generate")} loading={gen.isPending} onClick={() => gen.mutate()}>
              <Sparkles />Generate & validate</Button>
            {!can("variants.generate") && <p className="text-[12px] text-fg-subtle">Your role can view but not generate variants.</p>}
            <p className="text-[12px] text-fg-subtle">Provider: {tpl.data?.llm?.configured ? `${tpl.data.llm.provider} (${tpl.data.llm.model})` : "Deterministic templates (LLM not configured)"} · {tpl.data?.templates?.length ?? "…"} verified templates</p>
          </CardBody>
        </Card>

        <div className="space-y-5">
          {!sourceId ? <Card><EmptyState icon={<Sparkles />} title="Pick a source question" description="Variants preserve the concept and difficulty, changing numbers, names and scenarios." /></Card>
            : compare.isError ? <Card><ErrorState error={compare.error} /></Card> : compare.isLoading ? <Card><LoadingRows /></Card> : (
              <>
                {result && (
                  <Card>
                    <CardHeader title={`Run #${result.run.id} · ${result.run.status}`} description={result.run.message}
                      actions={<Badge tone="warn">Sent to review queue</Badge>} />
                    <CardBody className="space-y-4">
                      {result.created.map((v: any) => (
                        <div key={v.id} className="grid gap-4 xl:grid-cols-[1fr_320px]">
                          <ItemCard q={v} title="New variant" highlight />
                          <div><h4 className="mb-2 text-[13px] font-semibold">Validation</h4><ValidationList checks={v.validation} compact /></div>
                        </div>
                      ))}
                      {result.rejections.length > 0 && (
                        <div className="rounded-md border border-danger/25 bg-danger-soft p-3 text-[12.5px]">
                          <div className="mb-1 font-medium text-danger">{result.rejections.length} candidate(s) rejected by the validator</div>
                          {result.rejections.map((r: any, i: number) => <div key={i} className="text-fg-muted">• {r.reasons.join("; ")}</div>)}
                        </div>
                      )}
                    </CardBody>
                  </Card>
                )}
                <div className="grid gap-4 xl:grid-cols-2">
                  <ItemCard q={compare.data.source} title="Source" />
                  {compare.data.variants.slice(0, 5).map((v: any) => <ItemCard key={v.id} q={v} title="Variant" />)}
                </div>
                {runs.data && runs.data.length > 0 && (
                  <Card><CardHeader title="Generation history" />
                    <ul className="divide-y divide-line">{runs.data.map((r) => (
                      <li key={r.id} className="px-5 py-2 text-[12.5px] text-fg-muted">#{r.id} · {r.provider} · seed {r.seed} · {r.message}</li>))}</ul>
                  </Card>
                )}
              </>
            )}
        </div>
      </div>
    </div>
  );
}
