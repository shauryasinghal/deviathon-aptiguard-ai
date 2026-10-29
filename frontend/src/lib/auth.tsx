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
};

type AuthCtx = {
  user: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  logout: () => void;
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

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: Me }>("/auth/login", { body: { email, password } });
    tokenStore.set(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const value = useMemo<AuthCtx>(
    () => ({ user, loading, login, logout, can: (p) => !!user?.permissions.includes(p) }),
    [user, loading, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
