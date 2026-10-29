import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Check, ChevronDown, X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------ Dialog */
export function Dialog({ open, onOpenChange, title, description, children, footer, size = "md" }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; description?: ReactNode; children?: ReactNode;
  footer?: ReactNode; size?: "sm" | "md" | "lg";
}) {
  const w = { sm: "max-w-md", md: "max-w-lg", lg: "max-w-3xl" }[size];
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px] animate-fade-in" />
        <DialogPrimitive.Content className={cn("fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line-strong bg-surface shadow-pop animate-fade-in", w)}>
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <DialogPrimitive.Title className="text-[15px] font-semibold">{title}</DialogPrimitive.Title>
              {description && <DialogPrimitive.Description className="mt-1 text-[13px] text-fg-muted">{description}</DialogPrimitive.Description>}
            </div>
            <DialogPrimitive.Close className="rounded-md p-1 text-fg-subtle hover:bg-surface-2 hover:text-fg" aria-label="Close"><X className="size-4" /></DialogPrimitive.Close>
          </div>
          {children && <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>}
          {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ------------------------------------------------------------ Sheet (side drawer) */
export function Sheet({ open, onOpenChange, title, description, children, width = "max-w-2xl", side = "right" }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; description?: ReactNode; children: ReactNode;
  width?: string; side?: "right" | "left";
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 animate-fade-in" />
        <DialogPrimitive.Content className={cn("fixed inset-y-0 z-50 flex w-full flex-col border-line-strong bg-surface shadow-pop animate-slide-in",
          side === "right" ? "right-0 border-l" : "left-0 border-r", width)}>
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="truncate text-[15px] font-semibold">{title}</DialogPrimitive.Title>
              {description ? <DialogPrimitive.Description asChild><div className="mt-1 text-[13px] text-fg-muted">{description}</div></DialogPrimitive.Description>
                : <DialogPrimitive.Description className="sr-only">Details panel</DialogPrimitive.Description>}
            </div>
            <DialogPrimitive.Close className="rounded-md p-1 text-fg-subtle hover:bg-surface-2 hover:text-fg" aria-label="Close panel"><X className="size-4" /></DialogPrimitive.Close>
          </div>
          <div className="flex-1 overflow-y-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ------------------------------------------------------------ Select */
export type Option = { value: string; label: ReactNode };
export function Select({ value, onChange, options, placeholder = "Select…", className, ariaLabel, disabled }: {
  value: string; onChange: (v: string) => void; options: Option[]; placeholder?: string; className?: string; ariaLabel?: string; disabled?: boolean;
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onChange} disabled={disabled}>
      <SelectPrimitive.Trigger aria-label={ariaLabel} className={cn("inline-flex h-9 min-w-[130px] items-center justify-between gap-2 rounded-md border border-line-strong bg-surface-2 px-3 text-sm text-fg hover:border-fg-subtle/50 focus:border-accent focus:outline-none data-[placeholder]:text-fg-subtle", className)}>
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon><ChevronDown className="size-4 text-fg-subtle" /></SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={4} className="z-[60] max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-line-strong bg-surface-2 shadow-pop animate-fade-in">
          <SelectPrimitive.Viewport className="p-1">
            {options.map((o) => (
              <SelectPrimitive.Item key={o.value} value={o.value} className="relative flex cursor-pointer select-none items-center rounded-sm py-1.5 pl-7 pr-3 text-sm text-fg outline-none data-[highlighted]:bg-surface-3">
                <SelectPrimitive.ItemIndicator className="absolute left-2"><Check className="size-3.5 text-accent" /></SelectPrimitive.ItemIndicator>
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

/* ------------------------------------------------------------ Tabs */
export const Tabs = TabsPrimitive.Root;
export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return <TabsPrimitive.List className={cn("inline-flex items-center gap-1 rounded-lg border border-line bg-surface-2 p-1", className)}>{children}</TabsPrimitive.List>;
}
export function TabsTrigger({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <TabsPrimitive.Trigger value={value} className={cn("inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium text-fg-muted transition-colors hover:text-fg data-[state=active]:bg-surface-3 data-[state=active]:text-fg data-[state=active]:shadow-card [&_svg]:size-3.5", className)}>
      {children}
    </TabsPrimitive.Trigger>
  );
}
export const TabsContent = TabsPrimitive.Content;

/* ------------------------------------------------------------ Dropdown */
export const Menu = DropdownPrimitive.Root;
export const MenuTrigger = DropdownPrimitive.Trigger;
export function MenuContent({ children, align = "end", className }: { children: ReactNode; align?: "start" | "end"; className?: string }) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content align={align} sideOffset={6} className={cn("z-[60] min-w-[200px] rounded-md border border-line-strong bg-surface-2 p-1 shadow-pop animate-fade-in", className)}>
        {children}
      </DropdownPrimitive.Content>
    </DropdownPrimitive.Portal>
  );
}
export function MenuItem({ children, onSelect, danger, disabled }: { children: ReactNode; onSelect?: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <DropdownPrimitive.Item disabled={disabled} onSelect={onSelect} className={cn("flex cursor-pointer select-none items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px] outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-3 [&_svg]:size-4 [&_svg]:text-fg-subtle", danger ? "text-danger" : "text-fg")}>
      {children}
    </DropdownPrimitive.Item>
  );
}
export function MenuLabel({ children }: { children: ReactNode }) {
  return <DropdownPrimitive.Label className="px-2.5 py-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-subtle">{children}</DropdownPrimitive.Label>;
}
export const MenuSeparator = () => <DropdownPrimitive.Separator className="my-1 h-px bg-line" />;
