import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { AuthLayout, PasswordInput } from "@/components/auth/AuthParts";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";

const schema = z.object({
  password: z.string().min(12, "Use at least 12 characters").refine((v) => new TextEncoder().encode(v).length <= 72, "Use at most 72 bytes"),
  confirm: z.string(),
}).refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Form = z.infer<typeof schema>;

export default function ResetPassword() {
  const [params] = useSearchParams();
  const [token] = useState(() => params.get("token") ?? ""); // keep it in memory only
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  // the secret is removed from the address bar and browser history as soon as it has been read
  useEffect(() => { if (token) window.history.replaceState(null, "", window.location.pathname); }, [token]);

  const onSubmit = async (v: Form) => {
    setError(null);
    try {
      await api("/auth/password/reset", { body: { token, password: v.password } });
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reset the password");
    }
  };

  return (
    <AuthLayout>
      <h1 className="text-[24px] font-semibold tracking-tight">Choose a new password</h1>
      {!token ? (
        <p role="alert" className="mt-6 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger">
          This reset link is missing or incomplete. <Link to="/forgot-password" className="underline">Request a new one</Link>.
        </p>
      ) : done ? (
        <div className="mt-6 space-y-4" role="status">
          <p className="flex items-start gap-2 rounded-md border border-ok/30 bg-ok-soft px-3 py-2 text-[13px] text-ok"><CheckCircle2 className="mt-0.5 size-4 shrink-0" />
            Password updated. All other sessions were signed out.</p>
          <Button asChild variant="primary" className="w-full"><Link to="/login">Sign in</Link></Button>
        </div>
      ) : (
        <>
          {error && <p role="alert" className="mt-4 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}{" "}
            <Link to="/forgot-password" className="underline">Request a new link</Link></p>}
          <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4" noValidate>
            <div>
              <Label htmlFor="password">New password</Label>
              <PasswordInput id="password" autoComplete="new-password" aria-invalid={!!errors.password} {...register("password")} />
              <FieldError>{errors.password?.message}</FieldError>
            </div>
            <div>
              <Label htmlFor="confirm">Confirm new password</Label>
              <PasswordInput id="confirm" autoComplete="new-password" aria-invalid={!!errors.confirm} {...register("confirm")} />
              <FieldError>{errors.confirm?.message}</FieldError>
            </div>
            <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Update password</Button>
          </form>
        </>
      )}
    </AuthLayout>
  );
}
