import { Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { homeFor } from "@/components/auth/AuthParts";
import { api, ApiError } from "@/lib/api";
import { type Session, useAuth } from "@/lib/auth";

/** Landing route for the Google redirect. Receives only a one-time ticket, a status or a fixed error code. */
export default function AuthCallback() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { applySession, refresh, user } = useAuth();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // React StrictMode runs effects twice; a ticket can only be used once
    started.current = true;
    const ticket = params.get("ticket"), error = params.get("error"), status = params.get("status");
    window.history.replaceState(null, "", "/auth/callback"); // never leave the ticket in the address bar / history
    (async () => {
      if (ticket) {
        try {
          const s = await api<Session>("/auth/google/exchange", { body: { ticket } });
          const me = applySession(s);
          toast.success(`Signed in as ${me.name}`);
          nav(homeFor(me.role), { replace: true });
        } catch (e) {
          toast.error(e instanceof ApiError ? e.message : "Google sign-in failed");
          nav("/login?error=google_failed", { replace: true });
        }
      } else if (status === "linked") {
        await refresh();
        toast.success("Google account linked");
        nav(user ? homeFor(user.role) : "/app", { replace: true });
      } else {
        nav(`/login?error=${encodeURIComponent(error ?? "google_failed")}`, { replace: true });
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="grid h-full min-h-[50vh] place-items-center text-fg-subtle" role="status" aria-label="Completing sign-in">
      <Loader2 className="size-5 animate-spin" />
    </div>
  );
}
