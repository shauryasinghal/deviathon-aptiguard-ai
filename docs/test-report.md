# Test report — executed 2026-10-29 (actual results, this checkout)

All commands below were re-run on the current working tree during the pre-commit review (an earlier pass also ran
them on a clean copy after the documented `./setup.sh`, with 191 backend tests at that time). Environment: macOS arm64, Python 3.12.7, Node 26.8.1, Chromium headless shell (Playwright 1.64).

| Check | Command | Result |
|---|---|---|
| Backend unit + integration | `cd backend && .venv/bin/python -m pytest -q` | **200 passed** |
| Python dependency audit | `pip-audit -r backend/requirements.txt` | **No known vulnerabilities** |
| Frontend unit/component | `cd frontend && npm test` | **9 passed** |
| Type check | `npm run typecheck` | **pass** |
| Production build | `npm run build` | **pass** |
| npm audit (runtime deps) | `npm audit --omit=dev` | **0 vulnerabilities** |
| Browser E2E (Playwright) | `npx playwright test` | **5 passed** (covers all 6 required journeys) |
| Synthetic ground-truth evaluation | `scripts/run_validation.py` | see below |

Not executed: Docker image builds / `docker compose` (Docker not installed), GitHub Actions CI (runs only after a push),
PostgreSQL (SQLite tested only), live LLM provider (mocked in tests; no key).

## Backend suite composition
- `test_auth_security.py` — all demo roles sign in; email normalisation; wrong-password vs unknown-user parity; inactive
  accounts; 7 bad-token classes; rate limiting; no password in audit; production guard; unknown/odd `APP_ENV` values
  rejected or normalised; demo credentials hidden when
  demo mode is off; seed refusal; security headers.
- `test_access_control.py` — assigned-only listing/opening/starting; unpublished forms; slot-window policy; deadline
  enforcement + auto-submit + no second attempt; no partial answer batches; quarantine → form reassessment → release;
  item withdrawn during a live attempt (attempt continues, official score kept, staff-only flag + alternative score,
  audit, release annotates); deterministic save-vs-submit race reproduction (fails without the row guard); other
  candidates' attempts (save/submit → 404); seed refuses a database with a non-demo organisation;
  publish re-checks eligibility; assignment rules; candidate cannot reach staff data; cross-organisation isolation; 413 on oversize.
- `test_reference_stats.py` — Wilson and Newcombe intervals vs the worked examples published in Newcombe (1998);
  Benjamini–Hochberg vs values hand-derived from the BH definition (the procedure R's `p.adjust(method="BH")`
  implements — **R itself was not run**); single-stratum Mantel–Haenszel vs the sample odds ratio and
  ((n−1)/n)·χ² with Yates correction computed by SciPy; zero-cell stability; item–rest r vs a direct NumPy computation;
  Rasch SE coverage on simulated data (a calibration check, not an external reference).
  **Not covered by external references:** multi-stratum MH with rest-score stratification and purification, ETS class
  thresholds, the response-time test, TOST beyond its decision logic, and Rasch point estimates versus another IRT package.
- `test_adversarial.py` — no distractor equals the key (16 templates × 3 bands × 60 seeds); mocked LLM output with two
  keys / wrong key / no verifier; LLM route persists only valid items as pending; explicit failure without provider;
  formatting-robust leak matching (case, whitespace, "Rs.", options appended); partial copies and siblings not
  over-claimed; re-running detection does not duplicate alerts; small groups not drift-tested; empty/large/infeasible assembly.
- `test_generation_validation.py`, `test_algorithms.py`, `test_api_integration.py` — templates, verifiers, duplicate and
  clone detection, CTT/Rasch/TOST, exposure risk, assembly constraints, MH/BH, reports, end-to-end API flows, and the
  bank-integrity invariant (no approved item carries a failed quality check).

## Synthetic-scenario evaluation — NOT real-world accuracy
Scope: one deterministic scenario, **9 injected leaked items**, 3 family-level decoy posts, 25 unrelated posts,
2 ability-shifted cohorts (slots 4 and 9).

Leak detection: 9/9 injected items flagged at medium severity or higher; medium+ alerts on
non-injected items: none. Low-severity family/template alerts from the decoy posts
(by design): LOG-DIR-H3-V03, QNT-INT-M2-V02.

| Item | Severity | Evidence class | Text detectable before slot | Statistical onset slot |
|---|---|---|---|---|
| LOG-CODE-M1-S | critical | confirmed_text_match | 3 | 5 |
| LOG-DIR-M3-V02 | high | confirmed_text_match | 9 | — |
| LOG-ORDER-H1-S | medium | statistical_suspicion | — | 7 |
| LOG-SERIES-E1-S | high | confirmed_text_match | 3 | — |
| QNT-PCT-M1-S | critical | confirmed_text_match | 3 | 5 |
| QNT-RATIO-M3-V01 | high | confirmed_text_match | 9 | — |
| QNT-SDT-M1-S | critical | confirmed_text_match | 3 | 6 |
| VRB-ANALOGY-M1-S | critical | confirmed_text_match | 3 | 5 |
| VRB-SYN-E1-S | high | confirmed_text_match | 3 | — |

Two text-leaked items show no significant ability-adjusted drift in this realisation (onset “—”); they are flagged on text evidence only.

Calibration (CTT + Rasch (MML-EM, N(0,1) ability prior)) on 4 simulated non-parallel variants (true offset in logits):

| Variant | True offset | Estimated Δ | 90% CI | Decision |
|---|---|---|---|---|
| QNT-SDT-H2-V02 | +0.9 | 0.267 | [-0.182, 0.715] | requires_review |
| QNT-PROB-H3-V01 | +0.95 | 0.945 | [0.512, 1.377] | outside_tolerance |
| QNT-SDT-E2-V02 | -0.85 | -1.218 | [-1.745, -0.692] | outside_tolerance |
| VRB-ANALOGY-H2-V03 | -0.9 | -0.544 | [-0.972, -0.117] | requires_review |

No simulated non-parallel variant is declared equivalent. Other administered variants: {'insufficient_data': 89, 'requires_review': 35, 'within_tolerance': 6}.

Assembly (run 1): 9 adjacent pairs, max shared 0 items
(0.0% vs limit 10.0%), independent verification violations: [].
