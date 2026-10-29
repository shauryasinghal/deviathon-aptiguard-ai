import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8001/api/v1";
const ROLE = { admin: "Administrator", designer: "Assessment Designer", reviewer: "Reviewer", analyst: "Psychometric Analyst", candidate: "Candidate" } as const;

async function signIn(page: Page, role: keyof typeof ROLE) {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(`^Sign in as ${ROLE[role]} `) }).click();
  await page.waitForURL(role === "candidate" ? "**/assessment" : "**/dashboard");
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await page.waitForURL(/\/login(\?.*)?$/);
}

async function apiToken(request: any, email: string) {
  const demo = await (await request.get(`${API}/demo-status`)).json();
  const r = await request.post(`${API}/auth/login`, { data: { email, password: demo.demo_password } });
  return (await r.json()).access_token as string;
}

test.describe.serial("AptiGuard core journeys", () => {
  test("1 · login, role-based routing, refresh, logout and route protection", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForURL("**/login?next=*");
    await signIn(page, "candidate");
    await expect(page.getByRole("heading", { name: "Your assessments" })).toBeVisible();
    await page.goto("/dashboard");
    await expect(page.getByText("You don't have access to this area")).toBeVisible();
    await page.goto("/assessment");
    await signOut(page);
    await page.goto("/assessment");
    await page.waitForURL("**/login?next=*");

    await signIn(page, "analyst");
    await expect(page.getByRole("heading", { name: "Assessment integrity overview" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Assessment integrity overview" })).toBeVisible();
    await signOut(page);

    // wrong password is rejected with the generic message
    await page.getByLabel("Work email").fill("analyst@aptiguard.demo");
    await page.getByLabel("Password").fill("not-the-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Invalid email or password")).toBeVisible();
  });

  test("2 · generate, validate, review and approve a variant", async ({ page, request }) => {
    const tok = await apiToken(request, "designer@aptiguard.demo");
    const src = (await (await request.get(`${API}/questions?q=QNT-SDT-E3-S`, { headers: { Authorization: `Bearer ${tok}` } })).json()).items[0];
    await signIn(page, "designer");
    await page.goto(`/variants?source=${src.id}`);
    await page.getByLabel("Variants").fill("1");
    await page.getByRole("button", { name: "Generate & validate" }).click();
    await expect(page.getByText("Sent to review queue")).toBeVisible();
    await expect(page.getByText(/Recomputed value = .*matches key/).first()).toBeVisible();
    const code = (await page.locator("text=/QNT-SDT-E3-V\\d\\d/").first().innerText()).match(/QNT-SDT-E3-V\d\d/)![0];
    await signOut(page);

    await signIn(page, "reviewer");
    await page.goto("/review");
    await page.getByRole("button", { name: new RegExp(code) }).click();
    await page.getByLabel("Comment (required to reject)").fill("Recomputed the answer independently; distractors are wrong.");
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText(new RegExp(`${code}: Approve`))).toBeVisible();

    const rtok = await apiToken(request, "reviewer@aptiguard.demo");
    const after = (await (await request.get(`${API}/questions?q=${code}`, { headers: { Authorization: `Bearer ${rtok}` } })).json()).items[0];
    expect(after.status).toBe("approved");
  });

  test("3+4 · assemble verified forms, publish, assign and complete a candidate attempt", async ({ page, request }) => {
    await signIn(page, "designer");
    await page.goto("/assembler");
    await page.getByLabel("Drive name").fill("E2E Drive");
    await page.getByLabel("Slots", { exact: true }).fill("3");
    await page.getByLabel("Random seed", { exact: true }).fill("4242");
    await page.getByRole("button", { name: "Generate forms" }).click();
    await expect(page.getByText("Verified", { exact: true })).toBeVisible();
    await expect(page.getByText("Overlap matrix")).toBeVisible();

    const tok = await apiToken(request, "designer@aptiguard.demo");
    const runs = await (await request.get(`${API}/assembly/runs`, { headers: { Authorization: `Bearer ${tok}` } })).json();
    const run = await (await request.get(`${API}/assembly/runs/${runs[0].id}`, { headers: { Authorization: `Bearer ${tok}` } })).json();
    expect(run.status).toBe("succeeded");
    for (const o of run.overlap) if (o.adjacent) expect(o.smaller_form_pct).toBeLessThanOrEqual(run.config.max_adjacent_overlap_pct);

    await page.getByRole("button", { name: "Publish draft forms" }).click();
    await expect(page.getByText(/Published 3 form/)).toBeVisible();
    await page.getByLabel("Candidate codes to assign").fill("DEMO-CAND-03");
    await page.getByRole("button", { name: "Assign", exact: true }).click();
    await expect(page.getByText(/Assigned 1/)).toBeVisible();
    await signOut(page);

    await page.getByRole("button", { name: /^Sign in as Candidate / }).isVisible();
    await page.getByLabel("Work email").fill("candidate3@aptiguard.demo");
    const demo = await (await request.get(`${API}/demo-status`)).json();
    await page.getByLabel("Password").fill(demo.demo_password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForURL("**/assessment");
    const row = page.locator("li", { hasText: "E2E Drive · Slot 1" });
    await row.getByRole("link", { name: "Start" }).click();
    await page.getByRole("button", { name: "Start / resume assessment" }).click();
    await expect(page.getByRole("timer")).toBeVisible();
    for (let i = 0; i < 3; i++) {
      await page.getByRole("radio").first().click();
      await expect(page.getByText("All answers saved")).toBeVisible();
      await page.getByRole("button", { name: "Next" }).click();
    }
    await page.getByRole("button", { name: "Submit" }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Submit" }).click();
    await expect(page.getByRole("heading", { name: "Assessment submitted" })).toBeVisible();
    await expect(page.getByText(/Scored on the server/)).toBeVisible();
  });

  test("5 · detect the simulated leak, review evidence, confirm and quarantine", async ({ page, request }) => {
    await signIn(page, "analyst");
    await page.goto("/leaks");
    await page.getByRole("button", { name: "Run detection" }).click();
    await expect(page.getByText(/Detection run #\d+/)).toBeVisible();
    await signOut(page);

    await signIn(page, "reviewer");
    await page.goto("/leaks");
    await page.getByRole("row", { name: /QNT-SDT-M1-S/ }).click();
    await expect(page.getByText("Text-match evidence (supplied dataset)")).toBeVisible();
    await expect(page.getByText("Performance evidence (ability-adjusted)")).toBeVisible();
    await page.getByLabel("Investigation note").fill("Verbatim copy with answer key posted after slot 2.");
    await page.getByRole("button", { name: "Confirm leak & quarantine" }).click();
    await expect(page.getByText(/→ confirmed/)).toBeVisible();

    const tok = await apiToken(request, "reviewer@aptiguard.demo");
    const q = (await (await request.get(`${API}/questions?q=QNT-SDT-M1-S&status=quarantined`, { headers: { Authorization: `Bearer ${tok}` } })).json()).items[0];
    expect(q.leak_status).toBe("confirmed");
  });

  test("6 · run calibration and export a report", async ({ page }) => {
    await signIn(page, "analyst");
    await page.goto("/calibration");
    await page.getByRole("button", { name: "Run calibration" }).click();
    await expect(page.getByText(/Calibration run #\d+ complete/)).toBeVisible();
    await expect(page.getByRole("cell", { name: /Insufficient data|Requires review|Within tolerance/ }).first()).toBeVisible();
    const dl = page.waitForEvent("download");
    await page.getByRole("button", { name: "Report CSV" }).click();
    expect((await dl).suggestedFilename()).toMatch(/aptiguard-calibration-.*\.csv/);
  });
});

test.describe.serial("integrity journeys", () => {
  test("7 · item quarantined during a live attempt → staff resolve the flag in the UI", async ({ page, request }) => {
    const auth = async (email: string) => ({ Authorization: `Bearer ${await apiToken(request, email)}` });
    const d = await auth("designer@aptiguard.demo");
    const run = await (await request.post(`${API}/assembly/runs`, { headers: d, data: {
      drive: "E2E Flag Drive", n_slots: 1, per_section: { QUANT: 3, LOGICAL: 3, VERBAL: 3 }, max_adjacent_overlap_pct: 0,
      max_slot_exposures: 5, min_slot_spacing: 0, seed: 777 } })).json();
    expect(run.status).toBe("succeeded");
    await request.post(`${API}/assembly/runs/${run.id}/publish`, { headers: d });
    const fid = run.forms[0].id;
    await request.post(`${API}/assembly/forms/${fid}/assignments`, { headers: d, data: { candidate_codes: ["DEMO-CAND-02"] } });
    const c = await auth("candidate2@aptiguard.demo");
    const at = await (await request.post(`${API}/assessment/forms/${fid}/attempts`, { headers: c })).json();
    const items = (await (await request.get(`${API}/assessment/forms/${fid}`, { headers: c })).json()).items;
    await request.put(`${API}/assessment/attempts/${at.attempt_id}/responses`, { headers: c,
      data: { answers: items.map((i: any) => ({ item_ref: i.item_ref, selected_key: "A" })) } });
    const r = await auth("reviewer@aptiguard.demo");
    const q = await request.post(`${API}/exposure/items/${run.forms[0].items[0].question_id}/quarantine`, { headers: r, data: { reason: "Exposed mid-slot (E2E)" } });
    expect(q.ok()).toBeTruthy();
    expect((await request.post(`${API}/assessment/attempts/${at.attempt_id}/submit`, { headers: c })).ok()).toBeTruthy();

    await signIn(page, "reviewer");
    await page.goto("/review?tab=flagged");
    const card = page.locator("div.rounded-lg", { hasText: `Attempt #${at.attempt_id}` }).first();
    await expect(card.getByText("Decision pending")).toBeVisible();
    await expect(card.getByText("Exposed mid-slot (E2E)")).toBeVisible();
    await card.getByLabel(/Use alternative score/).check();
    await card.getByLabel(/Reason \(required/).fill("Question was exposed before this candidate's slot began.");
    await card.getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByText(new RegExp(`Attempt #${at.attempt_id}: Use Alternative recorded`))).toBeVisible();
    const flagged = await (await request.get(`${API}/integrity/flagged-attempts?state=resolved`, { headers: await auth("reviewer2@aptiguard.demo") })).json();
    const me = flagged.items.find((x: any) => x.attempt_id === at.attempt_id);
    expect(me.decision).toBe("use_alternative");
    expect(me.official_score).not.toBeNull(); // official score kept
  });

  test("8 · an author cannot approve their own item (server-enforced, shown in UI)", async ({ page, request }) => {
    const a = { Authorization: `Bearer ${await apiToken(request, "admin@aptiguard.demo")}` };
    const created = await (await request.post(`${API}/questions`, { headers: a, data: {
      section: "LOGICAL", skill: "patterns", concept: "Odd one out", difficulty_target: "easy",
      stem: "Which of these numbers is not prime: 2, 3, 9, 11?", explanation: "9 = 3 × 3.",
      options: [{ key: "A", text: "2", is_correct: false }, { key: "B", text: "3", is_correct: false },
                { key: "C", text: "9", is_correct: true }, { key: "D", text: "11", is_correct: false }] } })).json();
    await signIn(page, "admin");
    await page.goto("/review");
    await page.getByRole("button", { name: new RegExp(created.code) }).click();
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText(/Independent review required/)).toBeVisible();
    const after = await (await request.get(`${API}/questions/${created.id}`, { headers: { Authorization: `Bearer ${await apiToken(request, "reviewer@aptiguard.demo")}` } })).json();
    expect(after.status).toBe("pending_review");
  });
});
