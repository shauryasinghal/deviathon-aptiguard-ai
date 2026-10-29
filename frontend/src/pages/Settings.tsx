import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { ErrorState, FilterBar, KeyValue, LoadingRows, PageHeader, Pagination } from "@/components/ui/page";
import { Card, CardBody, CardHeader, Input, Label } from "@/components/ui/primitives";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, titleCase } from "@/lib/utils";

export default function Settings() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const s = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/settings") });
  return (
    <div>
      <PageHeader eyebrow="Governance" title="Settings & audit" description="Assessment policies, model-provider status and the tamper-evident (hash-chained) audit trail. Policies marked “not enforced” have no effect yet." />
      <Tabs defaultValue={params.get("tab") ?? "policies"}>
        <TabsList className="mb-5"><TabsTrigger value="policies">Policies</TabsTrigger><TabsTrigger value="system">System</TabsTrigger>
          {can("audit.read") && <TabsTrigger value="audit">Audit log</TabsTrigger>}</TabsList>
        <TabsContent value="policies">
          {s.isError ? <Card><ErrorState error={s.error} /></Card> : !s.data ? <Card><LoadingRows /></Card> : (
            <div className="grid gap-5 lg:grid-cols-2">
              {Object.entries(s.data.policies).map(([k, v]) => <PolicyCard key={k} name={k} values={v as any} canEdit={s.data.can_manage} inactive={s.data.inactive_fields?.[k] ?? {}} />)}
            </div>
          )}
        </TabsContent>
        <TabsContent value="system">
          {s.data && <div className="grid gap-5 lg:grid-cols-2">
            <Card><CardHeader title="Model provider" /><CardBody><KeyValue cols={2} items={[["Provider", s.data.model_provider.provider], ["Configured", s.data.model_provider.configured ? "yes" : "no"],
              ["Model", s.data.model_provider.model], ["API key", s.data.model_provider.api_key], ["Fallback", s.data.model_provider.fallback]]} /></CardBody></Card>
            <Card><CardHeader title="Security (prototype)" /><CardBody><KeyValue cols={1} items={[["Auth", s.data.security.auth], ["Insecure dev secret in use", s.data.security.insecure_dev_secret ? "yes — set JWT_SECRET" : "no"],
              ["CORS origins", s.data.security.cors_origins.join(", ")], ["Upload limit", `${s.data.security.max_upload_mb} MB`], ["Database", s.data.database]]} /></CardBody></Card>
            {can("demo.reset") && <DemoReset />}
          </div>}
        </TabsContent>
        {can("audit.read") && <TabsContent value="audit"><Audit /></TabsContent>}
      </Tabs>
    </div>
  );
}

function PolicyCard({ name, values, canEdit, inactive }: { name: string; values: Record<string, any>; canEdit: boolean; inactive: Record<string, string> }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, any>>(values);
  const m = useMutation({
    mutationFn: () => {
      const changed: Record<string, any> = {};
      for (const [k, v] of Object.entries(draft)) if (!(k in inactive) && JSON.stringify(v) !== JSON.stringify(values[k])) changed[k] = typeof values[k] === "number" ? Number(v) : v;
      return api(`/settings/policies/${name}`, { method: "PUT", body: { values: changed } });
    },
    onSuccess: () => { toast.success(`${titleCase(name)} policy saved`); qc.invalidateQueries(); },
    onError: (e: ApiError) => toast.error(e.message),
  });
  return (
    <Card><CardHeader title={`${titleCase(name)} policy`} actions={canEdit && <Button size="sm" variant="primary" loading={m.isPending} onClick={() => m.mutate()}><Save />Save</Button>} />
      <CardBody className="grid grid-cols-2 gap-3">
        {Object.entries(draft).map(([k, v]) => (
          <div key={k}><Label htmlFor={`${name}-${k}`}>{titleCase(k)}{k in inactive && <span className="ml-1.5 rounded border border-line px-1 text-[10.5px] font-normal uppercase tracking-wide text-fg-subtle" title={inactive[k]}>not enforced</span>}</Label>
            {k in inactive ? <Input id={`${name}-${k}`} disabled value={String(v)} aria-describedby={`${name}-${k}-why`} />
              : typeof v === "boolean" ? <select id={`${name}-${k}`} disabled={!canEdit} value={String(v)} onChange={(e) => setDraft({ ...draft, [k]: e.target.value === "true" })} className="h-9 w-full rounded-md border border-line-strong bg-surface-2 px-2 text-sm"><option value="true">true</option><option value="false">false</option></select>
              : Array.isArray(v) ? <Input id={`${name}-${k}`} disabled value={v.join(", ")} />
                : <Input id={`${name}-${k}`} type="number" step="any" disabled={!canEdit} value={v} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />}
            {k in inactive && <p id={`${name}-${k}-why`} className="mt-1 text-[11.5px] text-fg-subtle">{inactive[k]}</p>}
          </div>
        ))}
      </CardBody></Card>
  );
}

function DemoReset() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const m = useMutation({ mutationFn: () => api<any>("/system/demo/reset", { method: "POST" }),
    onSuccess: (r) => { toast.success(`Demo data reset in ${r.seconds}s`); setOpen(false); qc.invalidateQueries(); }, onError: (e: ApiError) => toast.error(e.message) });
  return (
    <Card><CardHeader title="Demo data" description="Re-seed the deterministic synthetic dataset (seed 107)." />
      <CardBody><Button variant="danger" onClick={() => setOpen(true)}><RotateCcw />Reset demo data</Button></CardBody>
      <Dialog open={open} onOpenChange={setOpen} title="Reset all demo data?" description="All items, responses, alerts, forms and audit events are deleted and regenerated (~10 s). You will need to sign in again."
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="danger" loading={m.isPending} onClick={() => m.mutate()}>Reset</Button></>} />
    </Card>
  );
}

function Audit() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const a = useQuery({ queryKey: ["audit", q, page], queryFn: () => api<any>(`/audit${qs({ q, page, page_size: 50 })}`) });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: () => api<any>("/audit/verify"), enabled: false });
  return (
    <Card>
      <FilterBar><Input aria-label="Search audit" placeholder="Search summary or actor…" className="w-72" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Button size="sm" variant="outline" className="ml-auto" loading={verify.isFetching} onClick={() => verify.refetch()}>Verify integrity</Button>
        {verify.data && <span role="status" className={verify.data.ok ? "text-[12.5px] text-ok" : "text-[12.5px] text-danger"}>
          {verify.data.ok ? `Hash chain intact · ${verify.data.checked} events` : `Chain broken at event #${verify.data.broken_at_id} (${verify.data.reason})`}</span>}
      </FilterBar>
      {a.isError ? <ErrorState error={a.error} /> : a.isLoading ? <LoadingRows /> : (
        <Table><THead><tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Entity</Th><Th>Summary</Th></tr></THead>
          <tbody>{a.data.items.map((e: any) => <Tr key={e.id}><Td className="whitespace-nowrap text-[12px]">{fmtDate(e.at)}</Td><Td className="text-[12.5px]">{e.actor}</Td>
            <Td className="font-mono text-[12px]">{e.action}</Td><Td className="text-[12px]">{e.entity_type} {e.entity_id}</Td><Td className="text-[12.5px] text-fg-muted">{e.summary}</Td></Tr>)}</tbody></Table>
      )}
      {a.data && <Pagination page={page} pageSize={50} total={a.data.total} onPage={setPage} />}
    </Card>
  );
}
