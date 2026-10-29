import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { FileQuestion, Search, ShieldAlert, Boxes } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { NAV } from "./nav";

type Result = { type: "question" | "alert" | "form"; id: number; label: string; detail: string; status: string; run_id?: number };

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const { can } = useAuth();
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 180);
    return () => clearTimeout(t);
  }, [q]);
  const { data, isFetching } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api<{ results: Result[] }>(`/search?q=${encodeURIComponent(debounced)}`),
    enabled: open && debounced.length >= 2,
  });
  const go = (to: string) => {
    onOpenChange(false);
    setQ("");
    nav(to);
  };
  const icon = { question: <FileQuestion />, alert: <ShieldAlert />, form: <Boxes /> };
  const target = (r: Result) =>
    r.type === "question" ? `/questions?open=${r.id}` : r.type === "alert" ? `/leaks?alert=${r.id}` : `/assembler?run=${r.run_id ?? ""}`;
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 animate-fade-in" />
        <DialogPrimitive.Content className="fixed left-1/2 top-[14vh] z-50 w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-line-strong bg-surface shadow-pop animate-fade-in">
          <DialogPrimitive.Title className="sr-only">Search and navigate</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">Search questions, alerts and forms, or jump to a page</DialogPrimitive.Description>
          <Command shouldFilter={false} className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-fg-subtle">
            <div className="flex items-center gap-2 border-b border-line px-4">
              <Search className="size-4 text-fg-subtle" />
              <Command.Input value={q} onValueChange={setQ} placeholder="Search item codes, stems, alerts, forms… or jump to a page"
                className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-fg-subtle" />
              {isFetching && <span className="text-xs text-fg-subtle">…</span>}
            </div>
            <Command.List className="max-h-[50vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-fg-muted">
                {debounced.length < 2 ? "Type at least two characters" : "No matches"}
              </Command.Empty>
              {data?.results?.length ? (
                <Command.Group heading="Results">
                  {data.results.map((r) => (
                    <Command.Item key={`${r.type}-${r.id}`} value={`${r.type}-${r.id}`} onSelect={() => go(target(r))}
                      className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm data-[selected=true]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-fg-subtle">
                      {icon[r.type]}
                      <span className="font-mono text-[12.5px] text-fg">{r.label}</span>
                      <span className="truncate text-fg-muted">{r.detail}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}
              <Command.Group heading="Navigate">
                {NAV.flatMap((g) => g.items)
                  .filter((i) => can(i.perm) && i.label.toLowerCase().includes(q.toLowerCase()))
                  .map((i) => (
                    <Command.Item key={i.to} value={`nav-${i.to}`} onSelect={() => go(i.to)}
                      className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm data-[selected=true]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-fg-subtle">
                      <i.icon />{i.label}
                    </Command.Item>
                  ))}
              </Command.Group>
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
