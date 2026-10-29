import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { forwardRef, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border border-line bg-surface shadow-card", className)} {...p} />;
}

export function CardHeader({ title, description, actions, className, icon }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string; icon?: ReactNode;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b border-line px-5 py-4", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 text-fg-subtle [&_svg]:size-4">{icon}</div>}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
          {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...p} />;
}

const tones = {
  neutral: "bg-surface-3 text-fg-muted border-line-strong",
  accent: "bg-accent-soft text-accent border-accent/25",
  ok: "bg-ok-soft text-ok border-ok/25",
  warn: "bg-warn-soft text-warn border-warn/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  info: "bg-info-soft text-info border-info/25",
  violet: "bg-violet/10 text-violet border-violet/25",
} as const;
export type Tone = keyof typeof tones;

export function Badge({ tone = "neutral", className, dot, children, ...p }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone; dot?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11.5px] font-medium leading-4", tones[tone], className)} {...p}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn("h-9 w-full rounded-md border border-line-strong bg-surface-2 px-3 text-sm text-fg placeholder:text-fg-subtle transition-colors focus:border-accent focus:outline-none focus-visible:outline-none disabled:opacity-60", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn("min-h-[84px] w-full rounded-md border border-line-strong bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none", className)} {...p} />
));
Textarea.displayName = "Textarea";

export function Label({ className, ...p }: HTMLAttributes<HTMLLabelElement> & { htmlFor?: string }) {
  return <label className={cn("mb-1.5 block text-[12.5px] font-medium text-fg-muted", className)} {...p} />;
}

export function FieldError({ children }: { children?: ReactNode }) {
  return children ? <p className="mt-1 text-xs text-danger" role="alert">{children}</p> : null;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} aria-hidden />;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted">{children}</kbd>;
}

export function Progress({ value, tone = "accent", className }: { value: number; tone?: "accent" | "ok" | "warn" | "danger"; className?: string }) {
  const bar = { accent: "bg-accent", ok: "bg-ok", warn: "bg-warn", danger: "bg-danger" }[tone];
  return (
    <ProgressPrimitive.Root value={value} className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}>
      <ProgressPrimitive.Indicator className={cn("h-full transition-all duration-500", bar)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </ProgressPrimitive.Root>
  );
}

export function Switch({ checked, onCheckedChange, id, label }: { checked: boolean; onCheckedChange: (v: boolean) => void; id?: string; label?: string }) {
  return (
    <SwitchPrimitive.Root id={id} checked={checked} onCheckedChange={onCheckedChange} aria-label={label}
      className="relative h-5 w-9 shrink-0 rounded-full border border-line-strong bg-surface-3 transition-colors data-[state=checked]:border-accent data-[state=checked]:bg-accent-strong">
      <SwitchPrimitive.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[17px]" />
    </SwitchPrimitive.Root>
  );
}

export function Tip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content side={side} sideOffset={6} className="z-[70] max-w-xs rounded-md border border-line-strong bg-surface-3 px-2.5 py-1.5 text-xs text-fg shadow-pop animate-fade-in">
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export function Separator({ className }: { className?: string }) {
  return <div className={cn("h-px w-full bg-line", className)} role="separator" />;
}

export function Mono({ className, ...p }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("font-mono text-[12.5px]", className)} {...p} />;
}
