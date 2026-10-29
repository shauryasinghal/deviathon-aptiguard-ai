# AptiGuard AI — IM-107 “An aptitude test that survives ten slots”

Assessment-integrity prototype: verifiable parallel-item generation → mandatory human review → calibration →
exposure-aware multi-slot assembly → assigned, server-scored delivery → evidence-backed leak detection → audited
staff decisions.

> **All data in this repository is synthetic** (deterministic seed 107). The official Integraminds datasets were not
> available, so **official-data validation is BLOCKED** (see [docs/dataset-schema.md](docs/dataset-schema.md)).
> Every result quoted here describes synthetic scenarios only and is **not** real-world validation.

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI[React 19 + TypeScript SPA<br/>Vite · Tailwind · TanStack Query]
  end
  UI -- "/api/v1 (JWT bearer)" --> API[FastAPI modular monolith<br/>server-side RBAC · validation · audit chain]
  API --> GEN[generation<br/>16 verified templates · optional Claude adapter]
  API --> VAL[validation<br/>keys · ambiguity · duplicates · clones]
  API --> CAL[calibration<br/>CTT · Rasch MML · TOST]
  API --> EXP[exposure<br/>risk score · quarantine]
  API --> ASM[assembly<br/>preflight · greedy+backtracking · re-verify]
  API --> LEAK[leakage<br/>text match · MH drift · RT · BH-FDR]
  API --> INT[integrity<br/>flagged attempts · staff decisions]
  API --> REP[reporting<br/>CSV · JSON · PDF]
  API --> DB[(SQLite default · PostgreSQL 17 tested<br/>Alembic migrations 0001–0005)]
```

Details: [docs/architecture.md](docs/architecture.md).

## Requirements

| Tool | Supported | Tested here |
|---|---|---|
| Python | 3.11+ | 3.12.7 |
| Node.js | 20+ | 26.8.1 (CI: 22) |
| PostgreSQL (optional) | 15+ | 17.10 |
| Docker + Compose v2.17+ (optional) | — | **not available locally**; runs in CI |

## Quick start (SQLite, offline demo) — verified

```bash
./setup.sh
```

```bash
./start.sh
```

Web app http://localhost:5173 · API docs http://127.0.0.1:8000/api/docs. `setup.sh` creates `backend/.venv`, installs
npm packages, runs all migrations and seeds the synthetic demo.

**Safe demo reset** (wipes and recreates *synthetic* demo data only). The seed refuses when `APP_ENV=production`, when
`DEMO_MODE=false`, or when the database contains any organisation other than the demo tenant:

```bash
backend/.venv/bin/python scripts/seed_demo.py
```

## Demo accounts (synthetic, demo mode only)

With `DEMO_MODE=true` (default outside production) the login page offers one-click sign-in per role. All demo accounts
share `DEMO_PASSWORD` (default `AptiGuard-Demo-2026`). Production refuses to start with demo mode on, and demo
credentials are never served when demo mode is off. Signing out revokes all of that user's sessions.

| Account | Role | Can |
|---|---|---|
| admin@aptiguard.demo | Administrator | everything incl. policies, audit log + integrity check, session revocation, demo reset |
| designer@aptiguard.demo | Assessment Designer | author items, generate variants, assemble, publish, assign/unassign candidates |
| reviewer@aptiguard.demo, reviewer2@… | Reviewer | approve/reject (not own items), quarantine/release, investigate leaks, resolve flagged attempts |
| analyst@aptiguard.demo | Psychometric Analyst | calibration, data import, leak detection, audit log |
| candidate1/2/3@aptiguard.demo | Candidate | take **assigned** assessments only |

## PostgreSQL — verified with a local throw-away cluster

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/aptiguard'
```

```bash
cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.bootstrap
```

Then either seed the synthetic demo (`scripts/seed_demo.py`, demo mode only) or create the first administrator:

```bash
backend/.venv/bin/python scripts/create_admin.py
```

`create_admin.py` reads `ADMIN_EMAIL`, `ADMIN_NAME`, `ORG_NAME`, `ORG_SLUG` and the password from `ADMIN_PASSWORD` or an
interactive prompt (minimum 12 characters, never printed).

## Docker — implemented, verified only in CI

Demo stack (SQLite volume, seeds only an empty database):

```bash
docker compose up -d --build --wait
```

Production-like stack (PostgreSQL, no demo, no seed):

```bash
JWT_SECRET=$(openssl rand -hex 32) POSTGRES_PASSWORD=$(openssl rand -hex 16) docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python /srv/scripts/create_admin.py
```

Open http://localhost:8080. The backend container runs as a non-root user, applies migrations first and **exits on any
migration failure** (no seeding, no API start). `scripts/docker_smoke.sh` verifies all of this plus restarts and
must-fail cases; it runs in GitHub Actions because Docker is not installed on the development machine.

## Tests and checks

| Check | Command | Status |
|---|---|---|
| Backend (SQLite) | `cd backend && .venv/bin/python -m pytest -q` | verified |
| Backend (PostgreSQL) | `TEST_DATABASE_URL=postgresql+psycopg://…/aptiguard_test` then the same command (DB name must end in `_test`; its schema is rebuilt) | verified |
| Migrations / drift | `cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic check` | verified (SQLite + PostgreSQL) |
| Live concurrency | `scripts/concurrency_check.py --api http://127.0.0.1:8002` against a multi-worker uvicorn | verified (SQLite + PostgreSQL) |
| Frontend | `cd frontend && npm run typecheck && npm test && npm run build` | verified |
| Browser E2E | `cd frontend && npx playwright install chromium && npx playwright test` (own backend on port 8001, throw-away DB) | verified |
| Repo hygiene | `python3 scripts/check_repo_hygiene.py` | verified |
| Dependency audits | `backend/.venv/bin/pip-audit -r backend/requirements.txt` · `cd frontend && npm audit --omit=dev` | verified |
| Docker smoke | `bash scripts/docker_smoke.sh` | CI only |
| Synthetic evaluation | `backend/.venv/bin/python scripts/run_validation.py` | verified (synthetic) |
| Official-data validation | `backend/.venv/bin/python scripts/validate_official_data.py` | **BLOCKED** (no official data) |

Results of the latest run: [docs/test-report.md](docs/test-report.md). CI ([.github/workflows/ci.yml](.github/workflows/ci.yml))
runs hygiene + actionlint + hadolint, backend on SQLite and on a PostgreSQL 17 service (tests, drift check,
downgrade/upgrade, live concurrency), frontend checks, Playwright, and the Docker smoke test.

## 6-minute demonstration

1. **Login** → *Sign in as Psychometric Analyst*. Dashboard: live KPIs, slot comparison, alerts, overlap.
2. **Leak Detection** → *Run detection*; open the CRITICAL alert for `QNT-SDT-M1-S` (text evidence, ability-adjusted drift,
   response-time drop, per-slot curve, affected family, first detectable slot). Compare the statistical-only alert.
3. **Reviewer** → confirm the leak with a note → item quarantined, affected forms flagged *needs reassessment*.
4. **Designer** → **AI Variant Studio** → generate variants (recomputed answers, rejected candidates with reasons).
5. **Reviewer Workspace** → approve a variant. Authors cannot approve their own items; designers get 403.
6. **Calibration Lab** → CIs, Rasch b ± SE, TOST decisions, sample-size warnings; export CSV/PDF.
7. **Test Assembler** → 10 slots at 10% adjacent overlap → verified overlap matrix; set exposure limit 1 → explicit infeasibility.
8. **Candidate** → only assigned forms; answer, submit, server-calculated score.
9. **Reviewer Workspace → Flagged attempts** → resolve an attempt affected by a withdrawn question (decision + reason, audited).
10. **Settings → Audit log → Verify integrity** → hash chain intact.

## Configuration

See [.env.example](.env.example): `APP_ENV` (development|test|production), `DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS`,
`DEMO_MODE`, `DEMO_PASSWORD`, `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_SECONDS`, `MAX_UPLOAD_MB`, `MAX_REQUEST_MB`,
`LLM_PROVIDER`/`LLM_API_KEY`/`LLM_MODEL` (optional; tested only with a mocked provider). With `APP_ENV=production`
start-up fails unless `DEMO_MODE=false`, `JWT_SECRET` ≥ 32 characters and explicit `CORS_ORIGINS`; the error never
echoes configured values.

## Troubleshooting

- *Invalid email or password* in the demo: use the one-click buttons; check the README password matches `DEMO_PASSWORD`.
- *Too many failed sign-in attempts*: wait the indicated seconds (the limiter is stored in the database and survives restarts).
- *Session has been revoked*: the user signed out elsewhere or an admin revoked sessions — sign in again.
- `/ready` returns 503: the database is not migrated — run `alembic upgrade head`.
- Seed refuses: you are pointing at a production or non-demo database — this is intentional.

## Security, limitations, AI disclosure

- [docs/security-review.md](docs/security-review.md) · [docs/known-limitations.md](docs/known-limitations.md) ·
  [docs/dataset-schema.md](docs/dataset-schema.md)
- **AI assistance:** this prototype was designed and implemented with substantial assistance from an AI coding assistant
  (Anthropic Claude via Claude Code), directed and reviewed by the team. All metrics in this repository come from
  executed tests and scripts on synthetic data; none are estimated or invented.
