# AptiGuard AI

**Keep an aptitude test fair, comparable and defensible across ten reuse slots — generate, calibrate, assemble, monitor and audit.**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-default-003B57?logo=sqlite&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-optional-4169E1?logo=postgresql&logoColor=white)

AptiGuard AI (project brief **IM-107**, *“An aptitude test that survives ten slots”*) is an assessment-integrity
**prototype**. It covers the lifecycle of a reusable question bank: verifiable parallel-item generation, mandatory human
review, calibration, exposure-aware multi-slot test assembly, assigned and server-scored delivery, evidence-backed leak
detection, and audited staff decisions.

It is intended for assessment designers, reviewers and psychometric analysts who run recurring aptitude drives, and for
hackathon judges evaluating the approach.

> **Data disclaimer.** Every dataset and metric in this repository is **synthetic** (deterministic seed 107). The official
> Integraminds datasets were not available, so **official-data validation is BLOCKED**. Nothing here is real-world
> validation, evidence of production effectiveness, or a statement about real candidates. See [Data and evaluation](#data-datasets-and-evaluation).

## Table of contents

1. [The problem](#the-problem-an-aptitude-test-that-survives-ten-slots)
2. [Solution overview](#solution-overview)
3. [Features and implementation status](#key-features-and-implementation-status)
4. [System architecture](#system-architecture)
5. [End-to-end workflow](#end-to-end-workflow)
6. [Methodology](#aiml-and-statistical-methodology)
7. [Data, datasets and evaluation](#data-datasets-and-evaluation)
8. [Security, integrity and access control](#security-integrity-and-access-control)
9. [Technology stack](#technology-stack)
10. [Quick start](#quick-start) · [PostgreSQL](#postgresql) · [Docker](#docker)
11. [Configuration](#configuration)
12. [API documentation](#api-documentation)
13. [Repository structure](#repository-structure)
14. [Testing, quality and CI](#testing-quality-and-continuous-integration)
15. [Demo walkthrough](#demo-walkthrough)
16. [Limitations and roadmap](#limitations-and-future-roadmap)
17. [Team](#team) · [Acknowledgements](#acknowledgements) · [License](#license)

---

## The problem: “An Aptitude Test That Survives Ten Slots”

A recruiting drive that runs the same aptitude test in ten consecutive slots has structural problems:

- **Exposure and leakage.** Every slot shows items to more candidates. Items that appear in earlier slots can be
  shared before later slots, so the longer an item stays in use the less it can be trusted.
- **Comparability.** Candidates in slot 1 and slot 10 must face assessments of comparable difficulty and content
  coverage, yet they cannot see identical questions. Hand-writing equivalent forms is slow, and “equivalent” has to be
  demonstrated with data, not assumed.
- **Item quality.** A question needs a correct key, unambiguous wording, and measurable difficulty and discrimination.
  Generated variants are only useful if they are demonstrably parallel to their source item.
- **Post-exam evidence.** Suspected leaks need evidence (where the text appeared, whether performance shifted, whether
  answers got faster), a human decision, and a record of who decided what.
- **Mid-exam changes.** If an item is withdrawn while attempts are in progress, the affected candidates need a
  documented, reviewable outcome rather than silent invalidation.

AptiGuard AI implements tooling for each of these concerns on **synthetic data**. It does **not** claim to eliminate
cheating, leakage or unfairness; leak detection only examines datasets that are imported into it, and similarity or
statistical signals are evidence for human review, not proof of misconduct.

## Solution overview

```text
Generate → Validate → Human review → Calibrate → Exposure management → Assemble (+ re-verify) → Deliver →
Leak detection → Investigate / quarantine → Flagged-attempt review → Report (all actions audited)
```

| Stage | What happens | Where |
|---|---|---|
| Generate | 16 deterministic templates produce parallel variants with recomputed answers; an optional Anthropic adapter can also propose variants | [`services/generation/`](backend/app/services/generation) |
| Validate | Key re-computation, structural/ambiguity checks, exact and near-duplicate detection | [`services/validation/`](backend/app/services/validation) |
| Review | Variants land in a `pending_review` queue; they are never auto-published and authors cannot approve their own items | [`api/v1/variants.py`](backend/app/api/v1/variants.py) |
| Calibrate | CTT statistics, Rasch (1PL) difficulty, TOST variant-equivalence decisions | [`services/calibration/`](backend/app/services/calibration) |
| Expose | Explainable 0–100 exposure-risk score, quarantine/retire/release | [`services/exposure/`](backend/app/services/exposure) |
| Assemble | Preflight capacity check, greedy + backtracking assembly, independent re-verification | [`services/assembly/`](backend/app/services/assembly) |
| Deliver | Assigned-only candidate access, server-side deadline and scoring | [`api/v1/assessment.py`](backend/app/api/v1/assessment.py) |
| Detect leaks | Text matching, Mantel–Haenszel drift, response-time analysis, Benjamini–Hochberg correction | [`services/leakage/`](backend/app/services/leakage) |
| Review attempts | Attempts affected by withdrawn items are flagged for a staff decision | [`api/v1/integrity.py`](backend/app/api/v1/integrity.py) |
| Report / audit | CSV, JSON and PDF reports; hash-chained audit log | [`services/reporting/`](backend/app/services/reporting), [`services/audit.py`](backend/app/services/audit.py) |

The demo runs on seeded synthetic history; live candidate attempts, generation and assembly are real code paths exercised
on that data, but no real drive has been run through the system.

## Key features and implementation status

Status reflects code inspection and the tests described in [docs/test-report.md](docs/test-report.md). “Implemented”
means the code exists and is covered by tests in this repository, not that it has been validated on real data.

| Feature | Purpose | Implementation Status |
|---|---|---|
| Template-based question generation | 16 verified templates (Quant, Logical, Verbal) produce variants with recomputed answers | Implemented |
| Optional Claude/LLM variant generation | Extra variant source via Anthropic adapter (`LLM_PROVIDER=anthropic`) | Experimental — off by default; tested only with a mocked provider |
| Question validation | Key recomputation, structural and ambiguity checks | Implemented (verbal items cannot be machine-proven; all flagged for human review) |
| Duplicate / near-duplicate detection | Text similarity gate (fail ≥ 0.93, warn ≥ 0.86) plus clone checks | Implemented |
| Mandatory human review | Pending queue, approve/reject, author ≠ approver | Implemented |
| Classical Test Theory | Item p-value with Wilson CI, omissions, corrected item–rest correlation | Implemented |
| Rasch (1PL) calibration | Item difficulty ± SE via marginal ML (EM) | Implemented — 1PL only; no 2PL/3PL |
| Equivalence testing (TOST) | Decide whether a variant matches its source's difficulty | Implemented — most synthetic comparisons end “requires review” at the available sample size |
| Exposure tracking and risk score | Explainable 0–100 score from slot usage, audience, recency, leak status | Implemented |
| Quarantine / retire / release | Withdraw risky items, flag affected forms | Implemented |
| Test assembly with preflight | 10-slot forms under exposure/overlap/family constraints, explicit infeasibility reports | Implemented |
| Independent form verification | `verify_plan` re-checks overlap, families, eligibility | Implemented |
| Leak detection — text matching | Exact, similar and family-level matches against imported datasets | Implemented (imported datasets only) |
| Statistical drift (Mantel–Haenszel) | Ability-adjusted per-item performance shift | Implemented |
| Response-time analysis | Pace-normalised speed-up test | Implemented |
| Multiple-testing correction | Benjamini–Hochberg FDR | Implemented |
| Attempt integrity review | Flag attempts affected by withdrawn items; staff resolution with reason | Implemented |
| Role-based permissions | 5 roles, 19 server-checked permissions | Implemented |
| Audit log with hash chain | Append-only SHA-256 chain with verify endpoint; optional external anchor (`anchor_count` + `anchor_head`) detects removal of the newest events | Implemented — tamper-*evident*, not tamper-proof |
| Server-observed item timing | Response times come from server-clock `focus` events, never from client-reported durations | Implemented — measures time on screen, not attention |
| Expired-attempt finalisation | Background sweep + `scripts/finalize_expired.py`; idempotent and race-safe | Implemented |
| Form comparability summary | Advisory mean-difficulty comparison of forms from Rasch estimates, with uncertainty | Implemented — advisory only; not an equivalence guarantee |
| Retention / pseudonymisation / second-look policies | Stored in Settings | **Not enforced** — shown as such in the UI and read-only |
| Reports (CSV / JSON / PDF) | Downloadable reports with filters | Implemented |
| Dashboard, global search, notifications | Command-center KPIs, `/search`, `/notifications` | Implemented |
| Candidate delivery | Assigned forms, atomic submit, server-side scoring | Implemented |
| Official-data validation | Pipeline for the official dataset | Pipeline implemented; **BLOCKED** — no official data |
| Proctoring, identity verification, SSO/MFA, accommodations, multilingual content | — | Not implemented |

## System architecture

```mermaid
flowchart LR
  subgraph Users
    ROLES["Admin · Designer · Reviewer · Analyst · Candidate"]
  end
  subgraph Browser
    UI["React 19 + TypeScript SPA<br/>Vite · Tailwind · TanStack Query<br/>frontend/src/pages"]
  end
  ROLES --> UI
  UI -- "/api/v1 · JWT bearer" --> API["FastAPI app<br/>backend/app/main.py"]
  subgraph Backend
    API --> AUTH["core/deps.py · core/security.py<br/>JWT + server-side permission checks"]
    API --> GEN["generation<br/>16 templates · llm_adapter"]
    API --> VAL["validation"]
    API --> CAL["calibration<br/>CTT · Rasch · TOST"]
    API --> EXP["exposure"]
    API --> ASM["assembly"]
    API --> LEAK["leakage"]
    API --> INT["integrity + assessment"]
    API --> REP["reporting<br/>CSV · JSON · PDF"]
    API --> AUD["audit hash chain"]
  end
  GEN -. "optional, off by default" .-> LLM["Anthropic API"]
  GEN & VAL & CAL & EXP & ASM & LEAK & INT & REP & AUD --> DB[("SQLite default<br/>PostgreSQL supported<br/>Alembic 0001–0007")]
```

The backend is a single FastAPI application. Routers in `backend/app/api/v1/` handle routing, permission checks and
Pydantic request validation; domain logic lives in `backend/app/services/` without HTTP concerns; SQLAlchemy 2 models are
in `backend/app/models/`. In development the Vite dev server proxies `/api` to `127.0.0.1:8000` ([frontend/vite.config.ts](frontend/vite.config.ts)).

A modular monolith with a relational database fits the current scope: the domain operations (assembly, exposure
counting, scoring) need transactional consistency, and there is no queue, cache, microservice or cloud-specific
infrastructure in the repository. Full detail: [docs/architecture.md](docs/architecture.md).

## End-to-end workflow

```mermaid
flowchart TD
  A["Source question<br/>seeded bank or POST /questions"] --> B["Generate variants<br/>templates or optional LLM"]
  B --> C["Validate<br/>key · ambiguity · duplicates"]
  C --> D{"Human review"}
  D -- reject --> B
  D -- "approve (author ≠ approver)" --> E["Calibrate<br/>CTT · Rasch · TOST on response logs"]
  E --> F["Exposure score and eligibility"]
  F --> G["Assemble slots<br/>preflight → greedy + backtracking"]
  G --> H["verify_plan<br/>independent re-check"]
  H --> I["Publish and assign candidates"]
  I --> J["Candidate attempt<br/>server-scored"]
  J --> K["Leak detection on imported datasets"]
  K --> L{"Reviewer decision"}
  L -- "confirm" --> M["Quarantine item<br/>flag affected forms and attempts"]
  M --> N["Flagged-attempt resolution"]
  L -- dismiss --> F
  N --> O["Reports and audit-chain verification"]
```

1. **Entry.** Source items come from the seeded bank, manual creation, or CSV/JSON/JSONL import; variants come from templates (or the optional LLM adapter).
2. **Validation.** Answer keys are recomputed; ambiguity and duplicate checks run; failures block approval.
3. **Calibration.** Response logs (the seed imports 45,000 synthetic responses) feed CTT and Rasch; TOST compares variants to sources.
4. **Exposure / leakage.** Exposure events accumulate per form/item; leak detection scans imported datasets.
5. **Assembly and verification.** The solver builds slot forms; `verify_plan` checks them independently.
6. **Attempt review.** Items withdrawn mid-attempt do not invalidate attempts: staff get a flag, an alternative score and a documented decision.
7. **Reporting.** Reports export as CSV/JSON/PDF; the audit log can be verified.

**Simulated parts:** historical slot responses, candidate cohorts and the leak-post dataset are generated by [backend/app/demo/seed.py](backend/app/demo/seed.py). Candidate delivery itself is real server code, but no real candidates are involved.

## AI/ML and statistical methodology

No deep learning is used. The methods are classical psychometrics and text/statistical tests; LLM use is optional.

| Method | Problem solved | Input → Output | How it is used | Assumptions / limits |
|---|---|---|---|---|
| **Template generation** (`generation/`) | Produce parallel items whose answers can be proven | Template id, difficulty, seed → stem, options, key | Variants go to the review queue | Finite text space; verbal items need human review; difficulty bands are *a-priori* until calibrated |
| **Optional LLM adapter** (`llm_adapter.py`) | Extra variant source | Source item → candidate variants | Same validation + review path as templates | Off by default; tested with a mock only; never auto-published |
| **Validation + duplicates** (`validation/`, `textsim.py`) | Reject wrong keys and repeats | Item + bank → checks (pass/warn/fail) | Failures block approval; near-duplicates held | Similarity thresholds (0.93/0.86) are heuristics |
| **CTT** (`calibration/ctt.py`) | Item difficulty and discrimination | Response matrix → p with Wilson CI, item–rest r | Shown in Calibration Lab; sample-size warnings | Needs enough responses per item |
| **Rasch 1PL** (`calibration/rasch.py`) | Comparable difficulty on one scale | Linked responses → b ± SE | Basis for variant equivalence | Marginal ML via EM (Bock–Aitkin), N(0,1) prior; refused for disconnected designs; leaked items excluded from linking; no guessing parameter |
| **TOST equivalence** | Show a variant is *not meaningfully different* | Difficulty difference CI → equivalent / not / requires review | Inconclusive results never count as equivalent | 90% CI of difference; Newcombe interval on the preliminary p-scale |
| **Exposure-risk score** (`exposure/service.py`) | Rank items by overuse risk | Slots used, audience, recency, leak status → 0–100 with components | Quarantine candidates; assembler eligibility | Additive heuristic (40 slot usage, 25 audience, 15 recency, +20/+35 leak status, +10 family leak) |
| **Test assembly** (`assembly/algorithm.py`) | Build comparable forms under constraints | Pool, quotas, exposure/overlap limits → slot forms or infeasibility report | Forms then re-verified by `verify_plan` | Greedy with bounded re-randomisation and backtracking; seeded, not provably optimal |
| **Text-match leakage** (`leakage/text_match.py`) | Find items reproduced in imported posts | Posts + bank → item_exact / item_similar / family matches | Evidence on alerts | Word-3-shingle containment and windowed char-n-gram cosine; textual overlap is not proof of misconduct |
| **Mantel–Haenszel drift** (`leakage/stats.py`) | Detect ability-adjusted performance gains | Responses stratified by rest-score → OR, ETS Δ class, p | Statistical alert evidence | Purified rest-score; needs minimum group sizes |
| **Response-time test** | Detect faster-than-expected answering | Log response times normalised by slot pace → one-sided Mann–Whitney p | Alert evidence | Depends on recorded timings |
| **Benjamini–Hochberg FDR** | Control false discoveries across many items | p-values → adjusted p | Applied to drift tests | Verified against hand-derived values, not against R |

Details and the full method notes are in [docs/architecture.md](docs/architecture.md#statistical-methods-short).

## Data, datasets and evaluation

| Category | Status |
|---|---|
| Synthetic demonstration | **Done** — everything below |
| Offline technical tests | **Done** — see [Testing](#testing-quality-and-continuous-integration) |
| Real-world validation | **Not done** |
| Official / external dataset validation | **BLOCKED** — official Integraminds data was not available; `scripts/validate_official_data.py` exits with status `BLOCKED` ([docs/dataset-schema.md](docs/dataset-schema.md)) |

**Datasets** in [data/synthetic/](data/synthetic) are generated by [backend/app/demo/seed.py](backend/app/demo/seed.py)
(`SEED = 107`), with SHA-256 hashes in [MANIFEST.json](data/synthetic/MANIFEST.json):

| File | Content |
|---|---|
| `item_bank.jsonl` | 573 synthetic items |
| `response_logs.csv` | 45,000 synthetic candidate×item responses (150 candidates × 10 slots × 30 items) |
| `leak_simulation_posts.jsonl` / `leak_ground_truth.json` | Synthetic leak posts and injected ground truth |

**Seed output, verified.** Running `scripts/seed_demo.py` against a fresh throw-away SQLite database during this README
update reported: **45,000 responses, 1,500 attempts, 15 pending-review items, 11 leak alerts** (4 critical, 4 high,
1 medium, 2 low), plus one succeeded assembly run. The seed also creates demo users, the historical drive
(`Campus Drive 2026-Q3 (synthetic)`) and an upcoming drive (`Campus Drive 2026-Q4`).

**Synthetic evaluation** (from [docs/test-report.md](docs/test-report.md); not re-run for this README): one scenario with
9 injected leaked items; at medium severity or higher 9/9 were detected with 0 alerts on the 547 non-leaked items. The
thresholds were developed on this same scenario, so this is **not independent validation**, and with n = 9 the recall
95% Wilson CI is [0.70, 1.00]. Reproduce with `backend/.venv/bin/python scripts/run_validation.py`
(output in [docs/evidence/validation_results.json](docs/evidence/validation_results.json)).

## Security, integrity and access control

| Area | Implementation | Enforced where |
|---|---|---|
| Authentication | bcrypt (cost 12) passwords; HS256 JWT with `exp`, `iat`, `sub`, `iss`, `tv`; generic login error | Server |
| Session revocation | Sign-out bumps the user's token version (“sign out everywhere”); admins can revoke another user's sessions | Server |
| Authorization | Every route declares a permission (`require("…")`); role→permission map in [core/security.py](backend/app/core/security.py) | Server (frontend hides nav items by permission but is not relied on) |
| Object-level access | Candidates see only assigned forms and their own attempts; organisation scoping | Server |
| Input validation | Pydantic request models; upload allow-list (`.csv/.json/.jsonl`), size caps (`MAX_UPLOAD_MB`, `MAX_REQUEST_MB`) | Server |
| Database access | SQLAlchemy ORM with bound parameters | Server |
| Brute-force limit | Failures per client+email, stored in the database | Server |
| Audit | SHA-256 hash chain; `GET /api/v1/audit/verify` finds edited, deleted or re-ordered events | Server |
| Attempt integrity | Atomic submit, server deadline, flagged-attempt review with mandatory reason | Server |
| Secrets | `.env` is git-ignored; production start-up refuses weak `JWT_SECRET`, demo mode or wildcard CORS and never echoes configured values | Server |
| Errors | Consistent envelope; unhandled errors return an opaque reference id | Server |

Not claimed: the app is not proven secure against every attack. Known residual risks (full list in
[docs/security-review.md](docs/security-review.md)): JWT in `sessionStorage` (XSS exposure), a database administrator
could rewrite the whole audit chain, no MFA/SSO, no proctoring or identity verification, login lock-out of a known email
is possible, and the demo password is public by design.

## Technology stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React 19, TypeScript ~5.9, Vite 8, Tailwind CSS 4 | SPA ([frontend/package.json](frontend/package.json)) |
| Frontend state / routing / charts | TanStack Query 5, React Router 7, Recharts 3 | Data fetching, routes, visualisations |
| Backend | Python 3.11+, FastAPI 0.162, Uvicorn 0.54, Pydantic 2.14 | REST API ([backend/requirements.txt](backend/requirements.txt)) |
| Auth | PyJWT 2.15, bcrypt 4.2 | Tokens and password hashing |
| Database | SQLite (default), PostgreSQL via psycopg 3.2 | Persistence; SQLAlchemy 2.0.36 ORM |
| Migrations | Alembic 1.14 (revisions 0001–0007) | Schema management |
| Analytics | NumPy 2.1, SciPy 1.14, pandas 2.2, scikit-learn 1.6 | Statistics and text similarity |
| Reporting | ReportLab 4.2 | PDF export |
| Optional AI | `anthropic` (via [requirements-llm.txt](backend/requirements-llm.txt)) | Optional variant generation |
| Testing | pytest 9, Vitest 3, Playwright 1.64 | Backend, unit and browser E2E tests |
| Delivery | Docker, Docker Compose, nginx, GitHub Actions | Optional containers and CI |

## Quick start

**Prerequisites:** Python 3.11+, Node.js 20+ and npm. Docker and PostgreSQL are optional. The commands below match
[setup.sh](setup.sh) and [start.sh](start.sh).

```bash
git clone https://github.com/shauryasinghal/deviathon-aptiguard-ai.git
cd deviathon-aptiguard-ai
./setup.sh
./start.sh
```

- `setup.sh` creates `backend/.venv`, installs Python and npm packages, and runs `scripts/seed_demo.py`, which applies
  the Alembic migrations and seeds the synthetic demo into the default SQLite database. To use a specific interpreter:
  `PYTHON=/path/to/python3.12 ./setup.sh`.
- `start.sh` starts the API on port 8000 in the background and the Vite dev server in the foreground.

| What | URL |
|---|---|
| Web app | http://localhost:5173 |
| API | http://127.0.0.1:8000/api/v1 |
| Interactive API docs | http://127.0.0.1:8000/api/docs |

**Stop:** press `Ctrl+C` in the terminal running `start.sh`; its exit trap kills the API process. If a port stays busy,
find the leftover process with `lsof -i :8000` and stop it.

**Safe demo reset** (wipes and recreates *synthetic* demo data only; refuses when `APP_ENV=production`, `DEMO_MODE=false`
or when the database contains any non-demo organisation):

```bash
backend/.venv/bin/python scripts/seed_demo.py
```

### Demo accounts (synthetic, demo mode only)

With `DEMO_MODE=true` the login page offers one-click sign-in per role. All demo accounts share `DEMO_PASSWORD`
(see [.env.example](.env.example); the application default is documented in `backend/app/core/config.py`). Demo
credentials are never served when demo mode is off, and production refuses to start with demo mode on.

| Account | Role | Can |
|---|---|---|
| admin@aptiguard.demo | Administrator | everything incl. policies, audit log + integrity check, session revocation, demo reset |
| designer@aptiguard.demo | Assessment Designer | author items, generate variants, assemble, publish, assign candidates |
| reviewer@aptiguard.demo, reviewer2@aptiguard.demo | Reviewer | approve/reject (not own items), quarantine/release, investigate leaks, resolve flagged attempts |
| analyst@aptiguard.demo | Psychometric Analyst | calibration, data import, leak detection, audit log |
| candidate1/2/3@aptiguard.demo | Candidate | take **assigned** assessments only |

### Troubleshooting

- *Invalid email or password* in the demo: use the one-click buttons on the login page.
- *Too many failed sign-in attempts*: wait the indicated seconds (the limiter survives restarts).
- *Session has been revoked*: someone signed out elsewhere or an admin revoked sessions — sign in again.
- `/api/v1/ready` returns 503: the database is not migrated — run `cd backend && .venv/bin/alembic upgrade head`.
- Seed refuses to run: it is pointed at a production or non-demo database — intentional.
- `./setup.sh` says Python 3.11+ required: set `PYTHON=` to a newer interpreter.

### PostgreSQL

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/aptiguard'
cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.bootstrap
```

Then seed the synthetic demo (`scripts/seed_demo.py`, demo mode only) or create the first administrator with
`backend/.venv/bin/python scripts/create_admin.py` (reads `ADMIN_EMAIL`, `ADMIN_NAME`, `ORG_NAME`, `ORG_SLUG` and the
password from `ADMIN_PASSWORD` or an interactive prompt; minimum 12 characters, never printed).

### Docker

Implemented, but according to [docs/known-limitations.md](docs/known-limitations.md) not executed on the development
machine; `scripts/docker_smoke.sh` runs in GitHub Actions.

```bash
docker compose up -d --build --wait
```

Production-like stack (PostgreSQL, no demo, no seed):

```bash
JWT_SECRET=$(openssl rand -hex 32) POSTGRES_PASSWORD=$(openssl rand -hex 16) docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python /srv/scripts/create_admin.py
```

The app is then at http://localhost:8080. The backend container runs as a non-root user and exits on any migration failure.

## Configuration

Copy [.env.example](.env.example) to `.env` (git-ignored) and adjust. Use placeholders for secrets.

| Variable | Purpose | Required? | Safe example |
|---|---|---|---|
| `APP_ENV` | `development`, `test` or `production` (production enables hard guards) | No | `development` |
| `DATABASE_URL` | SQLAlchemy URL (SQLite or PostgreSQL) | No (SQLite default) | `sqlite:///backend/var/aptiguard.db` |
| `JWT_SECRET` | Token signing key; must be ≥ 32 characters in production | **Yes in production** | `<random-32+-char-secret>` |
| `JWT_EXPIRE_MINUTES` | Token lifetime | No | `480` |
| `CORS_ORIGINS` | Allowed browser origins; must be explicit in production | Yes in production | `http://localhost:5173` |
| `DEMO_MODE` | Enables demo login and seeding; must be `false` in production | No | `true` |
| `DEMO_PASSWORD` | Password for seeded synthetic accounts | No | `<demo-password>` |
| `LOGIN_MAX_FAILURES` / `LOGIN_WINDOW_SECONDS` | Login rate limit | No | `8` / `300` |
| `MAX_UPLOAD_MB` / `MAX_REQUEST_MB` | Upload and request size caps | No | `10` / `12` |
| `EXPIRY_SWEEP_SECONDS` | Interval of the in-process sweep that finalises expired attempts; `0` disables it (then run `scripts/finalize_expired.py` from cron) | No | `60` |
| `DEMO_SEED` | Docker only: seed demo data into an *empty* database at start | No | `false` |
| `FORWARDED_ALLOW_IPS` | Trusted proxies for `X-Forwarded-For` | No | `127.0.0.1` |
| `LLM_PROVIDER` | `none` or `anthropic` (optional generation) | No | `none` |
| `LLM_API_KEY` / `LLM_MODEL` | Provider key and model for the optional adapter | Only if `LLM_PROVIDER=anthropic` | `<your-api-key>` / see `.env.example` |

With `APP_ENV=production`, start-up fails unless `DEMO_MODE=false`, `JWT_SECRET` is strong and `CORS_ORIGINS` is explicit.
The optional LLM adapter needs `pip install -r backend/requirements-llm.txt`.

## API documentation

All routes are under `/api/v1` (plus `/api/docs` for Swagger UI). “Perm” is the server-checked permission from
[core/security.py](backend/app/core/security.py); routers are in [backend/app/api/v1/](backend/app/api/v1).

| Method | Endpoint | Purpose | Authentication |
|---|---|---|---|
| GET | `/health`, `/ready`, `/version` | Liveness, readiness (DB + migration state), version | None |
| GET | `/demo-status` | Whether demo mode/accounts are offered | None |
| POST | `/auth/login` | Obtain a JWT | None (rate limited) |
| GET / POST | `/auth/me`, `/auth/logout` | Current user; revoke own sessions | Bearer |
| GET | `/dashboard/summary` | Command-center KPIs | `dashboard.read` |
| GET | `/notifications`, `/search` | Alerts feed; global search | Bearer |
| GET / POST | `/questions`, `/questions/{qid}` · `/questions/bulk` | Browse, create, bulk import | `questions.read` / `questions.write` |
| POST | `/questions/{qid}/variants:generate` | Generate parallel variants | `variants.generate` |
| POST | `/questions/{qid}/validate` | Run validation checks | `questions.read` |
| GET / POST | `/review/queue` · `/review/{qid}/decision` | Review queue and decision | `questions.read` / `review.decide` |
| POST / GET | `/calibration/runs`, `/calibration/items`, `/calibration/families` | Run and read CTT/Rasch/TOST results | `calibration.run` / `calibration.read` |
| GET / POST | `/exposure/items`, `/exposure/items/{qid}/{action}` | Exposure risk; quarantine/retire/release | `exposure.read` / `exposure.manage` |
| POST | `/leaks/datasets`, `/leaks/detect` | Import leak dataset; run detection | `leaks.import` / `leaks.manage` |
| GET / POST | `/leaks/alerts`, `/leaks/alerts/{id}/actions` | Evidence and investigation actions | `leaks.read` / `leaks.manage` |
| GET / POST | `/assembly/preview`, `/assembly/validate`, `/assembly/runs` | Preflight, validate, assemble | `assembly.read` / `assembly.run` |
| POST | `/assembly/runs/{run_id}/publish`, `/assembly/forms/{form_id}/assignments` | Publish forms; assign candidates | `assembly.run` |
| GET | `/assessment/available` | Candidate's assigned forms | `assessment.take` |
| POST / PUT | `/assessment/forms/{id}/attempts`, `/assessment/attempts/{id}/responses`, `…/submit` | Start, save, submit | `assessment.take` |
| GET / POST | `/integrity/flagged-attempts`, `/integrity/attempts/{id}/resolution` | Flagged attempts and staff decision | `review.decide` |
| GET | `/reports/templates`, `/reports/{kind}/preview`, `/reports/{kind}.{csv\|json\|pdf}` | Report catalogue, preview, download | `reports.read` |
| GET | `/audit`, `/audit/verify` | Audit log; hash-chain check | `audit.read` |
| PUT | `/settings/policies/{key}` | Change assessment policy | `settings.manage` |
| POST | `/system/demo/reset` | Reset synthetic demo | `demo.reset` |

Request and response schemas are generated by FastAPI; browse them in the interactive docs at
http://127.0.0.1:8000/api/docs after starting the API. This table is representative, not exhaustive (see the router files).

## Repository structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/v1/         # routers: auth, questions, variants, calibration, exposure, leaks, assembly, assessment, integrity, reports, system
│   │   ├── core/           # config, JWT/RBAC, errors, rate limiting, logging
│   │   ├── models/         # SQLAlchemy models
│   │   ├── services/       # generation, validation, calibration, exposure, assembly, leakage, reporting, audit
│   │   ├── demo/seed.py    # deterministic synthetic seed (seed 107)
│   │   └── main.py
│   ├── alembic/versions/   # migrations 0001–0007
│   └── tests/              # pytest suite (10 modules)
├── frontend/
│   ├── src/                # pages, components, lib (api client, auth)
│   └── tests/              # Vitest unit tests, Playwright E2E
├── data/synthetic/         # generated synthetic datasets + MANIFEST.json
├── docs/                   # architecture, security review, limitations, dataset schema, test report, evidence/
├── scripts/                # seed_demo, run_validation, validate_official_data, create_admin, concurrency_check, docker_smoke, hygiene check
├── .github/workflows/ci.yml
├── docker-compose.yml · docker-compose.prod.yml
├── setup.sh · start.sh
└── .env.example
```

## Testing, quality and continuous integration

| Check | Command |
|---|---|
| Backend tests (SQLite) | `cd backend && .venv/bin/python -m pytest -q` |
| Backend tests (PostgreSQL) | set `TEST_DATABASE_URL=postgresql+psycopg://…/aptiguard_test` (name must end in `_test`), then the same command |
| Migrations and drift | `cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic check` |
| Frontend type check / unit tests / build | `cd frontend && npm run typecheck && npm test && npm run build` |
| Browser E2E | `cd frontend && npx playwright install chromium && npx playwright test` |
| Live concurrency | `scripts/concurrency_check.py --api http://127.0.0.1:8002` against a multi-worker uvicorn |
| Repo hygiene / secrets scan | `python3 scripts/check_repo_hygiene.py` |
| Synthetic evaluation | `backend/.venv/bin/python scripts/run_validation.py` |
| Official-data validation | `backend/.venv/bin/python scripts/validate_official_data.py` (currently BLOCKED) |

No separate linter script (ESLint/ruff) is configured; static checks are TypeScript type checking, hygiene scan, and
`actionlint` / `hadolint` in CI.

**CI** ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs: hygiene + actionlint + hadolint; backend on SQLite
(migrations, drift check, tests, `pip-audit`); backend on PostgreSQL 17 (tests, drift, downgrade/upgrade, concurrency);
frontend (typecheck, tests, build, `npm audit`); Playwright E2E; and the Docker smoke test.

**Tests that exist vs. tests that were run.** The suites above exist in the repository. [docs/test-report.md](docs/test-report.md)
records a run dated 2026-10-29 (220 backend tests on SQLite and PostgreSQL, 9 frontend unit tests, 7 Playwright journeys).
Those results are quoted from that report; they were **not re-executed** while writing this README, and the
hosted-CI status of the latest commit has not been verified here. Documented gaps: Docker, actionlint and hadolint were not
run locally; multi-stratum MH, ETS thresholds, the response-time test and Rasch point estimates are not checked against
external reference implementations.

## Demo walkthrough

A roughly six-minute path for evaluators (details depend on the synthetic seed; use the one-click login buttons):

1. **Login → Psychometric Analyst.** Open the **Command Center**: KPIs, slot comparison, alerts.
2. **Leak Detection → Run detection.** Open a critical alert (e.g. item `QNT-SDT-M1-S`): text evidence, ability-adjusted drift, response-time shift, affected family.
3. **Reviewer → confirm the leak** with a note → the item is quarantined and affected forms are flagged.
4. **Designer → AI Variant Studio.** Generate variants (answers recomputed; rejected candidates show reasons).
5. **Reviewer Workspace → approve a variant.** An author cannot approve their own item (the server returns 403 for designers).
6. **Calibration Lab.** Confidence intervals, Rasch difficulty ± SE, TOST decisions, sample-size warnings; export CSV/PDF from **Reports**.
7. **Test Assembler.** Assemble 10 slots with the adjacent-overlap setting, inspect the verified overlap matrix; set the exposure limit to 1 to see an explicit infeasibility report.
8. **Candidate.** Sign in as a candidate: only assigned forms appear; answer, submit, see the server-calculated score.
9. **Reviewer Workspace → Flagged attempts.** Resolve an attempt affected by a withdrawn question (decision + reason, audited).
10. **Settings → Audit log → Verify integrity.**

## Limitations and future roadmap

**Current limitations**

- All data is synthetic; no official or real-world dataset has been used. The leak evaluation covers one scenario with 9 injected items and was tuned on that scenario.
- Calibration uses about 150 responses per non-core item, so many variant comparisons end as “requires review”. Data were simulated with a guessing parameter but fitted with 1PL Rasch; there is no 2PL/3PL model.
- Verbal items cannot be machine-proven correct; template text spaces are finite.
- The Anthropic LLM adapter has only been tested with a mocked provider.
- Leak detection scans only imported datasets; it cannot monitor messaging platforms.
- Single-tenant UI, no proctoring, identity verification, accommodations or multilingual content; no MFA/SSO.
- JWTs are held in `sessionStorage`; the audit chain is not protected against someone able to rewrite the whole database.
- Docker stack not executed locally; no load or scalability benchmarks are recorded beyond the small concurrency check.
- In demo mode the `enforce_slot_window` policy is off.

Full list: [docs/known-limitations.md](docs/known-limitations.md) and [docs/security-review.md](docs/security-review.md).

**Possible future work (proposals, not commitments):** validate on official or real data using the existing pipeline
([docs/dataset-schema.md](docs/dataset-schema.md)); independent checks of the MH/response-time/Rasch implementations;
2PL/3PL models; OIDC with httpOnly cookies; external write-once audit storage; hardening and load testing.

**AI-assistance disclosure.** This prototype was designed and implemented with substantial assistance from an AI coding
assistant (Anthropic Claude via Claude Code), directed and reviewed by the team.

## Team

| Name | Role |
|---|---|
| Tahaseen Khan | Team Lead |
| Shaurya Singhal | Team Member |
| Bharti Chaudhary | Team Member |
| Priyanshi Saraswat | Team Member |

## Acknowledgements

The repository documents no sponsors, mentors or dataset providers. The project brief refers to Integraminds as the
source of the (unavailable) official datasets.

## License

No license file has been identified in this repository, so no reuse permissions are granted or should be assumed.
