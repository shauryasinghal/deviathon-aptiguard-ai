# Test report — executed 2026-10-29 (actual results, current working tree)

Environment: macOS arm64, Python 3.12.7, Node 26.8.1, PostgreSQL 17.10 (local throw-away cluster), Chromium headless
shell (Playwright 1.64). Docker is not installed locally. Every row below was executed; nothing is estimated.

| Check | Command | Result |
|---|---|---|
| Backend unit + integration (SQLite) | `cd backend && .venv/bin/python -m pytest -q` | **220 passed** |
| Backend unit + integration (PostgreSQL 17) | `TEST_DATABASE_URL=postgresql+psycopg://…/aptiguard_test …pytest -q` | **220 passed** |
| Clean checkout | fresh copy of the tree → `./setup.sh` → backend tests | **setup OK, 219 passed (before the 220th test was added)** |
| Migrations from scratch + drift | `alembic upgrade head && alembic check` | **no drift** on SQLite and PostgreSQL |
| PostgreSQL downgrade/upgrade | `alembic downgrade 0003 && alembic upgrade head && alembic check` | **pass** |
| Live concurrency (4 uvicorn workers) | `scripts/concurrency_check.py` | **pass** on SQLite and PostgreSQL (below) |
| Production boot rehearsal (no containers) | migrate → bootstrap → create admin → serve on PostgreSQL with `APP_ENV=production` | **pass** (below) |
| Clean restart | state persisted; revoked token 401; rate limit persisted (429); audit chain ok | **pass** |
| Frontend unit/component | `cd frontend && npm test` | **9 passed** |
| Type check / production build | `npm run typecheck` / `npm run build` | **pass** / **pass** |
| Browser E2E | `npx playwright test` | **7 passed** (below) |
| Python dependency audit | `pip-audit -r backend/requirements.txt` | **no known vulnerabilities** |
| npm audit (runtime deps) | `npm audit --omit=dev` | **0 vulnerabilities** |
| Repository hygiene | `python3 scripts/check_repo_hygiene.py` (+ negative control) | **pass** (171 files); planted secret detected |
| Compose / workflow schemas | official compose-spec and SchemaStore GitHub-workflow JSON schemas | **valid** |
| Official-data validation | `scripts/validate_official_data.py` | **BLOCKED** (exit 3: no official data) |
| Synthetic pipeline check | fixture → `validate_official_data.py` | **COMPLETED** (labelled synthetic) |

Not executed: Docker builds / Compose (Docker unavailable; `scripts/docker_smoke.sh` runs in CI), `actionlint` and
`hadolint` (binary download not permitted locally; run in CI), hosted GitHub Actions for these changes (requires a push),
real LLM provider calls (mocked only), official data (not supplied).

## Live concurrency (real parallel HTTP requests, then database inspection)
30 simultaneous starts by 3 candidates on one form, 30 parallel answer saves, 10 simultaneous submits racing 20 saves.
Both engines: every start 201 (no 5xx), exactly one attempt per candidate, exposure count exactly 3 for every item
(no lost increments), 1 submit succeeded and 9 were rejected with 409, 0 responses written after scoring, 0 duplicate
response rows, stored score = recomputed score, 0 server exceptions.

## Production boot rehearsal (PostgreSQL, `APP_ENV=production`)
Unsafe config (`DEMO_MODE=true`) refused to start with a sanitised message; migrations 0001–0005 applied; bootstrap
created 19 permissions, 5 roles, 3 sections; demo seed refused; admin created; `/ready` reported 0 questions (no seeding);
demo-status exposed no demo data; demo login 401; admin login + dashboard 200; audit chain verified.

## Browser E2E journeys (Playwright, hermetic backend on a throw-away DB)
1 login, role routing, refresh, logout (server-side revocation) and route protection · 2 generate → validate → review →
approve · 3+4 assemble verified forms → publish → assign → candidate attempt and submission · 5 leak detection →
evidence → confirm and quarantine · 6 calibration → CSV export · 7 item quarantined during a live attempt → reviewer
resolves the flag in the UI · 8 author cannot approve own item (server-enforced, shown in UI).

## Backend suite composition (220)
- `test_auth_security.py` — demo sign-in per role, email normalisation, unknown-user/wrong-password parity, inactive
  accounts, 7 bad-token classes, rate limiting, no password in audit, production guard, `APP_ENV` validation,
  sanitised configuration errors, demo credentials hidden when demo mode is off, seed refusal, headers.
- `test_security_hardening.py` — logout revokes all sessions, admin revocation (allowed/denied/404), limiter shared and
  persistent with hashed keys, audit chain verification + tamper and deletion detection, migration 0004 backfill,
  bootstrap idempotence and admin password policy, failed login on a fresh database with no organisation (401, not 500).
- `test_access_control.py` — assignment-only access, unpublished forms, slot window, deadline + auto-submit, partial
  batches, quarantine → reassessment → release, publish re-check, assignment rules, cross-organisation isolation,
  413, live-attempt flag policy, save-vs-submit race (proven to fail without the guard), other candidates' attempts,
  seed refusal on foreign organisations.
- `test_integrity_workflow.py` — flagged-attempt resolution (roles, in-progress refusal, validation, history, no score
  overwrite, reopen on new evidence, candidate-visible status without item details, report, 403 for candidates),
  unassignment rules, `deadline_mode=slot_end`, atomic exposure upsert, start race inside the savepoint (proven to fail
  with the old code).
- `test_data_pipeline.py` — BLOCKED without data or provenance, full synthetic pipeline run (inputs unmodified, hashes,
  labels, dev-only metrics with CIs, independent assembly check), import policy (structural reject, duplicates held).
- `test_reference_stats.py` — Wilson and Newcombe intervals vs the worked examples in Newcombe (1998); Benjamini–Hochberg
  vs values hand-derived from the BH definition (R was not run); single-stratum MH vs the odds ratio and SciPy's Yates
  χ²; zero cells; item–rest r; Rasch SE coverage on simulated data. **Not covered by external references:** multi-stratum
  MH with purification, ETS class thresholds, the response-time test, TOST beyond its decision logic, Rasch point
  estimates vs another IRT package.
- `test_adversarial.py`, `test_generation_validation.py`, `test_algorithms.py`, `test_api_integration.py` — templates,
  verifiers, duplicate/clone detection, CTT/Rasch/TOST, exposure, assembly, MH/BH, reports, API flows, bank invariant.

## Synthetic-scenario evaluation — NOT real-world accuracy
One deterministic scenario: 9 injected leaked items (6 text+performance, 1 statistical-only, 2 text-only), 3 decoy
posts, 25 unrelated posts, 2 ability-shifted cohorts. At medium severity or higher: 9/9 detected, 0 alerts on the 547
non-leaked bank items. With n = 9 the recall's Wilson 95% CI is [0.70, 1.00]; FPR 0/547, CI [0, 0.007]. These labels are
the *development* scenario the thresholds were designed on, so they are not independent validation.
Details: `docs/evidence/validation_results.json` and the synthetic pipeline report.
