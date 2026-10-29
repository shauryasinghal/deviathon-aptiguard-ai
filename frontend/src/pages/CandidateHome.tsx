import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { ThemeToggle, UserMenu } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/page";
import { Badge, Card } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

export default function CandidateHome() {
  const q = useQuery({ queryKey: ["available"], queryFn: () => api<any>("/assessment/available") });
  return (
    <div className="min-h-full">
      <header className="flex h-14 items-center justify-between border-b border-line px-5"><Logo /><div className="flex items-center gap-2"><ThemeToggle /><UserMenu /></div></header>
      <main className="mx-auto max-w-3xl px-5 py-10">
        <h1 className="text-[22px] font-semibold">Your assessments</h1>
        <p className="mt-1 text-sm text-fg-muted">{q.data ? `${q.data.candidate.name} · ${q.data.candidate.code}` : ""} — only assessments assigned to you are listed.</p>
        <Card className="mt-6">
          {q.isError ? <ErrorState error={q.error} /> : q.isLoading ? <LoadingRows /> : !q.data.forms.length ? <EmptyState title="No published assessments" /> : (
            <ul className="divide-y divide-line">{q.data.forms.map((f: any) => (
              <li key={f.form_id} className="flex flex-wrap items-center gap-3 px-5 py-4">
                <div className="min-w-0 flex-1"><div className="text-[14px] font-medium">{f.slot}</div>
                  <div className="text-[12.5px] text-fg-muted"><Clock className="mr-1 inline size-3.5" />{fmtDate(f.slot_starts_at)} · {f.n_items} questions · {f.duration_minutes} min</div></div>
                {!f.window.enforced && !f.attempt && <Badge tone="info">Slot window not enforced (demo policy)</Badge>}
                {f.attempt?.status === "submitted" ? <Badge tone="ok">Submitted · {f.attempt.score}/{f.attempt.max_score}</Badge>
                  : f.attempt ? <Button asChild variant="outline" size="sm"><Link to={`/assessment/${f.form_id}`}>Resume<ArrowRight /></Link></Button>
                  : f.can_start ? <Button asChild variant="primary" size="sm"><Link to={`/assessment/${f.form_id}`}>Start<ArrowRight /></Link></Button>
                  : <Badge tone="neutral">{f.form_status !== "published" ? "Temporarily unavailable" : f.window.state === "not_yet_open" ? `Opens ${fmtDate(f.window.opens_at)}` : "Window closed"}</Badge>}
              </li>))}</ul>
          )}
        </Card>
      </main>
    </div>
  );
}
