# AptiGuard AI — IM-107 “An aptitude test that survives ten slots”

Assessment-integrity prototype: verifiable parallel-item generation → human review → calibration →
exposure-aware multi-slot assembly → server-scored delivery → evidence-backed leak detection.

**All demo data is synthetic** (deterministic seed 107). The official Integraminds datasets were not available;
the import pipelines (`/calibration/import`, `/leaks/datasets`) accept CSV/JSON/JSONL in the documented schema.

## Run it

Requirements: Python 3.12, Node 20+. No Docker, cloud or API keys needed.

```bash
./setup.sh
```

```bash
./start.sh
```

Open http://localhost:5173 · API docs: http://127.0.0.1:8000/api/docs

Reset the demo at any time with `backend/.venv/bin/python scripts/seed_demo.py` (or Settings → System → Reset demo data as admin).

### Demo accounts (local demo only)

Password for every account: `AptiGuard-Demo-2026`

| Email | Role |
|---|---|
| admin@aptiguard.demo | Administrator |
| designer@aptiguard.demo | Assessment Designer (generates, assembles) |
| reviewer@aptiguard.demo | Reviewer (approves, investigates, quarantines) |
| analyst@aptiguard.demo | Psychometric Analyst (calibration, leak detection) |
| candidate1@aptiguard.demo (also 2, 3) | Candidate |

## 6-minute demo sequence

1. **Dashboard** (analyst): KPIs, slot comparison (raw score vs Rasch ability), active alerts, overlap status — all live from the DB.
2. **Leak Detection**: click *Run detection*. Open a CRITICAL alert, e.g. `QNT-SDT-M1-S`. It shows the verbatim Telegram-style post, the Mantel–Haenszel drift (baseline p → later p, ETS Δ, BH q-value), the response-time drop, the per-slot curve, the affected family, and “first detectable: slot 3”. Note the *statistical-only* alert (`LOG-ORDER-H1-S`), which has no text evidence and is labelled differently.
3. Sign in as **reviewer**: Investigate → Confirm with a note. The item becomes *quarantined / confirmed leak*.
4. Sign in as **designer** → **AI Variant Studio**: pick a source, generate 3 variants. Show recomputed answers and validation checks; rejected candidates are listed with reasons.
5. **Reviewer Workspace** (reviewer): compare source and variant, approve one. A designer cannot approve (API 403), and an author cannot approve their own item (409).
6. **Calibration Lab**: n, p with Wilson CI, item–rest r, Rasch b±SE, Δ vs source with 90% CI. Statuses are within / outside tolerance, requires review, or insufficient data, with sample-size warnings.
7. **Test Assembler** (designer): generate 10 slots at a 10% adjacent-overlap limit with seed 107. Show the verified overlap matrix and manifests. Then set *Max slot exposures* = 1 and generate again: it fails explicitly and names the bottleneck. Publish a successful run.
8. **Candidate** (candidate1): open an assessment, answer with A–D keys, submit, and get a server-side score. No answer keys reach the browser.
9. **Reports**: download Leak investigations / Calibration as CSV, JSON or PDF, with provenance and warnings.

## Verify

```bash
cd backend && .venv/bin/python -m pytest -q
```

```bash
backend/.venv/bin/python scripts/run_validation.py
```

```bash
cd frontend && npm run build
```

## Architecture (modular monolith)

- `backend/app/services/generation`: 16 deterministic templates (6 quant, 5 logical, 5 verbal), each with an independent verifier (recomputation, syllogism model enumeration, brute-force ordering uniqueness). There is also an optional Claude adapter (`LLM_PROVIDER=anthropic`).
- `validation`: schema, single key, distinct/equivalent options, exact / near-duplicate / answer-equivalent-clone detection, quality gates.
- `calibration`: CTT (Wilson CIs, item–rest r, missingness) and Rasch MML-EM. Rasch is refused for disconnected designs and leaked items are excluded from linking. Variant equivalence uses TOST on the 90% CI.
- `exposure`: per-item slots, candidates, recency, and an explained 0–100 risk score. Supports quarantine, retire and release.
- `assembly`: preflight capacity check → greedy seeded selection with bounded backtracking → independent re-verification. Jaccard and smaller-form % are computed for every pair.
- `leakage`: text (containment, windowed char-n-gram TF-IDF, numeric and option signatures, template masking) plus Mantel–Haenszel drift with purification, an RT test, Benjamini–Hochberg control, and slot-by-slot replay to find the earliest detectable slot.
- Stack: FastAPI, SQLAlchemy 2, Alembic, SQLite (PostgreSQL via `DATABASE_URL`), JWT + server-side RBAC (5 roles), React 19, TypeScript, Vite, Tailwind 4, Radix, TanStack Query, Recharts.

See `docs/test-report.md` and `docs/known-limitations.md`.
