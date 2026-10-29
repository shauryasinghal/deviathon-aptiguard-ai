/** Thin fetch client for /api/v1. Errors use the backend envelope {error: {code, message, details}}. */
const BASE = "/api/v1";
const TOKEN_KEY = "aptiguard.token";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Prototype note: the token lives in sessionStorage (cleared when the tab closes). Production should use
// httpOnly cookies from an identity provider; see docs/security-review.md.
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

type Opts = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal };

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(BASE + path, { method: opts.method ?? (body ? "POST" : "GET"), headers, body, signal: opts.signal });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the AptiGuard API. Is the backend running on port 8000?");
  }
  if (res.status === 401 && token) onUnauthorized?.();
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const e = (data as any)?.error;
    throw new ApiError(res.status, e?.code ?? "http_error", e?.message ?? `Request failed (${res.status})`, e?.details);
  }
  return data as T;
}

function safeJson(t: string) {
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}

/** Authenticated file download (reports). */
export async function download(path: string, fallbackName: string) {
  const token = tokenStore.get();
  const res = await fetch(BASE + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    const data = safeJson(await res.text()) as any;
    throw new ApiError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? "Download failed");
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return name;
}

export function qs(params: Record<string, unknown>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === "all") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
