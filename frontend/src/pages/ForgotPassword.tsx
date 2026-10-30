import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { AuthLayout } from "@/components/auth/AuthParts";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";

const schema = z.object({ email: z.string().trim().email("Enter a valid email") });
type Form = z.infer<typeof schema>;

export default function ForgotPassword() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  const onSubmit = async (v: Form) => {
    setError(null);
    try {
      await api("/auth/password/forgot", { body: { email: v.email } });
      setSent(true); // the same message is shown whether or not the account exists
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError(e.message);
      else setSent(true);
    }
  };
  return (
    <AuthLayout>
      <h1 className="text-[24px] font-semibold tracking-tight">Reset your password</h1>
      {sent ? (
        <div className="mt-6 space-y-4" role="status">
          <p className="flex items-start gap-2 rounded-md border border-ok/30 bg-ok-soft px-3 py-2 text-[13px] text-ok"><CheckCircle2 className="mt-0.5 size-4 shrink-0" />
            If an account exists for that email, a reset link has been sent. The link expires shortly and works once.</p>
          <p className="text-[12.5px] text-fg-subtle">This server may not have email delivery configured; in that case ask your administrator.</p>
          <Link to="/login" className="text-[13px] font-medium text-accent hover:underline">Back to sign in</Link>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-fg-muted">Enter your email and we will send a reset link if an account exists.</p>
          {error && <p role="alert" className="mt-4 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
          <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4" noValidate>
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
              <FieldError>{errors.email?.message}</FieldError>
            </div>
            <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Send reset link</Button>
          </form>
          <p className="mt-5 text-center text-[13px]"><Link to="/login" className="text-accent hover:underline">Back to sign in</Link></p>
        </>
      )}
    </AuthLayout>
  );
}
