import { useQuery } from "@tanstack/react-query";
import {
  Activity, AlertOctagon, ArrowUpRight, Boxes, CheckCircle2, ClipboardList, Database, FlaskConical, Layers, Radar, ShieldAlert,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, ErrorBar, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axis, BAND_COLORS, C, ChartTooltip, Legend } from "@/components/charts/theme";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { DataNotice, EmptyState, ErrorState, LoadingRows, PageHeader, StatCard } from "@/components/ui/page";
import { Badge, Card, CardBody, CardHeader, Input, Label, Progress } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/ui/status";
import { api, qs } from "@/lib/api";
import { fmtDate, fmtInt, SECTION_LABEL, timeAgo, titleCase } from "@/lib/utils";

const CAL_ORDER = ["within_tolerance", "calibrated_reference", "requires_review", "outside_tolerance", "insufficient_data"];
const CAL_COLOR: Record<string, string> = {
  within_tolerance: C.ok, calibrated_reference: C.accent, requires_review: C.warn, outside_tolerance: C.danger, insufficient_data: C.muted,
};

export default function Dashboard() {
  const [section, setSection] = useState("all");
  const [drive, setDrive] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const nav = useNavigate();
  const params = { section, drive, date_from: from ? `${from}T00:00:00` : undefined, date_to: to ? `${to}T23:59:59` : undefined };
  const q = useQuery({ queryKey: ["dashboard", params], queryFn: () => api<any>(`/dashboard/summary${qs(params)}`) });
  const d = q.data;

  const diffData = useMemo(() => {
    if (!d) return [];
    const by: Record<string, any> = {};
    for (const r of d.difficulty.target) {
      by[r.section] ??= { section: SECTION_LABEL[r.section] ?? r.section };
      by[r.section][r.band] = r.n;
    }
    return Object.values(by);
  }, [d]);
  const calData = useMemo(() => (d ? CAL_ORDER.map((k) => ({ key: k, name: titleCase(k), n: d.calibration.status_counts[k] ?? 0 })) : []), [d]);
  const slotData = useMemo(() => (d?.slots ?? []).map((s: any) => ({ ...s, label: `S${s.sequence}`, err: s.theta_se ? 1.96 * s.theta_se : 0 })), [d]);

  return (
    <div>
      <PageHeader eyebrow="Command center" title="Assessment integrity overview"
        description="Live state of the bank, review pipeline, exposure, calibration and leak investigations."
        actions={<>
          <Select ariaLabel="Section filter" value={section} onChange={setSection} options={[{ value: "all", label: "All sections" },
            ...["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))]} />
          <Select ariaLabel="Drive filter" value={drive} onChange={setDrive} className="min-w-[200px]"
            options={[{ value: "all", label: "All drives" }, ...(d?.drives ?? []).map((x: string) => ({ value: x, label: x }))]} />
        </>} />

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3 px-4 py-3">
          <div><Label htmlFor="from">From</Label><Input id="from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="w-[160px]" /></div>
          <div><Label htmlFor="to">To</Label><Input id="to" type="date" value={to} onChange={(e) => setTo(e.target.value)} className="w-[160px]" /></div>
          <p className="pb-2 text-[12px] text-fg-subtle">Dates filter slot statistics and alert detection time.</p>
          {(from || to || section !== "all" || drive !== "all") && (
            <Button size="sm" variant="ghost" className="mb-0.5" onClick={() => { setFrom(""); setTo(""); setSection("all"); setDrive("all"); }}>Clear filters</Button>
          )}
          <div className="ml-auto flex items-center gap-2 pb-1.5 text-[12px] text-fg-subtle">
            <Database className="size-3.5" />{d?.data_label ?? "…"}
          </div>
        </div>
      </Card>

      {q.isError ? <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card> : (
        <>
          {d?.data_label?.startsWith("Synthetic") && (
            <DataNotice>All figures are computed live from the database. This workspace holds deterministic synthetic demo data (seed 107), not official Integraminds data.</DataNotice>
          )}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            <StatCard label="Questions in bank" value={fmtInt(d?.kpis.total_questions)} icon={<Layers />} loading={q.isLoading}
              hint={d && `${fmtInt(d.kpis.approved)} approved`} onClick={() => nav("/questions")} />
            <StatCard label="Approved variants" value={fmtInt(d?.kpis.approved_variants)} icon={<CheckCircle2 />} tone="ok" loading={q.isLoading}
              hint="Human-approved parallel forms" onClick={() => nav("/questions?status=approved")} />
            <StatCard label="Pending reviews" value={fmtInt(d?.kpis.pending_reviews)} icon={<ClipboardList />} tone="warn" loading={q.isLoading}
              hint="Awaiting an independent reviewer" onClick={() => nav("/review")} />
            <StatCard label="Exposure warnings" value={fmtInt(d?.kpis.exposure_warnings)} icon={<Radar />} tone="warn" loading={q.isLoading}
              hint={d && `${d.kpis.over_limit} over limit`} onClick={() => nav("/exposure")} help="Approved/quarantined items at or above the exposure warning ratio" />
            <StatCard label="Active leak alerts" value={fmtInt(d?.kpis.active_leak_alerts)} icon={<ShieldAlert />} tone="danger" loading={q.isLoading}
              hint={d && `${d.kpis.critical_alerts} critical`} onClick={() => nav("/leaks")} />
            <StatCard label="Candidates assessed" value={fmtInt(d?.kpis.candidates_assessed)} icon={<Users />} tone="accent" loading={q.isLoading}
              hint="Submitted attempts in scope" />
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Slot comparison" icon={<Activity />}
                description="Mean raw score vs. Rasch ability estimate (±95% CI). Raw scores rise with leaks and cohort ability; ability estimates exclude suspected leaked items."
                actions={<Button size="sm" variant="ghost" asChild><Link to="/calibration">Calibration lab<ArrowUpRight /></Link></Button>} />
              <CardBody>
                {q.isLoading ? <LoadingRows rows={5} /> : slotData.length === 0 ? <EmptyState title="No slot data in this filter" /> : (
                  <>
                    <div className="h-[260px]">
                      <ResponsiveContainer>
                        <ComposedChart data={slotData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                          <CartesianGrid stroke={C.grid} vertical={false} />
                          <XAxis dataKey="label" {...axis} />
                          <YAxis yAxisId="pct" {...axis} domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                          <YAxis yAxisId="th" orientation="right" {...axis} domain={[-1, 1]} />
                          <Tooltip content={<ChartTooltip formatter={(v, n) => (n === "Mean score" ? `${v}%` : Number(v).toFixed(2))} />} cursor={{ fill: "rgba(127,135,160,0.08)" }} />
                          <Bar yAxisId="pct" dataKey="mean_pct" name="Mean score" fill={C.accent} fillOpacity={0.55} radius={[4, 4, 0, 0]} maxBarSize={36} />
                          <Line yAxisId="th" dataKey="mean_theta" name="Mean ability (θ)" stroke={C.ok} strokeWidth={2} dot={{ r: 3 }}>
                            <ErrorBar dataKey="err" width={4} stroke={C.ok} strokeOpacity={0.6} />
                          </Line>
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="mt-2"><Legend items={[{ label: "Mean raw score (%)", color: C.accent }, { label: "Mean Rasch ability θ ± 95% CI", color: C.ok }]} /></div>
                  </>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="High-priority alerts" icon={<AlertOctagon />} actions={<Button size="sm" variant="ghost" asChild><Link to="/leaks">All<ArrowUpRight /></Link></Button>} />
              {q.isLoading ? <LoadingRows /> : !d?.alerts.length ? <EmptyState title="No active alerts" description="Leak detection has not raised any open alert in this scope." /> : (
                <ul className="divide-y divide-line">
                  {d.alerts.map((a: any) => (
                    <li key={a.id}>
                      <button onClick={() => nav(`/leaks?alert=${a.id}`)} className="flex w-full items-start gap-3 px-5 py-3 text-left hover:bg-surface-2">
                        <StatusBadge kind="severity" value={a.severity} />
                        <span className="min-w-0 flex-1">
                          <span className="block font-mono text-[12.5px] text-fg">{a.code} · {a.question_code}</span>
                          <span className="mt-0.5 block truncate text-[12.5px] text-fg-muted">{a.title.split(": ")[1]}</span>
                          <span className="mt-0.5 block text-[11px] text-fg-subtle">{a.first_detectable_slot ? `Detectable from slot ${a.first_detectable_slot} · ` : ""}{a.status}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {d && <div className="flex gap-2 border-t border-line px-5 py-3">
                {(["critical", "high", "medium", "low"] as const).map((s) => <Badge key={s} tone={s === "low" ? "info" : s === "medium" ? "warn" : "danger"}>{d.alert_counts[s]} {s}</Badge>)}
              </div>}
            </Card>
          </div>

          <div className="mt-5 grid gap-5 lg:grid-cols-3">
            <Card>
              <CardHeader title="Target difficulty distribution" icon={<Layers />} description="Approved + pending items by section and target band" />
              <CardBody>
                {q.isLoading ? <LoadingRows rows={4} /> : (
                  <>
                    <div className="h-[200px]">
                      <ResponsiveContainer>
                        <BarChart data={diffData} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
                          <CartesianGrid stroke={C.grid} vertical={false} />
                          <XAxis dataKey="section" {...axis} />
                          <YAxis {...axis} allowDecimals={false} />
                          <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(127,135,160,0.08)" }} />
                          {(["easy", "medium", "hard"] as const).map((b) => <Bar key={b} dataKey={b} name={titleCase(b)} stackId="a" fill={BAND_COLORS[b]} fillOpacity={0.8} maxBarSize={44} />)}
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="mt-2"><Legend items={(["easy", "medium", "hard"] as const).map((b) => ({ label: titleCase(b), color: BAND_COLORS[b] }))} /></div>
                    {d && Object.keys(d.difficulty.observed_rasch).length > 0 && (
                      <p className="mt-3 text-[12px] text-fg-muted">Observed (Rasch b) bands among calibrated items:{" "}
                        {(["easy", "medium", "hard"] as const).map((b) => `${b} ${d.difficulty.observed_rasch[b] ?? 0}`).join(" · ")}</p>
                    )}
                  </>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Variant calibration status" icon={<FlaskConical />}
                description={d?.calibration.run_id ? `Run #${d.calibration.run_id} · ${fmtDate(d.calibration.created_at)}` : "No calibration run"} />
              <CardBody className="space-y-3">
                {q.isLoading ? <LoadingRows rows={4} /> : calData.map((c) => {
                  const total = calData.reduce((a, b) => a + b.n, 0) || 1;
                  return (
                    <div key={c.key}>
                      <div className="mb-1 flex justify-between text-[12.5px]"><span className="text-fg-muted">{c.name}</span><span className="tabular text-fg">{c.n}</span></div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full" style={{ width: `${(100 * c.n) / total}%`, background: CAL_COLOR[c.key] }} /></div>
                    </div>
                  );
                })}
                <p className="pt-1 text-[11.5px] text-fg-subtle">Equivalence requires the whole 90% CI of the difficulty difference to fall inside the configured tolerance (TOST); a non-significant difference alone is never treated as equivalence.</p>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Form overlap" icon={<Boxes />} description={d?.overlap ? `${d.overlap.drive} · assembly run #${d.overlap.run_id}` : "No assembled drive"}
                actions={<Button size="sm" variant="ghost" asChild><Link to="/assembler">Assembler<ArrowUpRight /></Link></Button>} />
              <CardBody>
                {!d?.overlap ? (q.isLoading ? <LoadingRows rows={4} /> : <EmptyState title="No forms assembled yet" />) : (
                  <>
                    <div className="grid grid-cols-3 gap-3 text-center">
                      <div><div className="text-[22px] font-semibold tabular">{d.overlap.forms}</div><div className="text-[11.5px] text-fg-subtle">Forms</div></div>
                      <div><div className="text-[22px] font-semibold tabular">{d.overlap.max_adjacent_pct}%</div><div className="text-[11.5px] text-fg-subtle">Max adjacent</div></div>
                      <div><div className="text-[22px] font-semibold tabular">{d.overlap.limit_pct}%</div><div className="text-[11.5px] text-fg-subtle">Limit</div></div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-1">
                      {d.overlap.pairs.map((p: any) => (
                        <span key={`${p.a}-${p.b}`} title={`S${p.slot_a}↔S${p.slot_b}: ${p.shared} shared, Jaccard ${p.jaccard}`}
                          className={`rounded px-1.5 py-0.5 font-mono text-[10.5px] ${p.constraint_ok ? "bg-ok-soft text-ok" : "bg-danger-soft text-danger"}`}>S{p.slot_a}↔{p.slot_b} {p.smaller_form_pct}%</span>
                      ))}
                    </div>
                    <p className="mt-3 flex items-center gap-1.5 text-[12.5px] text-ok"><CheckCircle2 className="size-3.5" />{d.overlap.all_ok ? "All adjacent-slot constraints verified" : "Constraint violations present"}</p>
                  </>
                )}
              </CardBody>
            </Card>
          </div>

          <div className="mt-5 grid gap-5 lg:grid-cols-3">
            <Card>
              <CardHeader title="Exposure risk" icon={<Radar />} description="Approved and quarantined items" actions={<Button size="sm" variant="ghost" asChild><Link to="/exposure">Details<ArrowUpRight /></Link></Button>} />
              <CardBody>
                {d && (
                  <>
                    <div className="h-[110px]">
                      <ResponsiveContainer>
                        <BarChart data={["low", "elevated", "high"].map((l) => ({ l: titleCase(l), n: d.exposure.levels[l] ?? 0, k: l }))} layout="vertical" margin={{ left: 8, right: 16 }}>
                          <XAxis type="number" hide />
                          <YAxis type="category" dataKey="l" {...axis} width={64} />
                          <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(127,135,160,0.08)" }} />
                          <Bar dataKey="n" name="Items" radius={[0, 4, 4, 0]} maxBarSize={18}>
                            {["low", "elevated", "high"].map((k) => <Cell key={k} fill={k === "low" ? C.ok : k === "elevated" ? C.warn : C.danger} />)}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <ul className="mt-3 space-y-2">
                      {d.exposure.top.slice(0, 4).map((t: any) => (
                        <li key={t.id} className="flex items-center gap-2 text-[12.5px]">
                          <span className="w-36 truncate font-mono text-fg">{t.code}</span>
                          <Progress value={t.score} tone={t.level === "high" ? "danger" : "warn"} className="flex-1" />
                          <span className="w-8 text-right tabular text-fg-muted">{Math.round(t.score)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Review pipeline" icon={<ClipboardList />} actions={<Button size="sm" variant="ghost" asChild><Link to="/review">Open queue<ArrowUpRight /></Link></Button>} />
              <CardBody className="space-y-2.5">
                {d && Object.entries(d.status_breakdown as Record<string, number>).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-[13px]">
                    <StatusBadge kind="question" value={k} />
                    <span className="tabular text-fg">{fmtInt(v)}</span>
                  </div>
                ))}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Recent activity" icon={<Activity />} actions={<Button size="sm" variant="ghost" asChild><Link to="/settings?tab=audit">Audit log<ArrowUpRight /></Link></Button>} />
              <ul className="max-h-[300px] divide-y divide-line overflow-y-auto">
                {d?.activity.map((e: any) => (
                  <li key={e.id} className="px-5 py-2.5">
                    <div className="text-[12.5px] text-fg">{e.summary}</div>
                    <div className="mt-0.5 text-[11px] text-fg-subtle">{e.actor} · {timeAgo(e.at)}</div>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <SystemHealth />
        </>
      )}
    </div>
  );
}

function SystemHealth() {
  const ready = useQuery({ queryKey: ["ready"], queryFn: () => api<any>("/ready"), refetchInterval: 30_000 });
  const ver = useQuery({ queryKey: ["version"], queryFn: () => api<any>("/version") });
  const demo = useQuery({ queryKey: ["demo-status"], queryFn: () => api<any>("/demo-status") });
  const ok = ready.data?.status === "ready";
  return (
    <Card className="mt-5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 text-[12.5px] text-fg-muted">
        <span className="flex items-center gap-2"><span className={`size-2 rounded-full ${ok ? "bg-ok" : "bg-danger"}`} />API {ok ? "ready" : ready.isLoading ? "checking…" : "unavailable"}</span>
        <span>DB latency {ready.data?.db_latency_ms ?? "—"} ms</span>
        <span>Migration {ready.data?.migration ?? "—"}</span>
        <span>{ver.data ? `${ver.data.name} v${ver.data.version} (${ver.data.env})` : ""}</span>
        <span>LLM provider: {demo.data?.llm?.configured ? demo.data.llm.provider : "not configured — deterministic templates active"}</span>
      </div>
    </Card>
  );
}
