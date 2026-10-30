import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { forwardRef, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";

export type Providers = { password: boolean; google: boolean; registration: boolean; password_reset: boolean; demo_mode: boolean };

/** What the server offers. An older backend without the endpoint (404) simply offers password sign-in only. */
export function useProviders() {
  return useQuery<Providers>({
    queryKey: ["auth-providers"],
    queryFn: () => api<Providers>("/auth/providers").catch(() => ({ password: true, google: false, registration: false, password_reset: false, demo_mode: false })),
    staleTime: 60_000,
    retry: false,
  });
}

/** Fixed, human-readable messages for the error codes the backend puts in the Google callback redirect. */
export const GOOGLE_ERRORS: Record<string, string> = {
  google_denied: "Google sign-in was cancelled. You can try again or use your email and password.",
  google_state: "That sign-in attempt expired or was not started in this browser. Please try again.",
  google_failed: "Google sign-in could not be completed. Please try again.",
  google_not_configured: "Google sign-in is not configured on this server.",
  google_account_exists: "An account with this email already exists. Sign in with your password, then link Google from your account settings.",
  google_email_unverified: "Your Google email address is not verified, so it cannot be used to sign in.",
  google_registration_disabled: "Sign-up is currently closed. Ask your administrator for an account.",
  google_inactive: "This account is disabled. Contact your administrator.",
  google_demo_blocked: "Demo accounts cannot be used with Google sign-in.",
  google_link_mismatch: "The Google account's email must match your account email to link it.",
  google_link_conflict: "That Google account is already linked to a different account, or your account already has a Google account linked.",
};

export const homeFor = (role: string) => (role === "candidate" ? "/assessment" : "/dashboard");

export function AuthLayout({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="flex flex-col justify-between border-r border-line bg-surface p-8 lg:p-12">
        <Link to="/" aria-label="Back to home"><Logo /></Link>
        <div className="mx-auto w-full max-w-sm py-12">{children}</div>
        <p className="text-[12px] text-fg-subtle">{footer ?? "Prototype authentication (JWT). Do not reuse real passwords."}</p>
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

/** Password field with a show/hide toggle (keyboard accessible, announces its state). */
export const PasswordInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ id, ...p }, ref) => {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input id={id} ref={ref} type={show ? "text" : "password"} className="pr-10" {...p} />
      <button type="button" onClick={() => setShow((s) => !s)} aria-pressed={show} aria-controls={id}
        aria-label={show ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 grid w-10 place-items-center text-fg-subtle hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
});
PasswordInput.displayName = "PasswordInput";

function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" className="size-4" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 7l7.3 5.7c4.3-4 7-9.9 7-17.2z" />
      <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 0 1 0-9.4l-7.9-6.1a24 24 0 0 0 0 21.6l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.3-5.7c-2 1.4-4.7 2.3-8.6 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

/** Starts the server-side OAuth flow. Plain navigation: the browser never sees a client secret, code or Google token. */
export function GoogleButton({ label = "Continue with Google", enabled }: { label?: string; enabled: boolean }) {
  return (
    <div>
      <Button type="button" variant="outline" className="w-full" disabled={!enabled}
        onClick={() => window.location.assign("/api/v1/auth/google/start")}>
        <GoogleG />{label}
      </Button>
      {!enabled && <p className="mt-1 text-center text-[11.5px] text-fg-subtle">Google sign-in is not configured on this server.</p>}
    </div>
  );
}

export function OrDivider() {
  return (
    <div className="my-5 flex items-center gap-3 text-[11.5px] uppercase tracking-wider text-fg-subtle" role="separator">
      <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
    </div>
  );
}
