# AptiGuard AI: Round 2 readiness audit (read-only)

Audit date: 2026-10-30. Scores are an engineering estimate, not an official judging result.
The exact problem statement is **not in the repository**; the compliance matrix in section 4 is provisional.

## 1. Executive summary

- **What it is:** a working end-to-end prototype with a broad, well-tested backend. FastAPI and React; the lifecycle from generation through review, calibration, exposure, assembly, delivery and leak detection to audit has real code and tests.
- **Main weakness:** evidence, not features. Everything runs on synthetic data, the exact problem statement is not in the repo, and the AI part is an optional adapter that has never made a real call.
- **Tests run:** backend 345 passed and 1 failed (the failure is an environment-dependent test, not a product bug, see section 5). Frontend typecheck is clean and 24 unit tests passed. Migrations have a single head, 0008. The repository hygiene scan passed.
- **Blocker for the compliance matrix:** the three problem requirements are not in the repo. The matrix in section 4 is provisional, built from the audit request and the README.
- **Estimated score: about 58-70 out of 100**, with the largest uncertainty in "problem statement compliance". Details in section 7.

## 2. Actual repository architecture

- **Backend:** `backend/app` is a FastAPI modular monolith. Routers are in `api/v1` (auth, questions, variants, calibration, exposure, leaks, assembly, assessment, integrity, reports, system, dashboard). Domain logic is in `services/` with no HTTP concerns, and SQLAlchemy 2 models are in `models/`.
- **Database:** SQLite by default and PostgreSQL supported. Alembic migrations 0001-0008 have a single head.
- **Frontend:** `frontend/src` is React 19 with Vite 8, TanStack Query and React Router. Pages cover Dashboard, Questions, Variants, Review, Calibration, Exposure, Leaks, Assembler, Reports, Settings, Assessment and the auth pages.
- **Other pieces:** `scripts/` holds seed, validation and admin tools. `data/synthetic/` has hashed synthetic datasets. There is a GitHub Actions workflow, Dockerfiles and two Compose files.
- **Size and state:** about 10.9k lines in the files counted. At audit time the authentication work was **uncommitted** (HEAD `0aac169`), and `PROJECT_CONTEXT_HANDOVER.md` was untracked and out of date.

## 3. Feature status

Legend: VERIFIED means code inspected and covered by a test that passed (SQLite, synthetic data). That is not the same as validated on real data.

| Feature | Status | Code evidence | Test evidence | Gap | Priority |
|---|---|---|---|---|---|
| Template question and variant generation | VERIFIED | `services/generation/{quant,logical,verbal,engine}.py`, `POST /questions/{qid}/variants:generate` | `test_generation_validation.py`, E2E journey 2 | Verbal answer keys can't be machine-proven | P2 |
| LLM variant generation | IMPLEMENTED BUT UNTESTED | `generation/llm_adapter.py` (structured output, `LLMUnavailable`, prompt version) | Mocked only (`test_adversarial.py`) | No real provider call ever made, no key. API parameters unconfirmed against the SDK | **P1** |
| Correctness and duplicate validation | VERIFIED | `validation/validator.py`, `services/textsim.py` (0.93 fail, 0.86 warn) | `test_generation_validation.py` | Thresholds are heuristics, not tuned | P2 |
| Human review gate | VERIFIED | `variants.py:decide` (re-validates, blocks critical failures, author != approver by policy) | `test_integrity_workflow`, E2E journey 8 | `request_regeneration` re-generates without a separate review | P3 |
| Question bank lifecycle | PARTIALLY VERIFIED | `questions.py`, `add_revision`, quarantine and retire in `exposure/service.py:set_item_state` | API tests | No explicit un-approve or edit-after-approval flow was traced | P2 |
| CTT and Rasch calibration | PARTIALLY VERIFIED | `calibration/ctt.py`, `rasch.py` (EM marginal ML, 1PL) | `test_reference_stats.py` (Wilson and Newcombe checked against references) | Rasch has no external-package comparison. About 150 responses per item gives mostly "requires review" | P1 |
| Exposure control | VERIFIED (logic) | `exposure/service.py` (risk score, `eligibility`, atomic `record_administration`) | Concurrency check, tests | Limits are enforced at **assembly eligibility**. No check found at candidate start | P2 |
| Leak detection | PARTIALLY VERIFIED | `leakage/{text_match,stats,service}.py`: text match, Mantel-Haenszel, response-time test, BH correction | `run_validation.py`: 9/9 recall on a scenario the thresholds were tuned on | Not independent. Uses simulated posts only | P1 |
| Test assembly (10 slots) | VERIFIED | `assembly/algorithm.py`, `verify_plan` | Tests, E2E journeys 3-4 | Enforces difficulty bands, not measured equivalence | P2 |
| Candidate delivery and server timing | VERIFIED | `assessment.py` | Tenant and timing tests | Time on screen, not attention | P3 |
| Auth: demo, password, Google | PARTIALLY VERIFIED | `api/v1/auth.py`, `google_oauth.py` | Mocked Google provider, 100+ tests | **No real Google flow succeeded.** Sign-up is closed by configuration | P1 |
| Audit hash chain | VERIFIED | `services/audit.py`, `GET /audit/verify` | Tamper and deletion tests | Tamper-evident, not tamper-proof. Anchor is manual | P3 |
| Reports (CSV, JSON, PDF) | VERIFIED | `reporting/reports.py` | `test_algorithms.py` | None noted | P3 |
| Retention and pseudonymisation policies | INCOMPLETE | Stored in Settings | Rejected by API | Honestly labelled "not enforced" | P3 |
| Official-data validation | BLOCKED | `scripts/validate_official_data.py` | Synthetic fixture only | No official data | P1 |
| Docker and Compose | IMPLEMENTED BUT UNTESTED | Dockerfiles, Compose files | Run only in CI, Docker not installed locally | Hosted CI status unverified | P2 |

## 4. Three-requirement compliance matrix (provisional)

The exact requirements were not found, so these are placeholders to be corrected once the problem statement is supplied.

| Provisional requirement | Implementation | Status | Judge-ready evidence |
|---|---|---|---|
| R1. AI-assisted generation and variants, with correctness and duplicate validation, and human approval before the bank | Templates (real), LLM adapter (optional), validator, review queue | PARTIALLY VERIFIED. The "AI" part is rule-based templates plus an untested LLM path. | Variant Studio -> review queue -> approval, and the author-cannot-approve 403 |
| R2. Calibration and exposure control across slots | CTT and Rasch with TOST, exposure score, assembly constraints | PARTIALLY VERIFIED on synthetic data | Calibration Lab with CIs, and an infeasibility report with the exposure limit set to 1 |
| R3. Leakage detection | Text, statistical and response-time evidence, persisted alerts, reviewer decisions | PARTIALLY VERIFIED. The ground truth is simulated. | Run detection -> alert evidence -> confirm -> quarantine, and the 9/9 result with its caveats |

## 5. Test execution report

**Executed**

| Command | Result |
|---|---|
| `cd backend && .venv/bin/python -m pytest -q` (throwaway temp SQLite DB) | **345 passed, 1 failed**, 85 s |
| `cd frontend && npm run typecheck` | clean |
| `cd frontend && npm test` (Vitest 4.1.12) | **24 passed** (2 files) |
| `alembic heads` | `0008 (head)` |
| `python3 scripts/check_repo_hygiene.py` | passed (196 files) |
| `git check-ignore .env` / `git ls-files` | `.env` is ignored and not tracked |
| Read-only query of the live DB | 556 approved, 18 pending_review, 2 rejected questions; 11 leak alerts; 2 calibration runs; 8 users |

**The one failure:** `test_auth_security.py::test_production_guard_rejects_unsafe_configuration`. It builds `Settings(app_env="production", demo_mode=False)` and expects a missing-secret error. The settings loader reads the root `.env`, which now holds a 54-character `JWT_SECRET`, so no error is raised. That makes it an environment-dependent test, not a product bug. It passed in earlier clean runs, before `.env` held a secret.

**Not executed:** Playwright E2E; PostgreSQL suite and concurrency script; Docker and Compose; real Google login, real LLM calls, official data; hosted CI status.

**Should run later with approval:** E2E, the PostgreSQL run, `pip-audit`, `npm audit`, and a rehearsal of the demo script on a copy of the DB.

## 6. Security and configuration findings

1. **`JWT_SECRET` in `.env` is the public `.env.example` placeholder.** It is 54 characters, so the production guard would accept it, yet it is publicly known. Acceptable for local demos; rotate before any shared deployment.
2. **Registration is closed**, so Google sign-up shows "Sign-up is currently closed". For a judge demo of Google or password sign-up, `REGISTRATION_ORG_SLUG` must be set, which opens candidate sign-up into the demo tenant.
3. **Google login has never succeeded end to end.** The diagnosis showed the flow reaches the last step correctly. Only mocked tests prove the rest.
4. **No email verification or delivery.** Password reset sends nothing by default.
5. **Token in `sessionStorage`** (XSS exposure) and sessions are not device-bound. This is documented.
6. **Tenant isolation is not proven complete.** The docs say so, and the tests cover listed routes only.
7. **Local files with secrets exist** (`.env.bak-*`). They are git-ignored, but must not be zipped for submission.
8. **Demo password is public by design.** The app refuses demo mode in production.
9. Secrets are not committed, and the hygiene scan found none in tracked files.

## 7. Round 2 rubric scorecard (estimate)

| Category | Max | Estimate | Why | Highest-impact action |
|---|---|---|---|---|
| Working prototype and functionality | 25 | 18-21 | Full workflow works in demo, 345 tests pass. Real Google and LLM are unproven. | Rehearse the demo on a clean DB and record a backup video |
| Technical implementation and engineering | 20 | 14-17 | Clean layering, migrations, hash chain, atomic exposure counters, PostgreSQL tested. Auth work uncommitted. | Commit the auth work and fix the env-sensitive test |
| Problem statement compliance and effectiveness | 20 | 9-14 | The requirements are unknown, data is synthetic, and the "AI" is mostly rules. | Get the statement, then map each requirement to evidence |
| Testing, validation and reliability | 15 | 10-12 | Large suite, reference checks, concurrency. The leak evaluation is self-tuned and nothing is independent. | Add an independent leak scenario with different seeds, and a reference check of Rasch |
| Innovation | 10 | 5-7 | Server-measured timing, TOST equivalence, exposure-aware assembly, attempt review. | Present these clearly in the demo |
| Team ownership and understanding | 10 | 4-7 | Heavy AI assistance is disclosed. Judges will probe design choices. | Each member owns a module and rehearses the Q&A in section 11 |
| **Total** | 100 | **~60-74**, midpoint about 66 | | |

The two uncertain categories are compliance and team ownership. The scores are not independent: the same synthetic evidence supports several rows, so it was counted only once.

## 8. Prioritised backlog (no implementation until approved)

**P0: demo blockers**
1. Commit or stash the auth work so the repo is in a known state. About 0.5 h, category 2.
2. Make the env-sensitive production-guard test deterministic (`_env_file=None`). About 0.5 h, category 4.
3. Demo-day checklist and DB rehearsal: fresh reset on a copy, confirm the seeded demo path works. About 2 h, category 1.

**P1: core and credibility**
4. Get the real problem statement and redo section 4. About 1 h, category 3.
5. Prove the LLM path with a real key (one real call with a recorded sample input and output), or label it clearly as optional. About 3 h, categories 1 and 3.
6. Independent leak evaluation: a second seed or scenario not used for tuning, reported with confidence intervals. About 4 h, categories 3 and 4.
7. Real Google test: enable registration temporarily and record a successful login, or drop Google from the demo. About 1 h, category 1.
8. Calibration sanity check: compare Rasch estimates with a known reference on simulated data. About 4 h, category 4.

**P2: reliability and inspection**
9. Add a candidate-start exposure check, or document that limits apply at assembly. About 3 h.
10. Run Playwright and the PostgreSQL suite and update `docs/test-report.md`, which still says 220 and 267 tests. About 2 h.
11. Update the stale `PROJECT_CONTEXT_HANDOVER.md` and the Vitest version line in the README. About 1 h.

**P3: optional**
12. Show per-item CI plots and form-comparability in the demo.
13. Anchor-hash export for the audit log.

## 9. Six-minute demo plan (only verified features)

| Time | Action | Expected |
|---|---|---|
| 0:00 | State the problem and the synthetic-data disclaimer in two sentences | |
| 0:30 | Log in as Analyst via one-click demo login, open Command Center | KPIs and slot comparison |
| 1:00 | Leak Detection, run detection, open a critical alert | Text, drift and response-time evidence |
| 2:00 | Switch to Reviewer, confirm leak with a note | Item quarantined, forms flagged |
| 2:45 | Designer, Variant Studio, generate variants | Answers recomputed, rejections shown with reasons |
| 3:30 | Designer tries to approve (403). Reviewer approves | Independent review enforced |
| 4:00 | Calibration Lab: CIs, Rasch +/- SE, TOST "requires review" | Honest sample-size warnings |
| 4:45 | Assembler: 10 slots, then exposure limit 1 | Infeasibility report |
| 5:30 | Settings, Audit, Verify integrity | Chain valid |

**Recovery:** if anything stalls, run `scripts/seed_demo.py` on a spare DB and keep a recorded video. Don't show Google login or the LLM unless backlog items 5 and 7 are done.

## 10. Four-minute technical inspection checklist

- `git log` and the commit state of the auth work.
- Test counts and CI config, then the migration chain (`alembic heads`).
- Permission map in `core/security.py` and `variants.py:decide`.
- Rasch EM in `rasch.py`, exposure scoring in `exposure/service.py`, and the atomic upsert.
- `docs/known-limitations.md`, and the AI-assistance disclosure.

## 11. Likely judge questions

- **Where is the AI?** Candidate variants come from deterministic templates with recomputed answers. An optional LLM path exists but is untested live. Say so plainly.
- **How do you know a variant is equivalent?** TOST on Rasch difficulty. Inconclusive results are never counted as equivalent.
- **Does leak detection work?** It found 9 of 9 injected items on a scenario its thresholds were tuned on, so it is not independent evidence.
- **Can a generated question bypass review?** No. New items land in `pending_review` and the author cannot approve them.
- **What about concurrency?** Atomic upsert counters and a live four-worker check on SQLite and PostgreSQL.
- **What don't you do?** No proctoring, MFA, real-data validation or enforced retention.

## 12. Before submission

- [ ] Provide the problem statement and redo section 4.
- [ ] Commit the authentication work.
- [ ] Fix the one environment-sensitive test.
- [ ] Rehearse the demo on a copy of the database and record a backup.
- [ ] Refresh `docs/test-report.md` with current counts.
- [ ] Decide whether to demo Google login, and if so enable registration temporarily.
- [ ] Rotate `JWT_SECRET` for anything shared, and exclude `.env*` files from any zip.
