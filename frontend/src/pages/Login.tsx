import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Info } from "lucide-react";
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
  const { register, handleSubmit, setValue, setFocus, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = async (v: Form) => {
    try {
      const u = await login(v.email, v.password);
      toast.success(`Signed in as ${u.name}`);
      nav(params.get("next") ?? (u.role === "candidate" ? "/assessment" : "/dashboard"), { replace: true });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Sign-in failed");
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
            </div>
            <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Sign in<ArrowRight /></Button>
          </form>
          {demo.data?.demo_mode && (
            <div className="mt-8">
              <div className="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-fg-subtle">Demo accounts</div>
              <div className="grid grid-cols-1 gap-1.5">
                {demo.data.demo_accounts.map((a: any) => (
                  <button key={a.email} type="button" onClick={() => { setValue("email", a.email); setFocus("password"); }}
                    className="flex items-center justify-between rounded-md border border-line bg-surface-2 px-3 py-2 text-left text-[13px] hover:border-line-strong">
                    <span className="font-mono text-[12px] text-fg">{a.email}</span>
                    <span className="text-[11.5px] text-fg-muted">{a.role}</span>
                  </button>
                ))}
              </div>
              <p className="mt-3 flex items-start gap-1.5 text-[12px] text-fg-subtle"><Info className="mt-0.5 size-3.5 shrink-0" />
                Local demo credentials are documented in the README (“Demo accounts”). Demo mode is disabled with DEMO_MODE=false.</p>
            </div>
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
