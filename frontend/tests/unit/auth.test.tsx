import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toaster } from "sonner";
import { AuthProvider } from "@/lib/auth";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import AuthCallback from "@/pages/AuthCallback";

// minimal stand-ins for user-event (not a project dependency): drive react-hook-form inputs through change/click events
const userEvent = {
  type: async (el: HTMLElement, text: string) => { fireEvent.change(el, { target: { value: (el as HTMLInputElement).value + text } }); },
  clear: async (el: HTMLElement) => { fireEvent.change(el, { target: { value: "" } }); },
  click: async (el: HTMLElement) => { fireEvent.click(el); },
};

const DEMO = { demo_mode: true, demo_password: "demo-pw-for-tests", demo_accounts: [
  { email: "admin@aptiguard.demo", role: "Administrator" }, { email: "candidate1@aptiguard.demo", role: "Candidate" }] };
const PROVIDERS = (o: object = {}) => ({ password: true, google: true, registration: true, password_reset: true, demo_mode: true, ...o });
const SESSION = { access_token: "tok", user: { id: 1, email: "a@b.co", name: "Ada", role: "candidate", role_label: "Candidate", permissions: ["assessment.take"],
  organization: { id: 1, name: "Org" }, candidate_code: "CAND-1", auth_methods: { google: false } } };

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
let calls: { url: string; body: any }[] = [];

function mockApi(extra: Record<string, Handler> = {}, providers: object = {}) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace("/api/v1", "");
    calls.push({ url: path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (extra[path]) return extra[path](path, init);
    if (path === "/demo-status") return json(DEMO);
    if (path === "/auth/providers") return json(PROVIDERS(providers));
    return json({ error: { code: "not_found", message: "nope" } }, 404);
  }));
}

function renderAt(path: string, el = <Login />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}><AuthProvider><MemoryRouter initialEntries={[path]}>
      <Toaster />
      <Routes>
        <Route path="/login" element={<Login />} /><Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} /><Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/assessment" element={<div>candidate home</div>} /><Route path="/dashboard" element={<div>staff dashboard</div>} />
        <Route path="*" element={el} />
      </Routes></MemoryRouter></AuthProvider></QueryClientProvider>,
  );
}

beforeEach(() => { sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("login page: three methods coexist", () => {
  it("offers email/password, Google, sign up, forgot password and the demo accounts", async () => {
    mockApi();
    renderAt("/login");
    expect(await screen.findByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(async () => expect(await screen.findByRole("button", { name: /continue with google/i })).toBeEnabled());
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute("href", "/register");
    expect(screen.getByRole("link", { name: /forgot password/i })).toHaveAttribute("href", "/forgot-password");
    expect(await screen.findByRole("button", { name: /Sign in as Administrator/ })).toBeInTheDocument();
    expect(screen.getByText(/Demo mode is ON/i)).toBeInTheDocument();
  });

  it("disables Google (with a reason) when the server has no Google configuration, and demo login still works", async () => {
    mockApi({ "/auth/login": () => json(SESSION) }, { google: false });
    renderAt("/login");
    const g = await screen.findByRole("button", { name: /continue with google/i });
    await waitFor(() => expect(g).toBeDisabled());
    expect(screen.getByText(/not configured on this server/i)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /Sign in as Candidate/ }));
    await screen.findByText("candidate home");
    expect(calls.find((c) => c.url === "/auth/login")?.body).toEqual({ email: "candidate1@aptiguard.demo", password: "demo-pw-for-tests" });
  });

  it("falls back to password + demo sign-in against an older backend without /auth/providers", async () => {
    mockApi({ "/auth/providers": () => json({ error: { code: "not_found", message: "x" } }, 404) });
    renderAt("/login");
    expect(await screen.findByLabelText("Work email")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Sign in as Administrator/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeDisabled();
  });

  it("shows and hides the password, and signs in with email and password", async () => {
    mockApi({ "/auth/login": () => json({ ...SESSION, user: { ...SESSION.user, role: "analyst" } }) });
    renderAt("/login");
    const pw = await screen.findByLabelText("Password");
    expect(pw).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(pw).toHaveAttribute("type", "text");
    await userEvent.type(screen.getByLabelText("Work email"), "ada@example.com");
    await userEvent.type(pw, "s3cret-value");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("staff dashboard");
    expect(calls.find((c) => c.url === "/auth/login")?.body).toEqual({ email: "ada@example.com", password: "s3cret-value" });
  });

  it("shows a fixed, friendly message for Google error codes and nothing from the URL beyond the code", async () => {
    mockApi();
    renderAt("/login?error=google_account_exists");
    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
    cleanup();
    renderAt("/login?error=<script>alert(1)</script>");
    await screen.findByLabelText("Work email");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("starts Google sign-in by navigating to the backend endpoint (no secrets in the browser)", async () => {
    mockApi();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    renderAt("/login");
    const g = await screen.findByRole("button", { name: /continue with google/i });
    await waitFor(() => expect(g).toBeEnabled()); // enabled once /auth/providers reports Google as configured
    await userEvent.click(g);
    expect(assign).toHaveBeenCalledWith("/api/v1/auth/google/start");
  });
});

describe("registration", () => {
  it("validates the form, never sends a role or organisation, and signs the new candidate in", async () => {
    mockApi({ "/auth/register": () => json(SESSION, 201) });
    renderAt("/register");
    await userEvent.type(await screen.findByLabelText("Full name"), "Ada Lovelace");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-enough-pass");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different-long-pass");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Passwords do not match")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/auth/register")).toBe(false);
    await userEvent.clear(screen.getByLabelText("Confirm password"));
    await userEvent.type(screen.getByLabelText("Confirm password"), "a-long-enough-pass");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByText("candidate home");
    expect(calls.find((c) => c.url === "/auth/register")?.body).toEqual({ name: "Ada Lovelace", email: "ada@example.com", password: "a-long-enough-pass" });
  });

  it("rejects short passwords client-side and shows server errors (duplicate email)", async () => {
    mockApi({ "/auth/register": () => json({ error: { code: "email_taken", message: "An account with this email already exists" } }, 409) });
    renderAt("/register");
    await userEvent.type(await screen.findByLabelText("Full name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.type(screen.getByLabelText("Confirm password"), "short");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Use at least 12 characters")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Password")); await userEvent.clear(screen.getByLabelText("Confirm password"));
    await userEvent.type(screen.getByLabelText("Password"), "long-enough-password"); await userEvent.type(screen.getByLabelText("Confirm password"), "long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
  });

  it("explains when sign-up is closed and offers Google sign-up when it is open", async () => {
    mockApi({}, { registration: false });
    renderAt("/register");
    expect(await screen.findByText(/Sign-up is currently closed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create account/i })).toBeDisabled();
    cleanup();
    mockApi();
    renderAt("/register");
    const g = await screen.findByRole("button", { name: /sign up with google/i });
    await waitFor(() => expect(g).toBeEnabled());
  });
});

describe("password reset", () => {
  it("shows the same message whether or not the account exists", async () => {
    mockApi({ "/auth/password/forgot": () => json({ status: "accepted" }, 202) });
    renderAt("/forgot-password");
    await userEvent.type(await screen.findByLabelText("Email"), "someone@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send reset link/i }));
    expect(await screen.findByText(/If an account exists for that email/i)).toBeInTheDocument();
  });

  it("removes the token from the URL, requires matching strong passwords and posts the token once", async () => {
    mockApi({ "/auth/password/reset": () => json({ status: "password_updated" }) });
    const replace = vi.spyOn(window.history, "replaceState");
    renderAt("/reset-password?token=abcdefghij1234567890");
    await userEvent.type(await screen.findByLabelText("New password"), "brand-new-long-pass");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "brand-new-long-pass");
    await userEvent.click(screen.getByRole("button", { name: /update password/i }));
    expect(await screen.findByText(/Password updated/i)).toBeInTheDocument();
    expect(replace).toHaveBeenCalled();
    expect(calls.find((c) => c.url === "/auth/password/reset")?.body).toEqual({ token: "abcdefghij1234567890", password: "brand-new-long-pass" });
  });

  it("explains a missing link", async () => {
    mockApi();
    renderAt("/reset-password");
    expect(await screen.findByRole("alert")).toHaveTextContent(/missing or incomplete/i);
  });
});

describe("Google callback route", () => {
  it("exchanges the one-time ticket once, strips it from the URL and routes by role", async () => {
    mockApi({ "/auth/google/exchange": () => json({ ...SESSION, user: { ...SESSION.user, role: "candidate" } }) });
    const replace = vi.spyOn(window.history, "replaceState");
    renderAt("/auth/callback?ticket=one-time-ticket-123");
    await screen.findByText("candidate home");
    expect(calls.filter((c) => c.url === "/auth/google/exchange")).toHaveLength(1);
    expect(calls.find((c) => c.url === "/auth/google/exchange")?.body).toEqual({ ticket: "one-time-ticket-123" });
    expect(sessionStorage.getItem("aptiguard.token")).toBe("tok");
    expect(replace).toHaveBeenCalledWith(null, "", "/auth/callback"); // the ticket never stays in the address bar
  });

  it("sends errors back to the login page with the fixed code only", async () => {
    mockApi();
    renderAt("/auth/callback?error=google_denied");
    expect(await screen.findByRole("alert")).toHaveTextContent(/cancelled/i);
    expect(sessionStorage.getItem("aptiguard.token")).toBeNull();
  });

  it("does not sign in when the ticket is rejected", async () => {
    mockApi({ "/auth/google/exchange": () => json({ error: { code: "invalid_ticket", message: "This sign-in link is invalid or has expired" } }, 401) });
    renderAt("/auth/callback?ticket=stale-ticket-12345");
    await screen.findByLabelText("Work email");
    expect(sessionStorage.getItem("aptiguard.token")).toBeNull();
  });
});
