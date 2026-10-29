import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { FlaggedAttempts } from "@/features/FlaggedAttempts";
import { ItemCard, ValidationList } from "@/features/questions";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { EmptyState, ErrorState, LoadingRows, PageHeader, Segmented } from "@/components/ui/page";
import { Card, CardBody, CardHeader, Input, Label, Mono, Textarea } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/ui/status";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, fmtDate, timeAgo, titleCase } from "@/lib/utils";

export default function Review() {
  const [params, setParams] = useSearchParams();
  const view = (params.get("tab") === "flagged" ? "flagged" : "items") as "items" | "flagged";
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["review-queue"], queryFn: () => api<any>("/review/queue") });
  const [sel, setSel] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const items = q.data?.items ?? [];
  const cur = items.find((i: any) => i.item.id === sel) ?? items[0];
  useEffect(() => setComment(""), [sel]);

  const decide = useMutation({
    mutationFn: (decision: string) => api<any>(`/review/${cur.item.id}/decision`, { body: { decision, comment: comment || null } }),
    onSuccess: (r, d) => {
      toast.success(`${r.item.code}: ${titleCase(d)}${r.regenerated?.length ? ` — new variant ${r.regenerated[0].code} queued` : ""}`);
      setSel(null); qc.invalidateQueries();
    },
    onError: (e: ApiError) => toast.error(e.message + (e.details && (e.details as any).issues ? `: ${(e.details as any).issues.join("; ")}` : "")),
  });

  return (
    <div>
      <PageHeader eyebrow="Content" title="Reviewer workspace"
        description="Compare each generated variant with its source, verify the key, edit if needed, then approve or reject. Authors cannot approve their own items." />
      <div className="mb-5"><Segmented ariaLabel="Review area" value={view} onChange={(v) => setParams(v === "items" ? {} : { tab: v })}
        options={[{ value: "items", label: "Item review" }, { value: "flagged", label: "Flagged attempts" }]} /></div>
      {view === "flagged" ? <FlaggedAttempts /> : (<>
      {q.isError ? <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card> : q.isLoading ? <Card><LoadingRows /></Card> : !items.length ? (
        <Card><EmptyState title="Review queue is empty" description="Generate variants in the Variant Studio to add items." /></Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          <Card className="h-fit">
            <CardHeader title={`Pending (${items.length})`} />
            <ul className="max-h-[70vh] divide-y divide-line overflow-y-auto">
              {items.map((i: any) => (
                <li key={i.item.id}>
                  <button onClick={() => setSel(i.item.id)} className={cn("w-full px-4 py-2.5 text-left hover:bg-surface-2", cur?.item.id === i.item.id && "bg-accent-soft")}>
                    <div className="flex items-center justify-between gap-2"><Mono className="text-fg">{i.item.code}</Mono><StatusBadge kind="validation" value={i.item.validation_status} /></div>
                    <div className="mt-0.5 text-[11.5px] text-fg-subtle">{i.item.concept} · {timeAgo(i.item.created_at)}</div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {cur && (
            <div className="space-y-5">
              <div className="grid gap-4 xl:grid-cols-2">
                {cur.source ? <ItemCard q={cur.source} title="Original" /> : <Card><EmptyState title="Human-authored source item" description="No parent: this is a new source question." /></Card>}
                <ItemCard q={cur.item} title="Candidate variant" highlight />
              </div>
              <div className="grid gap-5 xl:grid-cols-2">
                <Card><CardHeader title="Automated checks" /><CardBody><ValidationList checks={cur.item.validation} /></CardBody></Card>
                <Card>
                  <CardHeader title="Decision" actions={can("review.decide") && <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil />Edit</Button>} />
                  <CardBody className="space-y-3">
                    <Label htmlFor="cmt">Comment (required to reject)</Label>
                    <Textarea id="cmt" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What did you verify?" />
                    <div className="flex flex-wrap gap-2">
                      <Button variant="success" disabled={!can("review.decide")} loading={decide.isPending && decide.variables === "approve"} onClick={() => decide.mutate("approve")}><Check />Approve</Button>
                      <Button variant="danger" disabled={!can("review.decide") || comment.trim().length < 5} onClick={() => decide.mutate("reject")}><X />Reject</Button>
                      <Button variant="outline" disabled={!can("review.decide")} onClick={() => decide.mutate("request_regeneration")}><RefreshCw />Request regeneration</Button>
                    </div>
                    {!can("review.decide") && <p className="text-[12px] text-fg-subtle">Read-only: your role cannot decide on items.</p>}
                    <div className="border-t border-line pt-3">
                      <div className="mb-2 text-[12px] font-medium text-fg-muted">Revision history</div>
                      <ul className="space-y-1.5 text-[12px] text-fg-muted">
                        {[...cur.history.revisions, ...cur.history.decisions].sort((a: any, b: any) => (a.at < b.at ? 1 : -1)).map((h: any, k: number) => (
                          <li key={k}>{fmtDate(h.at)} · <span className="text-fg">{h.by?.name ?? "system"}</span> · {h.decision ? `decision: ${h.decision}` : `${h.change_type} v${h.version}`}{h.note || h.comment ? ` — ${h.note ?? h.comment}` : ""}</li>
                        ))}
                      </ul>
                    </div>
                  </CardBody>
                </Card>
              </div>
              {editing && <EditDialog item={cur.item} onClose={() => setEditing(false)} />}
            </div>
          )}
        </div>
      )}
      {q.data?.recent_decisions?.length > 0 && (
        <Card className="mt-5"><CardHeader title="Recent decisions" />
          <ul className="divide-y divide-line">{q.data.recent_decisions.map((d: any, i: number) => (
            <li key={i} className="flex gap-3 px-5 py-2 text-[12.5px]"><Mono>{d.question_code}</Mono><span className="text-fg">{titleCase(d.decision)}</span>
              <span className="text-fg-muted">{d.by?.name}</span><span className="ml-auto text-fg-subtle">{fmtDate(d.at)}</span></li>))}</ul>
        </Card>
      )}
      </>)}
    </div>
  );
}

function EditDialog({ item, onClose }: { item: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [stem, setStem] = useState(item.stem);
  const [expl, setExpl] = useState(item.explanation ?? "");
  const [opts, setOpts] = useState(item.options.map((o: any) => ({ key: o.key, text: o.text, is_correct: !!o.is_correct })));
  const m = useMutation({
    mutationFn: () => api(`/questions/${item.id}`, { method: "PATCH", body: { stem, explanation: expl, options: opts, note: "Reviewer edit" } }),
    onSuccess: () => { toast.success("Saved — re-validated and kept in review"); qc.invalidateQueries(); onClose(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} size="lg" title={`Edit ${item.code}`} description="Edits create a new revision and re-run validation."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>Save revision</Button></>}>
      <div className="space-y-3">
        <div><Label>Stem</Label><Textarea rows={3} value={stem} onChange={(e) => setStem(e.target.value)} /></div>
        {opts.map((o: any, i: number) => (
          <div key={o.key} className="flex items-center gap-2">
            <input type="radio" name="ok" aria-label={`Option ${o.key} correct`} checked={o.is_correct} onChange={() => setOpts(opts.map((x: any, j: number) => ({ ...x, is_correct: j === i })))} />
            <span className="w-4 font-mono text-xs">{o.key}</span>
            <Input value={o.text} onChange={(e) => setOpts(opts.map((x: any, j: number) => (j === i ? { ...x, text: e.target.value } : x)))} />
          </div>
        ))}
        <div><Label>Explanation</Label><Textarea value={expl} onChange={(e) => setExpl(e.target.value)} /></div>
      </div>
    </Dialog>
  );
}
