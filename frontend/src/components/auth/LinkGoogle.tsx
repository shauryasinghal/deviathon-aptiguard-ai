import { useMutation } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProviders } from "./AuthParts";

/** Sign-in methods for the signed-in user. Google can only be attached from an authenticated session (never by an email match). */
export function LinkGoogle() {
  const { user } = useAuth();
  const providers = useProviders();
  const start = useMutation({
    mutationFn: () => api<{ authorization_url: string }>("/auth/google/link/start", { method: "POST" }),
    onSuccess: (r) => window.location.assign(r.authorization_url),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not start Google linking"),
  });
  if (!user || user.email.toLowerCase().endsWith("@aptiguard.demo")) return null; // demo accounts are never linkable
  if (!providers.data?.google) return null;
  const linked = !!user.auth_methods?.google;
  return (
    <Card>
      <CardHeader title="Sign-in methods" description="Your account can use a password, Google, or both." />
      <CardBody className="space-y-3 text-[13px]">
        {linked ? (
          <p className="flex items-center gap-2 text-ok"><CheckCircle2 className="size-4" />Google is linked to this account.</p>
        ) : (
          <>
            <p className="text-fg-muted">Link the Google account that uses <b className="text-fg">{user.email}</b>. You will be asked to approve access to your name and email only.</p>
            <Button variant="outline" loading={start.isPending} onClick={() => start.mutate()}>Link Google account</Button>
          </>
        )}
      </CardBody>
    </Card>
  );
}
