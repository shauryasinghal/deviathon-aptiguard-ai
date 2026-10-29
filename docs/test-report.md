# Test report (actually executed, 2026-10-29T07:46:26+00:00)

## Automated tests
`cd backend && .venv/bin/python -m pytest -q` → **115 passed** (unit: generators/verifiers, duplicates, CTT, Rasch recovery,
TOST, risk score, assembly constraints & infeasibility, MH/BH leak statistics, CSV-injection; integration over HTTP:
RBAC matrix, generation→review→approval, independence rule, failed-validation gate, calibration, response/leak imports
incl. invalid files, detection of every injected leak, investigation workflow, quarantine, assembly overlap & reproducibility,
candidate flow with answer-key protection, duplicate/invalid submissions, reports, policy validation).

`cd frontend && npm run build` → succeeds (TypeScript strict). All 10 staff routes plus candidate routes were loaded in a browser against the live API with no console errors.
No Playwright E2E suite was written (time); the E2E flow was exercised manually and through the HTTP integration tests.

## Synthetic-scenario evaluation (`scripts/run_validation.py`) — NOT real-world accuracy
Leak detection: 9/9 injected items flagged (recall 1.0), medium+ alerts on non-injected items: none (precision 1.0).
Low-severity family/template alerts (decoy posts, by design): LOG-DIR-H2-V02, QNT-INT-M2-V02, QNT-RATIO-M2-V02.
Ability-confounded slots 4 and 9 (+0.30/+0.35 logits) produced no false alerts.

| Item | Severity | Evidence class | Text detectable before slot | Statistical onset slot |
|---|---|---|---|---|
| LOG-CODE-M1-S | critical | confirmed_text_match | 3 | 3 |
| LOG-CODE-M2-V01 | high | confirmed_text_match | 9 | None |
| LOG-ORDER-H1-S | medium | statistical_suspicion | None | 10 |
| LOG-SERIES-E1-S | critical | confirmed_text_match | 3 | 3 |
| QNT-PCT-M1-S | critical | confirmed_text_match | 3 | 5 |
| QNT-PROB-M1-V02 | high | confirmed_text_match | 9 | None |
| QNT-SDT-M1-S | critical | confirmed_text_match | 3 | 3 |
| VRB-ANALOGY-M1-S | critical | confirmed_text_match | 3 | 3 |
| VRB-SYN-E1-S | critical | confirmed_text_match | 3 | 4 |

Calibration (CTT + Rasch (MML-EM, N(0,1) ability prior)) on 4 simulated non-parallel variants (true offset in logits):

| Variant | True offset | Estimated Δ | 90% CI | Decision |
|---|---|---|---|---|
| VRB-ANALOGY-E1-V02 | +0.9 | 1.049 | [0.625, 1.473] | outside_tolerance |
| VRB-ANT-H1-V01 | +0.95 | 0.597 | [0.159, 1.034] | requires_review |
| LOG-ORDER-M2-V02 | -0.85 | -0.162 | [-0.578, 0.255] | requires_review |
| LOG-SERIES-E3-V03 | -0.9 | -0.995 | [-1.539, -0.451] | requires_review |

Other administered variants: {'insufficient_data': 80, 'requires_review': 41, 'within_tolerance': 4}. With ~150 responses per item, most comparisons are
honestly *inconclusive* rather than falsely “equivalent”; one simulated drift was under-estimated (3PL-like guessing data
fitted with Rasch, plus small n).

Assembly (run 1): 9 adjacent pairs, max shared 0 items
(0.0% vs limit 10.0%), independent verification violations: [].
