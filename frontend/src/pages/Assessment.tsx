import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Clock, Flag, Send } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { ErrorState, LoadingRows } from "@/components/ui/page";
import { Card, CardBody } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function Assessment() {
  const { formId } = useParams();
  const qc = useQueryClient();
  const form = useQuery({ queryKey: ["cform", formId], queryFn: () => api<any>(`/assessment/forms/${formId}`) });
  const [attempt, setAttempt] = useState<any>(null);
  const [started, setStarted] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string | null>>({});
  const [idx, setIdx] = useState(0);
  const [flags, setFlags] = useState<Set<number>>(new Set());
  const [remaining, setRemaining] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const shownAt = useRef(Date.now());
  const unsaved = useRef<Map<number, { item_ref: number; selected_key: string; time_spent_ms?: number }>>(new Map());

  // Persist every unsaved answer in one request; failures stay queued and are retried on the next save / submit.
  const flush = useCallback(async (attemptId: number) => {
    if (!unsaved.current.size) return true;
    // Take the entries out of the queue *before* sending, so overlapping saves never send the same entry twice
    // (the server adds time_spent_ms, so a duplicate send would inflate response-time data).
    const batch = [...unsaved.current.values()];
    batch.forEach((b) => unsaved.current.delete(b.item_ref));
    setSaving("saving");
    try {
      await api(`/assessment/attempts/${attemptId}/responses`, { method: "PUT", body: { answers: batch } });
      setSaving(unsaved.current.size ? "error" : "saved");
      return unsaved.current.size === 0;
    } catch (e) {
      // re-queue unless a newer answer for the same item was chosen meanwhile
      batch.forEach((b) => { if (!unsaved.current.has(b.item_ref)) unsaved.current.set(b.item_ref, b); });
      setSaving("error");
      toast.error(`${(e as ApiError).message} — your answer is kept and will be retried.`);
      return false;
    }
  }, []);

  const start = useMutation({
    mutationFn: () => api<any>(`/assessment/forms/${formId}/attempts`, { method: "POST" }),
    onSuccess: (a) => { setAttempt(a); setAnswers(a.answers ?? {}); setRemaining(a.remaining_seconds); setStarted(true); shownAt.current = Date.now(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const submit = useMutation({
    mutationFn: async () => {
      if (!(await flush(attempt.attempt_id))) throw new ApiError(0, "unsaved", "Some answers could not be saved. Check your connection and try again.");
      return api<any>(`/assessment/attempts/${attempt.attempt_id}/submit`, { method: "POST" });
    },
    onSuccess: (a) => { setAttempt(a); setConfirm(false); qc.invalidateQueries({ queryKey: ["available"] }); toast.success("Assessment submitted"); },
    onError: (e: ApiError) => toast.error(e.message),
  });

  useEffect(() => {
    if (!started || attempt?.status !== "in_progress") return;
    const t = setInterval(() => setRemaining((r) => { if (r <= 1) { clearInterval(t); submit.mutate(); return 0; } return r - 1; }), 1000);
    return () => clearInterval(t);
  }, [started, attempt?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const items = form.data?.items ?? [];
  const item = items[idx];
  const choose = useCallback(async (key: string) => {
    if (!item || attempt?.status !== "in_progress") return;
    setAnswers((a) => ({ ...a, [item.item_ref]: key }));
    unsaved.current.set(item.item_ref, { item_ref: item.item_ref, selected_key: key, time_spent_ms: Date.now() - shownAt.current });
    shownAt.current = Date.now();
    await flush(attempt.attempt_id);
  }, [item, attempt, flush]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!started || confirm || attempt?.status !== "in_progress") return;
      const k = e.key.toUpperCase();
      if (["A", "B", "C", "D"].includes(k)) choose(k);
      if (e.key === "ArrowRight") setIdx((i) => Math.min(items.length - 1, i + 1));
      if (e.key === "ArrowLeft") setIdx((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [started, confirm, attempt, choose, items.length]);

  const sections = useMemo(() => [...new Set(items.map((i: any) => i.section))] as string[], [items]);
  const answered = Object.values(answers).filter(Boolean).length;
  const mm = String(Math.floor(remaining / 60)).padStart(2, "0"), ss = String(remaining % 60).padStart(2, "0");

  if (form.isError) return <div className="p-10"><ErrorState error={form.error} /></div>;
  if (form.isLoading) return <LoadingRows />;
  const f = form.data;

  if (attempt?.status === "submitted") {
    const r = attempt.result;
    return (
      <div className="grid min-h-full place-items-center p-6"><Card className="w-full max-w-lg"><CardBody className="space-y-4 text-center">
        <h1 className="text-[20px] font-semibold">Assessment submitted</h1>
        <p className="text-sm text-fg-muted">Scored on the server. Answer keys are never sent to your browser.</p>
        <div className="text-[40px] font-semibold tabular">{r.score} / {r.max_score}</div>
        <div className="grid grid-cols-3 gap-2 text-[12.5px]">{Object.entries(r.section_scores).map(([k, v]: any) => (
          <div key={k} className="rounded-md border border-line p-2"><div className="text-fg-subtle">{k}</div><div className="font-semibold tabular">{v.score}/{v.max}</div><div className="text-fg-subtle">{v.answered} answered</div></div>))}</div>
        <Button asChild variant="primary"><Link to="/assessment">Back to my assessments</Link></Button>
      </CardBody></Card></div>
    );
  }

  if (!started) {
    return (
      <div className="grid min-h-full place-items-center p-6"><Card className="w-full max-w-xl"><CardBody className="space-y-4">
        <Logo />
        <h1 className="text-[20px] font-semibold">{f.slot}</h1>
        <p className="text-sm text-fg-muted">{f.n_items} questions · {f.duration_minutes} minutes · sections: {sections.join(", ")}</p>
        <ul className="list-disc space-y-1 pl-5 text-[13.5px] text-fg-muted">{f.instructions.map((i: string) => <li key={i}>{i}</li>)}</ul>
        <p className="text-[12.5px] text-fg-subtle">Keyboard: A–D to answer, ←/→ to move between questions.</p>
        <Button variant="primary" className="w-full" loading={start.isPending} onClick={() => start.mutate()}>Start / resume assessment</Button>
      </CardBody></Card></div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur">
        <Logo collapsed /><span className="hidden truncate text-sm font-medium sm:block">{f.slot}</span>
        <span className="flex-1" />
        <span className="text-[12px] text-fg-subtle" aria-live="polite">{saving === "saving" ? "Saving…" : saving === "saved" ? "All answers saved" : saving === "error" ? `${unsaved.current.size} answer(s) not yet saved — will retry` : ""}</span>
        <span className={cn("flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-sm tabular", remaining < 300 ? "border-danger/40 text-danger" : "border-line-strong")} role="timer" aria-label={`Time remaining ${mm} minutes ${ss} seconds`}>
          <Clock className="size-4" />{mm}:{ss}</span>
        <Button variant="primary" size="sm" onClick={() => setConfirm(true)}><Send />Submit</Button>
      </header>
      <div className="mx-auto grid w-full max-w-6xl flex-1 gap-5 p-4 md:grid-cols-[1fr_260px] md:p-6">
        <Card className="h-fit">
          <div className="flex flex-wrap items-center gap-1 border-b border-line px-4 py-2" role="tablist" aria-label="Sections">
            {sections.map((s) => { const first = items.findIndex((i: any) => i.section === s); return (
              <button key={s} role="tab" aria-selected={item?.section === s} onClick={() => setIdx(first)} className={cn("rounded-md px-3 py-1 text-[13px]", item?.section === s ? "bg-surface-3 text-fg" : "text-fg-muted hover:text-fg")}>{items[first].section_name}</button>); })}
          </div>
          {item && <CardBody className="space-y-5">
            <div className="flex items-center justify-between text-[12.5px] text-fg-subtle"><span>Question {idx + 1} of {items.length}</span>
              <button onClick={() => setFlags((s) => { const n = new Set(s); n.has(idx) ? n.delete(idx) : n.add(idx); return n; })} className={cn("flex items-center gap-1", flags.has(idx) && "text-warn")} aria-pressed={flags.has(idx)}><Flag className="size-3.5" />{flags.has(idx) ? "Flagged" : "Flag for review"}</button></div>
            <p className="prose-item text-[16px] text-fg">{item.stem}</p>
            <div role="radiogroup" aria-label="Answer options" className="space-y-2">
              {item.options.map((o: any) => { const sel = answers[item.item_ref] === o.key; return (
                <button key={o.key} role="radio" aria-checked={sel} onClick={() => choose(o.key)}
                  className={cn("flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-[14.5px] transition-colors", sel ? "border-accent bg-accent-soft" : "border-line bg-surface-2 hover:border-line-strong")}>
                  <span className={cn("grid size-6 shrink-0 place-items-center rounded-md font-mono text-[12px] font-semibold", sel ? "bg-accent-strong text-white" : "bg-surface-3 text-fg-muted")}>{o.key}</span>{o.text}</button>); })}
            </div>
            <div className="flex justify-between">
              <Button variant="outline" disabled={idx === 0} onClick={() => { setIdx(idx - 1); shownAt.current = Date.now(); }}><ChevronLeft />Previous</Button>
              <Button variant="outline" disabled={idx === items.length - 1} onClick={() => { setIdx(idx + 1); shownAt.current = Date.now(); }}>Next<ChevronRight /></Button>
            </div>
          </CardBody>}
        </Card>
        <Card className="h-fit"><CardBody>
          <div className="mb-3 text-[12.5px] text-fg-muted">{answered} of {items.length} answered</div>
          <div className="grid grid-cols-6 gap-1.5" aria-label="Question navigator">
            {items.map((it: any, i: number) => (
              <button key={it.item_ref} onClick={() => { setIdx(i); shownAt.current = Date.now(); }} aria-label={`Question ${i + 1}${answers[it.item_ref] ? ", answered" : ""}${flags.has(i) ? ", flagged" : ""}`}
                className={cn("relative h-8 rounded-md border text-[12px] tabular", i === idx ? "border-accent text-fg" : "border-line", answers[it.item_ref] ? "bg-accent-soft text-accent" : "bg-surface-2 text-fg-muted")}>
                {i + 1}{flags.has(i) && <span className="absolute right-0.5 top-0.5 size-1.5 rounded-full bg-warn" />}</button>))}
          </div>
        </CardBody></Card>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm} title="Submit your assessment?"
        description={`${answered} of ${items.length} answered${flags.size ? `, ${flags.size} flagged` : ""}. You cannot change answers after submitting.`}
        footer={<><Button variant="ghost" onClick={() => setConfirm(false)}>Keep working</Button><Button variant="primary" loading={submit.isPending} onClick={() => submit.mutate()}>Submit</Button></>} />
    </div>
  );
}
