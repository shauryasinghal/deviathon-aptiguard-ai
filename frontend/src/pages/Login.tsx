import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Info } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Password is required") });
type Form = z.infer<typeof schema>;

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const demo = useQuery({ queryKey: ["demo-status"], queryFn: () => api<any>("/demo-status") });
  const { register, handleSubmit, setValue, watch, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  const [demoBusy, setDemoBusy] = useState<string | null>(null);
  const pw = watch("password") ?? "";
  const pwHasEdgeSpace = pw.length > 0 && pw !== pw.trim();

  const onSubmit = async (v: Form) => {
    try {
      const u = await login(v.email.trim(), v.password);
      toast.success(`Signed in as ${u.name}`);
      // honour ?next only if it belongs to this role's area (and is an in-app path)
      const next = params.get("next");
      const home = u.role === "candidate" ? "/assessment" : "/dashboard";
      const ok = next && next.startsWith("/") && !next.startsWith("//") && (u.role === "candidate") === next.startsWith("/assessment");
      nav(ok ? next : home, { replace: true });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Sign-in failed");
    }
  };

  const demoSignIn = async (email: string) => {
    setValue("email", email);
    setValue("password", demo.data.demo_password);
    setDemoBusy(email);
    try {
      await onSubmit({ email, password: demo.data.demo_password });
    } finally {
      setDemoBusy(null);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="flex flex-col justify-between border-r border-line bg-surface p-8 lg:p-12">
        <Link to="/" aria-label="Back to home"><Logo /></Link>
        <div className="mx-auto w-full max-w-sm py-12">
          <h1 className="text-[24px] font-semibold tracking-tight">Sign in</h1>
          <p className="mt-1 text-sm text-fg-muted">Use a demo account to explore each role.</p>
          <form onSubmit={handleSubmit(onSubmit)} className="mt-8 space-y-4" noValidate>
            <div>
              <Label htmlFor="email">Work email</Label>
              <Input id="email" type="email" autoComplete="username" aria-invalid={!!errors.email} {...register("email")} />
              <FieldError>{errors.email?.message}</FieldError>
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
              <FieldError>{errors.password?.message}</FieldError>
              {pwHasEdgeSpace && <p className="mt-1 text-xs text-warn" role="status">The password starts or ends with a space — check for a copy/paste artefact.</p>}
            </div>
            <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Sign in<ArrowRight /></Button>
          </form>
          {demo.data?.demo_mode && demo.data?.demo_accounts && (
            <div className="mt-8">
              <div className="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-fg-subtle">Demo mode is ON — one-click sign-in</div>
              <div className="grid grid-cols-1 gap-1.5">
                {demo.data.demo_accounts.map((a: any) => (
                  <button key={a.email} type="button" disabled={!!demoBusy} onClick={() => demoSignIn(a.email)}
                    aria-label={`Sign in as ${a.role} (${a.email})`}
                    className="flex items-center justify-between rounded-md border border-line bg-surface-2 px-3 py-2 text-left text-[13px] hover:border-line-strong disabled:opacity-60">
                    <span className="font-mono text-[12px] text-fg">{a.email}</span>
                    <span className="text-[11.5px] text-fg-muted">{demoBusy === a.email ? "Signing in…" : `Sign in as ${a.role}`}</span>
                  </button>
                ))}
              </div>
              <p className="mt-3 flex items-start gap-1.5 text-[12px] text-fg-subtle"><Info className="mt-0.5 size-3.5 shrink-0" />
                Synthetic demo accounts. Shared demo password: <code className="font-mono text-fg-muted">{demo.data.demo_password}</code>. Hidden automatically when DEMO_MODE=false; never shown in production.</p>
            </div>
          )}
          {demo.data && !demo.data.demo_mode && (
            <p className="mt-8 text-[12px] text-fg-subtle">Demo mode is off. Use the credentials issued by your administrator.</p>
          )}
        </div>
        <p className="text-[12px] text-fg-subtle">Prototype authentication (JWT). Do not reuse real passwords.</p>
      </div>
      <div className="relative hidden overflow-hidden lg:block">
        <div className="grid-bg absolute inset-0" aria-hidden />
        <div className="absolute inset-0 bg-gradient-to-br from-accent-strong/15 via-transparent to-transparent" aria-hidden />
        <div className="relative flex h-full flex-col justify-center p-16">
          <blockquote className="max-w-md text-[22px] font-medium leading-snug tracking-tight text-fg">
            “Fairness across slots isn’t a feature you add later. It is a property you measure, enforce and prove.”
          </blockquote>
          <ul className="mt-10 space-y-3 text-sm text-fg-muted">
            <li>· Variants are verified, then <span className="text-fg">approved by a person</span>.</li>
            <li>· Forms are assembled under <span className="text-fg">explicit, checked constraints</span>.</li>
            <li>· Leak alerts carry <span className="text-fg">evidence, uncertainty and provenance</span>.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
