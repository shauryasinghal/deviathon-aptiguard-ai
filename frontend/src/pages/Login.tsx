import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Info, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { AuthLayout, GOOGLE_ERRORS, GoogleButton, OrDivider, PasswordInput, useProviders } from "@/components/auth/AuthParts";
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
  const providers = useProviders();
  const { register, handleSubmit, setValue, watch, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  const [demoBusy, setDemoBusy] = useState<string | null>(null);
  const pw = watch("password") ?? "";
  const pwHasEdgeSpace = pw.length > 0 && pw !== pw.trim();
  const googleError = GOOGLE_ERRORS[params.get("error") ?? ""];
  useEffect(() => { if (googleError) toast.error(googleError); }, [googleError]);

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
    <AuthLayout>
      <h1 className="text-[24px] font-semibold tracking-tight">Sign in</h1>
      <p className="mt-1 text-sm text-fg-muted">Sign in with your email, with Google, or try a demo account.</p>
      {googleError && (
        <p role="alert" className="mt-4 flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />{googleError}
        </p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} className="mt-8 space-y-4" noValidate>
        <div>
          <Label htmlFor="email">Work email</Label>
          <Input id="email" type="email" autoComplete="username" aria-invalid={!!errors.email} {...register("email")} />
          <FieldError>{errors.email?.message}</FieldError>
        </div>
        <div>
          <div className="flex items-baseline justify-between">
            <Label htmlFor="password">Password</Label>
            <Link to="/forgot-password" className="text-[12px] text-accent hover:underline">Forgot password?</Link>
          </div>
          <PasswordInput id="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
          <FieldError>{errors.password?.message}</FieldError>
          {pwHasEdgeSpace && <p className="mt-1 text-xs text-warn" role="status">The password starts or ends with a space — check for a copy/paste artefact.</p>}
        </div>
        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Sign in<ArrowRight /></Button>
      </form>
      <OrDivider />
      <GoogleButton enabled={!!providers.data?.google} />
      <p className="mt-5 text-center text-[13px] text-fg-muted">
        New here? <Link to="/register" className="font-medium text-accent hover:underline">Sign up</Link>
      </p>
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
    </AuthLayout>
  );
}
