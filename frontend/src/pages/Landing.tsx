import {
  ArrowRight, BadgeCheck, Boxes, Check, ClipboardCheck, FileSearch, FlaskConical, GitBranch, Lock, Radar, ScrollText,
  ShieldAlert, Sparkles, Timer, UserCheck,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { LogoMark, Logo } from "@/components/layout/Logo";
import { ThemeToggle } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const PREVIEWS = ["Leak timeline", "Overlap matrix", "Variant review"] as const;

function LeakPreview() {
  // Illustrative shape of the demo scenario (not live data)
  const slots = [0.46, 0.47, 0.71, 0.79, 0.83, 0.84, 0.85, 0.84, 0.86, 0.85];
  const base = [0.46, 0.47, 0.47, 0.5, 0.46, 0.47, 0.45, 0.47, 0.5, 0.48];
  const x = (i: number) => 24 + i * 52;
  const y = (v: number) => 150 - (v - 0.3) * 220;
  const path = (a: number[]) => a.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  return (
    <div>
      <svg viewBox="0 0 520 170" className="w-full" role="img" aria-label="Illustration: a leaked item becomes easier from slot 3 while a control item stays flat">
        {[0.4, 0.6, 0.8].map((g) => <line key={g} x1="16" x2="510" y1={y(g)} y2={y(g)} className="stroke-line" strokeDasharray="3 4" />)}
        <rect x={x(2) - 26} y="8" width={52 * 8 + 8} height="146" className="fill-danger/[0.06]" rx="6" />
        <text x={x(2) - 18} y="22" className="fill-danger text-[10px] font-medium">post detected before slot 3</text>
        <path d={path(base)} className="stroke-fg-subtle" fill="none" strokeWidth="2" />
        <path d={path(slots)} className="stroke-danger" fill="none" strokeWidth="2.5" />
        {slots.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="3.5" className="fill-danger" />)}
        {slots.map((_, i) => <text key={i} x={x(i)} y="168" textAnchor="middle" className="fill-fg-subtle text-[9.5px]">S{i + 1}</text>)}
      </svg>
      <div className="mt-2 flex flex-wrap gap-2 text-[11.5px]">
        <Badge tone="danger" dot>Leaked item · ETS Δ +2.3, q &lt; 0.001</Badge>
        <Badge tone="neutral" dot>Control item · ability-adjusted, no drift</Badge>
      </div>
    </div>
  );
}

function OverlapPreview() {
  const n = 8;
  const val = (i: number, j: number) => (i === j ? 1 : Math.abs(i - j) === 1 ? 0 : (i * 7 + j * 3) % 5 === 0 ? 0.03 : 0);
  return (
    <div>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${n}, minmax(0,1fr))` }} role="img" aria-label="Illustration: overlap matrix with zero shared items between adjacent slots">
        {Array.from({ length: n * n }).map((_, k) => {
          const i = Math.floor(k / n), j = k % n, v = val(i, j);
          return <div key={k} className={cn("aspect-square rounded-[3px] border border-line", i === j ? "bg-accent/70" : v > 0 ? "bg-accent/25" : Math.abs(i - j) === 1 ? "bg-ok/15" : "bg-surface-3")} />;
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[11.5px]">
        <Badge tone="ok" dot>Adjacent slots: 0% shared (limit 10%)</Badge>
        <Badge tone="accent" dot>Jaccard verified for every pair</Badge>
      </div>
    </div>
  );
}

function VariantPreview() {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {[["Source", "A train covers 240 km in 4 hours. How long for 420 km?", "7 hours"],
        ["Variant V02", "A delivery van covers 180 km in 3 hours. How long for 360 km?", "6 hours"]].map(([t, s, a]) => (
        <div key={t} className="rounded-md border border-line bg-surface-2 p-3">
          <div className="mb-1.5 flex items-center justify-between text-[11px] uppercase tracking-wider text-fg-subtle">{t}
            {t !== "Source" && <Badge tone="warn" dot>Pending review</Badge>}</div>
          <p className="text-[13px] text-fg">{s}</p>
          <p className="mt-2 flex items-center gap-1.5 text-[12px] text-ok"><BadgeCheck className="size-3.5" />Answer recomputed: {a}</p>
        </div>
      ))}
    </div>
  );
}

const FEATURES = [
  { icon: Sparkles, title: "Verifiable variant generation", body: "Parameterised templates for quantitative, logical and verbal items. Every answer is recomputed or brute-force checked — never trusted from a model." },
  { icon: UserCheck, title: "Mandatory human review", body: "Nothing goes live automatically. Independent reviewers compare source and variant, edit, approve or reject with full revision history." },
  { icon: FlaskConical, title: "Honest psychometrics", body: "CTT with Wilson intervals, Rasch MML when the design is linked, and equivalence (TOST) decisions that say ‘inconclusive’ when data are thin." },
  { icon: Boxes, title: "Exposure-aware assembly", body: "Seeded, reproducible forms that respect exposure limits, reuse spacing, family separation and adjacent-slot overlap — or fail with the reason." },
  { icon: ShieldAlert, title: "Evidence-backed leak alerts", body: "Text matching against authorised datasets plus ability-adjusted Mantel–Haenszel drift and response-time signals, FDR-controlled." },
  { icon: ScrollText, title: "Audit-ready reporting", body: "Every decision is attributed and timestamped. CSV, JSON and PDF reports carry provenance and insufficient-evidence warnings." },
];

const FLOW = [
  { icon: GitBranch, label: "Generate", sub: "templates / LLM" },
  { icon: ClipboardCheck, label: "Validate", sub: "recompute · dedupe" },
  { icon: UserCheck, label: "Review", sub: "human approval" },
  { icon: FlaskConical, label: "Calibrate", sub: "CTT · Rasch" },
  { icon: Boxes, label: "Assemble", sub: "constraints · seed" },
  { icon: Timer, label: "Deliver", sub: "server-scored" },
  { icon: Radar, label: "Detect", sub: "text · drift · RT" },
];

export default function Landing() {
  const [tab, setTab] = useState<(typeof PREVIEWS)[number]>("Leak timeline");
  return (
    <div className="min-h-full bg-canvas">
      <header className="sticky top-0 z-40 border-b border-line/70 bg-canvas/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-5">
          <Logo />
          <nav className="hidden items-center gap-6 text-[13.5px] text-fg-muted md:flex" aria-label="Landing">
            <a href="#problem" className="hover:text-fg">Problem</a>
            <a href="#platform" className="hover:text-fg">Platform</a>
            <a href="#workflow" className="hover:text-fg">Workflow</a>
            <a href="#governance" className="hover:text-fg">Governance</a>
          </nav>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button asChild variant="primary" size="sm"><Link to="/login">Open demo<ArrowRight /></Link></Button>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden border-b border-line">
        <div className="grid-bg absolute inset-0 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_70%)]" aria-hidden />
        <div className="absolute left-1/2 top-[-240px] h-[480px] w-[900px] -translate-x-1/2 rounded-full bg-accent-strong/20 blur-[120px]" aria-hidden />
        <div className="relative mx-auto grid max-w-6xl gap-12 px-5 pb-20 pt-20 lg:grid-cols-[1.05fr_1fr] lg:items-center">
          <div>
            <Badge tone="accent" className="mb-5">IM-107 · Integraminds · AI Frontier</Badge>
            <h1 className="text-[40px] font-semibold leading-[1.08] tracking-tight text-fg md:text-[52px]">
              An aptitude test that <span className="bg-gradient-to-r from-[#A5B4FC] to-[#7C83FF] bg-clip-text text-transparent">survives ten slots.</span>
            </h1>
            <p className="mt-5 max-w-xl text-[16px] leading-relaxed text-fg-muted">
              AptiGuard AI generates verifiable parallel items, calibrates them on real responses, assembles exposure-aware
              forms for every slot, and detects leaks from the data — with a human in the loop for every decision.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg"><Link to="/login">Launch the command center<ArrowRight /></Link></Button>
              <Button asChild variant="outline" size="lg"><a href="#workflow">See how it works</a></Button>
            </div>
            <ul className="mt-8 grid max-w-lg grid-cols-2 gap-x-6 gap-y-2 text-[13px] text-fg-muted">
              {["Runs fully offline on a laptop", "No auto-publishing of AI content", "Every number traceable to data", "Reproducible with a seed"].map((t) => (
                <li key={t} className="flex items-center gap-2"><Check className="size-3.5 text-ok" />{t}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-line-strong bg-surface p-4 shadow-pop">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex gap-1 rounded-md border border-line bg-surface-2 p-0.5" role="tablist" aria-label="Product preview">
                {PREVIEWS.map((p) => (
                  <button key={p} role="tab" aria-selected={tab === p} onClick={() => setTab(p)}
                    className={cn("rounded-[5px] px-2.5 py-1 text-[12px] font-medium", tab === p ? "bg-surface-3 text-fg" : "text-fg-muted hover:text-fg")}>{p}</button>
                ))}
              </div>
              <span className="text-[10.5px] uppercase tracking-wider text-fg-subtle">Illustrative preview</span>
            </div>
            <div className="rounded-lg border border-line bg-canvas/60 p-4">
              {tab === "Leak timeline" && <LeakPreview />}
              {tab === "Overlap matrix" && <OverlapPreview />}
              {tab === "Variant review" && <VariantPreview />}
            </div>
            <p className="mt-3 text-[11.5px] text-fg-subtle">Illustrations mirror the synthetic demo scenario. Live figures are in the app.</p>
          </div>
        </div>
      </section>

      <section id="problem" className="border-b border-line">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-20 md:grid-cols-3">
          <div className="md:col-span-1">
            <div className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-accent">The problem</div>
            <h2 className="mt-2 text-[28px] font-semibold tracking-tight">A question bank loses its value in a week.</h2>
          </div>
          <div className="grid gap-4 sm:grid-cols-3 md:col-span-2">
            {[["Hours", "after slot 1, questions appear in Telegram channels and ‘solution’ videos."],
              ["Unfair", "hand-written variants drift in difficulty; later slots score higher."],
              ["Too late", "leaks are discovered from complaints, not from the data."]].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line bg-surface p-5">
                <div className="text-[22px] font-semibold text-fg">{k}</div>
                <p className="mt-2 text-[13.5px] leading-relaxed text-fg-muted">{v}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="platform" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-5 py-20">
          <div className="max-w-2xl">
            <div className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-accent">The platform</div>
            <h2 className="mt-2 text-[28px] font-semibold tracking-tight">One integrity loop, from item to incident.</h2>
          </div>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="group rounded-lg border border-line bg-surface p-5 transition-colors hover:border-line-strong">
                <div className="mb-4 grid size-9 place-items-center rounded-md border border-accent/25 bg-accent-soft text-accent"><f.icon className="size-4" /></div>
                <h3 className="text-[15px] font-semibold">{f.title}</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-fg-muted">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="workflow" className="border-b border-line bg-surface/40">
        <div className="mx-auto max-w-6xl px-5 py-20">
          <div className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-accent">Workflow</div>
          <h2 className="mt-2 text-[28px] font-semibold tracking-tight">Closed-loop, human-governed, measurable.</h2>
          <ol className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {FLOW.map((s, i) => (
              <li key={s.label} className="relative rounded-lg border border-line bg-surface p-4">
                <div className="mb-3 flex items-center justify-between">
                  <s.icon className="size-4 text-accent" />
                  <span className="font-mono text-[10.5px] text-fg-subtle">0{i + 1}</span>
                </div>
                <div className="text-[13.5px] font-semibold">{s.label}</div>
                <div className="mt-0.5 text-[12px] text-fg-muted">{s.sub}</div>
              </li>
            ))}
          </ol>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {[["Architecture", "React · TypeScript SPA → FastAPI modular monolith → SQLite (PostgreSQL-ready) via SQLAlchemy + Alembic."],
              ["Algorithms", "Template verifiers · TF-IDF char n-grams · Rasch MML-EM · Mantel–Haenszel + Benjamini–Hochberg · greedy assembly with backtracking."],
              ["Optional AI", "LLM adapter with schema-validated output. Off by default; deterministic templates keep the platform fully functional offline."]].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line bg-surface p-4">
                <div className="text-[12px] font-medium uppercase tracking-wider text-fg-subtle">{k}</div>
                <p className="mt-1.5 text-[13.5px] text-fg-muted">{v}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="governance" className="border-b border-line">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-20 md:grid-cols-2">
          <div>
            <div className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-accent">Trust & governance</div>
            <h2 className="mt-2 text-[28px] font-semibold tracking-tight">Built to be audited, not just demoed.</h2>
            <p className="mt-4 text-[14.5px] leading-relaxed text-fg-muted">
              AptiGuard separates what it <em>knows</em> from what it <em>suspects</em>. Text found in a supplied dataset,
              statistically suspicious drift, unverified exposure and human-confirmed incidents are always labelled differently.
            </p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {[[Lock, "Server-side RBAC", "Five roles; every permission checked by the API."],
              [FileSearch, "No fabricated evidence", "Only authorised, imported datasets are searched."],
              [UserCheck, "Independent review", "Authors cannot approve their own items."],
              [ScrollText, "Full audit trail", "Who changed what, when — exportable."]].map(([Icon, t, d]: any) => (
              <li key={t} className="rounded-lg border border-line bg-surface p-4">
                <Icon className="mb-2 size-4 text-ok" />
                <div className="text-[13.5px] font-semibold">{t}</div>
                <div className="mt-1 text-[12.5px] text-fg-muted">{d}</div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="border-b border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-center px-5 py-16 text-center">
          <LogoMark className="size-10" />
          <h2 className="mt-4 text-[26px] font-semibold tracking-tight">See the integrity loop end to end.</h2>
          <p className="mt-2 max-w-lg text-sm text-fg-muted">Seeded synthetic demo: 593 items, 10 historical slots, 45,000 responses and a deliberately simulated leak.</p>
          <Button asChild variant="primary" size="lg" className="mt-6"><Link to="/login">Open the demo<ArrowRight /></Link></Button>
        </div>
      </section>

      <footer className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-8 text-[12.5px] text-fg-subtle md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2"><LogoMark className="size-5" />AptiGuard AI · Hackathon prototype for IM-107 (Deviathon 2.0)</div>
        <div>Synthetic demo data only · Not production-certified · <a className="hover:text-fg" href="/api/docs">API docs</a></div>
      </footer>
    </div>
  );
}
