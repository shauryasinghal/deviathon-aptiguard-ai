import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { AuthLayout, GoogleButton, OrDivider, PasswordInput, useProviders } from "@/components/auth/AuthParts";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({
  name: z.string().trim().min(1, "Enter your name").max(80, "At most 80 characters"),
  email: z.string().trim().email("Enter a valid email"),
  password: z.string().min(12, "Use at least 12 characters").refine((v) => new TextEncoder().encode(v).length <= 72, "Use at most 72 bytes"),
  confirm: z.string(),
}).refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Form = z.infer<typeof schema>;

export default function Register() {
  const { register: signUp } = useAuth();
  const nav = useNavigate();
  const providers = useProviders();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  const closed = providers.data && !providers.data.registration;

  const onSubmit = async (v: Form) => {
    setServerError(null);
    try {
      await signUp(v.name, v.email, v.password); // role and organisation are decided by the server, never sent
      toast.success("Account created");
      nav("/assessment", { replace: true });
    } catch (e) {
      setServerError(e instanceof ApiError ? e.message : "Sign-up failed");
    }
  };

  return (
    <AuthLayout footer="Accounts created here are candidate accounts. Staff accounts are issued by an administrator.">
      <h1 className="text-[24px] font-semibold tracking-tight">Create your account</h1>
      <p className="mt-1 text-sm text-fg-muted">Register as a candidate with your email, or continue with Google.</p>
      {closed && (
        <p role="status" className="mt-4 flex items-start gap-2 rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />Sign-up is currently closed on this server. Ask your administrator for an account.
        </p>
      )}
      {serverError && <p role="alert" className="mt-4 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{serverError}</p>}
      <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4" noValidate>
        <div>
          <Label htmlFor="name">Full name</Label>
          <Input id="name" autoComplete="name" aria-invalid={!!errors.name} {...register("name")} />
          <FieldError>{errors.name?.message}</FieldError>
        </div>
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
          <FieldError>{errors.email?.message}</FieldError>
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <PasswordInput id="password" autoComplete="new-password" aria-invalid={!!errors.password} aria-describedby="pw-hint" {...register("password")} />
          <p id="pw-hint" className="mt-1 text-[11.5px] text-fg-subtle">At least 12 characters. Avoid your name or email.</p>
          <FieldError>{errors.password?.message}</FieldError>
        </div>
        <div>
          <Label htmlFor="confirm">Confirm password</Label>
          <PasswordInput id="confirm" autoComplete="new-password" aria-invalid={!!errors.confirm} {...register("confirm")} />
          <FieldError>{errors.confirm?.message}</FieldError>
        </div>
        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting} disabled={!!closed}>Create account<ArrowRight /></Button>
      </form>
      <OrDivider />
      <GoogleButton label="Sign up with Google" enabled={!!providers.data?.google && !closed} />
      <p className="mt-5 text-center text-[13px] text-fg-muted">
        Already have an account? <Link to="/login" className="font-medium text-accent hover:underline">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
