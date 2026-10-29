# Security review (prototype) — what is enforced, what is not

Scope: OWASP Top 10 (web) and OWASP API Security Top 10 themes, reviewed against the code in this repository.
This is a manual review plus automated tests and dependency audits. **It does not prove the application is secure.**

## Enforced and tested

| Area | Control | Evidence (tests) |
|---|---|---|
| Authentication | bcrypt (cost 12); one generic error for unknown user / wrong password / inactive account; timing-equalised for unknown users | `test_auth_security.py` |
| Brute force | per client+email failure limiter (8 / 5 min → 429 with Retry-After), stored in the database (`auth_failures`, SHA-256 keys, no raw emails): shared by all API processes and survives restarts; other accounts unaffected | `test_login_rate_limited_after_repeated_failures`, `test_limiter_state_is_shared_and_survives_restart`, live restart check |
| Tokens / sessions | HS256 JWT with required `exp, iat, sub, iss, tv`, `nbf`, `jti`; expired, wrong-key, wrong-issuer, unsigned (`alg=none`), malformed and unknown-user tokens rejected. Sign-out bumps the user's `token_version`, revoking every outstanding token ("sign out everywhere"); admins can revoke another user's sessions | `test_bad_tokens_rejected` (7 cases), `test_logout_revokes_all_sessions_of_that_user`, `test_admin_can_revoke_sessions_others_cannot` |
| Audit-log integrity | append-only hash chain (`prev_hash`, `hash` = SHA-256 over the previous hash and a canonical event); writers serialised (PostgreSQL advisory lock / SQLite write lock); `GET /audit/verify` and a UI button report the first edited, deleted or re-ordered event | `test_audit_chain_verifies_and_detects_tampering`, `test_deleting_an_audit_event_breaks_the_chain`, `test_migration_0004_backfills_existing_audit_rows` |
| Configuration secrets | invalid configuration is reported with rule messages only — values (JWT secret, DB credentials) are never echoed | `test_configuration_errors_never_echo_secret_values` |
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
| Containers | non-root user (`app`, uid 10001) in the API image; unprivileged nginx; `.dockerignore` keeps venvs, local databases, backups and `.env` out of images; migrations run first and any failure stops the container | `scripts/docker_smoke.sh` (runs in CI — not executed locally) |
| Dependencies | `pip-audit`: no known vulnerabilities after upgrading FastAPI/Starlette, PyJWT, python-multipart, pydantic-settings, pytest; `npm audit --omit=dev`: 0 | see test report |

## Known residual risks (not fixed)

1. **Token storage**: JWT in `sessionStorage` is readable by injected script (XSS). Production should use an OIDC
   provider with httpOnly, SameSite cookies, short-lived access tokens and refresh rotation. Revocation is per user
   (all sessions), not per device. Upgrading to migration 0004 invalidates tokens issued before it (they lack `tv`).
2. **Rate limiting** is keyed by client + email, so an attacker can temporarily lock out a known email (5 minutes).
   Behind a reverse proxy, uvicorn must trust the proxy (`--forwarded-allow-ips`, set in the container) so the real
   client address is used. There is no per-IP global limit.
3. **Audit chain** detects tampering by anyone who cannot also recompute later hashes; a database administrator
   could rewrite the whole chain. Ship events to write-once external storage for stronger guarantees.
4. **Demo password is public** by design (synthetic accounts only). Never enable `DEMO_MODE` on a deployment holding real data.
5. **Single-tenant UI**: data is org-scoped server-side, but there is no tenant administration or SSO.
6. **No MFA, no password policy/rotation, no account lockout notifications.**
7. **Proctoring/anti-cheating** (browser lockdown, identity verification) is out of scope.
8. **CSP** is only set by the nginx container config, not by the Vite dev server.
9. Leak detection searches **only imported datasets**; it does not and cannot monitor messaging platforms.
