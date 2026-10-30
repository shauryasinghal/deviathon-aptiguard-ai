import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setUnauthorizedHandler, tokenStore } from "./api";

export type Me = {
  id: number;
  email: string;
  name: string;
  role: "admin" | "designer" | "reviewer" | "analyst" | "candidate";
  role_label: string;
  permissions: string[];
  organization: { id: number; name: string };
  candidate_code: string | null;
  auth_methods?: { google: boolean };
};

export type Session = { access_token: string; user: Me };

type AuthCtx = {
  user: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  register: (name: string, email: string, password: string) => Promise<Me>;
  applySession: (s: Session) => Me; // used after the one-time Google ticket has been exchanged
  refresh: () => Promise<void>;
  logout: () => void; // local only (used on 401)
  signOut: () => Promise<void>; // revokes all server-side sessions, then clears locally
  can: (perm: string) => boolean;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api<Me>("/auth/me")
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, [logout]);

  const applySession = useCallback((r: Session) => {
    tokenStore.set(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    return applySession(await api<Session>("/auth/login", { body: { email, password } }));
  }, [applySession]);

  const register = useCallback(async (name: string, email: string, password: string) => {
    return applySession(await api<Session>("/auth/register", { body: { name, email, password } }));
  }, [applySession]);

  const refresh = useCallback(async () => {
    try {
      setUser(await api<Me>("/auth/me"));
    } catch {
      /* a 401 is handled by the global unauthorized handler */
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      /* already expired/revoked or offline: local sign-out still proceeds */
    }
    logout();
  }, [logout]);

  const value = useMemo<AuthCtx>(
    () => ({ user, loading, login, register, applySession, refresh, logout, signOut, can: (p) => !!user?.permissions.includes(p) }),
    [user, loading, login, register, applySession, refresh, logout, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
