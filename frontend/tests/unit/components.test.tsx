import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusBadge, DifficultyPill } from "@/components/ui/status";
import { ErrorState, Pagination } from "@/components/ui/page";
import { ApiError, api, qs } from "@/lib/api";
import { fmtPct, fmtSigned, fmtNum } from "@/lib/utils";

describe("formatting", () => {
  it("formats numbers honestly", () => {
    expect(fmtPct(0.4567, 1)).toBe("45.7%");
    expect(fmtSigned(-0.25)).toBe("−0.25");
    expect(fmtNum(null)).toBe("—");
    expect(fmtPct(null)).toBe("—");
  });
  it("drops empty and 'all' filters from query strings", () => {
    expect(qs({ a: 1, b: "", c: "all", d: undefined, e: "x y" })).toBe("?a=1&e=x+y");
    expect(qs({})).toBe("");
  });
});

describe("status semantics", () => {
  it("distinguishes suspicion from confirmation", () => {
    render(<><StatusBadge kind="evidence" value="statistical_suspicion" /><StatusBadge kind="evidence" value="human_confirmed" /></>);
    expect(screen.getByText("Statistical suspicion")).toBeInTheDocument();
    expect(screen.getByText("Human-confirmed")).toBeInTheDocument();
  });
  it("labels form reassessment and missing values", () => {
    render(<><StatusBadge kind="form" value="needs_review" /><StatusBadge kind="leak" value={null} /></>);
    expect(screen.getByText("Needs reassessment")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
  it("exposes difficulty to assistive tech", () => {
    render(<DifficultyPill value="hard" />);
    expect(screen.getByLabelText("Difficulty hard")).toBeInTheDocument();
  });
});

describe("page states", () => {
  it("shows API error code and message, never a stack trace", () => {
    render(<ErrorState error={new ApiError(403, "forbidden", "Missing permission: leaks.read")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Missing permission: leaks.read");
    expect(screen.getByText("403 forbidden")).toBeInTheDocument();
  });
  it("paginates with accessible controls", () => {
    render(<Pagination page={1} pageSize={25} total={60} onPage={() => {}} />);
    expect(screen.getByText("1–25 of 60")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
    expect(screen.getByLabelText("Next page")).toBeEnabled();
  });
});

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("maps the backend error envelope to ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "conflict", message: "Attempt already submitted" } }), { status: 409 })));
    await expect(api("/x")).rejects.toMatchObject({ status: 409, code: "conflict", message: "Attempt already submitted" });
  });
  it("reports network failure without crashing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(api("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});
