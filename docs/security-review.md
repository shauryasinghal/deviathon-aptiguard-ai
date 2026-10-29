# Security review (prototype) — what is enforced, what is not

Scope: OWASP Top 10 (web) and OWASP API Security Top 10 themes, reviewed against the code in this repository.
This is a manual review plus automated tests and dependency audits. **It does not prove the application is secure.**

## Enforced and tested

| Area | Control | Evidence (tests) |
|---|---|---|
| Authentication | bcrypt (cost 12); one generic error for unknown user / wrong password / inactive account; timing-equalised for unknown users | `test_auth_security.py` |
| Brute force | per client+email failure limiter (8 / 5 min → 429 with Retry-After); other accounts unaffected | `test_login_rate_limited_after_repeated_failures` |
| Tokens | HS256 JWT with required `exp, iat, sub, iss`, `nbf`, `jti`; expired, wrong-key, wrong-issuer, unsigned (`alg=none`), malformed and unknown-user tokens rejected | `test_bad_tokens_rejected` (7 cases) |
| Production guard | `APP_ENV` must be development/test/production (case-normalised; `prod` etc. rejected); startup fails if production runs with demo mode on, a weak/default JWT secret, or wildcard CORS; seeding refuses in production, with demo mode off, or when the database contains any non-demo organisation | `test_production_guard_rejects_unsafe_configuration`, `test_unknown_app_env_is_rejected`, `test_seed_refuses_when_demo_mode_disabled`, `test_seed_refuses_to_wipe_database_with_foreign_organisation` |
| Authorization | every route declares a permission checked server-side; role matrix tested allowed + denied | `test_rbac_matrix`, `test_candidate_cannot_reach_staff_or_other_results` |
| Object-level (IDOR) | candidates only list/open/start **assigned** forms (unassigned → 404); attempts of other candidates → 404; organisation scoping on questions, exposure history, generation runs, search, alerts, forms | `test_access_control.py` incl. `test_cross_org_isolation` |
| Assessment integrity | publish re-checks item eligibility; slot-window policy; server-side deadline; answers after deadline rejected + auto-submit; atomic submit (single `UPDATE … WHERE status='in_progress'`); race-safe start (unique constraint + savepoint); no partial answer batches | `test_access_control.py` |
| Item withdrawn mid-attempt | attempt never silently invalidated: continues, official score unchanged, staff-only review flag + alternative score + audit; save/submit serialised by a guarded row update | `test_quarantine_during_live_attempt_flags_but_never_invalidates`, `test_save_cannot_land_on_an_attempt_scored_concurrently` |
| Review integrity | authors cannot approve their own items; approval re-runs validation and blocks on critical failures | `test_reviewer_cannot_approve_own_item`, `test_failed_validation_blocks_approval` |
| Answer-key protection | candidate payloads contain no `is_correct`, explanations or item codes | `test_candidate_flow_and_answer_key_protection` |
| Input limits | Pydantic validation on every body; upload allow-list (.csv/.json/.jsonl), 10 MB cap, in-memory only (no path traversal surface); global request cap 12 MB → 413 | `test_response_import_validation`, `test_oversized_request_rejected` |
| Injection | SQLAlchemy ORM/bound parameters only (no string-built SQL); CSV formula injection neutralised | `test_csv_injection_neutralized` |
| Error handling | consistent envelope; unhandled errors return an opaque reference id, never a stack trace | `app/core/errors.py` |
| Logging/privacy | request logs contain method/path/status/timing only; failed-login audit stores email domain + reason, never the password; candidates are pseudonymous codes | `test_failed_login_audit_does_not_store_password` |
| Headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store`; CSP in the nginx config | `test_security_headers_present` |
| Dependencies | `pip-audit`: no known vulnerabilities after upgrading FastAPI/Starlette, PyJWT, python-multipart, pydantic-settings, pytest; `npm audit --omit=dev`: 0 | see test report |

## Known residual risks (not fixed)

1. **Token storage**: JWT in `sessionStorage` is readable by injected script (XSS). Production should use an OIDC
   provider with httpOnly, SameSite cookies, short-lived access tokens and refresh rotation. No token revocation list.
2. **Rate limiting is in-process**: resets on restart and is not shared across instances (use Redis or a gateway).
   Because it is keyed by client + email, an attacker can temporarily lock out a known email (5 minutes). Behind a
   reverse proxy, configure uvicorn `--forwarded-allow-ips` so the real client address is used.
3. **Demo password is public** by design (synthetic accounts only). Never enable `DEMO_MODE` on a deployment holding real data.
4. **Single-tenant UI**: data is org-scoped server-side, but there is no tenant administration or SSO.
5. **No MFA, no password policy/rotation, no account lockout notifications.**
6. **Proctoring/anti-cheating** (browser lockdown, identity verification) is out of scope.
7. **CSP** is only set by the nginx container config, not by the Vite dev server.
8. Leak detection searches **only imported datasets**; it does not and cannot monitor messaging platforms.
