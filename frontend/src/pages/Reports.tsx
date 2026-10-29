import { useQuery } from "@tanstack/react-query";
import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { ErrorState, LoadingRows, PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader, Input, Label } from "@/components/ui/primitives";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, download, qs } from "@/lib/api";
import { cn, SECTION_LABEL } from "@/lib/utils";

export default function Reports() {
  const tpl = useQuery({ queryKey: ["report-templates"], queryFn: () => api<any[]>("/reports/templates") });
  const [kind, setKind] = useState("question_bank");
  const [section, setSection] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const f = { section, date_from: from ? `${from}T00:00:00` : undefined, date_to: to ? `${to}T23:59:59` : undefined };
  const prev = useQuery({ queryKey: ["report-preview", kind, f], queryFn: () => api<any>(`/reports/${kind}/preview${qs(f)}`) });
  const dl = (fmt: string) => download(`/reports/${kind}.${fmt}${qs(f)}`, `${kind}.${fmt}`).then((n) => toast.success(`Downloaded ${n}`)).catch((e) => toast.error(e.message));
  return (
    <div>
      <PageHeader eyebrow="Governance" title="Analytics & reports" description="Every export carries a generation timestamp, data provenance and insufficient-evidence warnings. CSV cells are protected against formula injection." />
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <Card className="h-fit"><CardHeader title="Templates" icon={<FileText />} />
          <ul className="p-2">{(tpl.data ?? []).map((t) => (
            <li key={t.id}><button onClick={() => setKind(t.id)} className={cn("w-full rounded-md px-3 py-2 text-left hover:bg-surface-2", kind === t.id && "bg-accent-soft")}>
              <div className="text-[13px] font-medium">{t.title}</div><div className="text-[11.5px] text-fg-muted">{t.description}</div></button></li>))}</ul>
        </Card>
        <div className="space-y-5">
          <Card><CardBody className="flex flex-wrap items-end gap-3">
            <div><Label>Section</Label><Select ariaLabel="Section" value={section} onChange={setSection} options={[{ value: "all", label: "All sections" }, ...["QUANT", "LOGICAL", "VERBAL"].map((s) => ({ value: s, label: SECTION_LABEL[s] }))]} /></div>
            <div><Label htmlFor="rf">From</Label><Input id="rf" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
            <div><Label htmlFor="rt">To</Label><Input id="rt" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
            <div className="ml-auto flex gap-2">{["csv", "json", "pdf"].map((x) => <Button key={x} variant={x === "csv" ? "primary" : "outline"} onClick={() => dl(x)}><Download />{x.toUpperCase()}</Button>)}</div>
          </CardBody></Card>
          <Card>
            <CardHeader title={prev.data?.title ?? "Preview"} description={prev.data ? `${prev.data.total_rows} rows · generated ${prev.data.generated_at} (first 50 shown)` : ""} />
            {prev.isError ? <ErrorState error={prev.error} /> : prev.isLoading ? <LoadingRows /> : (
              <>
                <CardBody className="space-y-1 text-[12px]">
                  {prev.data.provenance.map((p: string) => <div key={p} className="text-fg-muted">Provenance: {p}</div>)}
                  {prev.data.warnings.map((w: string) => <div key={w} className="text-warn">Warning: {w}</div>)}
                </CardBody>
                <Table><THead><tr>{prev.data.columns.map((c: string) => <Th key={c}>{c}</Th>)}</tr></THead>
                  <tbody>{prev.data.rows.map((r: any[], i: number) => <Tr key={i}>{r.map((v, j) => <Td key={j} className="max-w-[240px] truncate text-[12px]">{v == null ? "—" : String(v)}</Td>)}</Tr>)}</tbody></Table>
              </>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
