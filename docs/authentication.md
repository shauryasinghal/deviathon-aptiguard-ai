# Authentication

AptiGuard AI supports three sign-in methods side by side. All of them end in the **same** session: the existing
HS256 JWT (`create_access_token`) with `token_version` revocation, the same role/permission checks and the same audit log.

| Method | Who | Endpoints |
|---|---|---|
| **Email + password** | Anyone with an account; new **candidates** may self-register | `POST /auth/login`, `POST /auth/register`, `POST /auth/password/forgot`, `POST /auth/password/reset`, `POST /auth/logout` |
| **Continue with Google** | Candidates (sign-up and sign-in); existing accounts can *link* Google | `GET /auth/google/start`, `GET /auth/google/callback`, `POST /auth/google/exchange`, `POST /auth/google/link/start` |
| **Demo login** | The seeded synthetic accounts (`*@aptiguard.demo`), demo mode only | unchanged `POST /auth/login`; `GET /demo-status` lists the accounts |

`GET /auth/providers` tells the login page what is switched on (`google`, `registration`, `demo_mode`); it exposes no secrets.
All paths are under `/api/v1`.

## Demo login is unchanged

* The eight demo accounts keep their emails, roles, organisation and the shared `DEMO_PASSWORD`; `/auth/login` and
  `/demo-status` behave exactly as before (regression tests: `tests/test_registration_password.py`, "demo login regression").
* Demo accounts do **not** depend on Google or registration settings.
* The domain `@aptiguard.demo` (and subdomains) is **reserved**: nobody can register it, request or complete a password
  reset for it, sign in with Google using it, or link a Google identity to it. Demo credentials are public by design, so
  these accounts must never be convertible into ordinary ones. Demo credentials are still shown only when
  `DEMO_MODE=true` outside production.

## Who can register, and as what

* Public registration (password or Google) creates **only a `candidate`**, with only the `assessment.take` permission.
  The request body is validated with `extra="forbid"`: a client-supplied `role`, `org_id`, `permissions`… is rejected (422), not ignored.
* The organisation is **never** chosen by the client. It is the organisation whose slug is in `REGISTRATION_ORG_SLUG`.
  **Empty (the default) = self-registration disabled** (`403 registration_disabled`; the UI shows "Sign-up is currently closed").
* Staff, analyst and administrator accounts are created by an administrator (`scripts/create_admin.py` for the first one).
  A Google email match never grants or merges anything (below).

## Email and password

* Registration: name (≤ 80), email (validated, normalised to lower case, ≤ 160), password ≥ 12 characters and ≤ 72 bytes
  (bcrypt ignores the rest, so longer passwords are refused rather than silently truncated), not a trivial/common password,
  not containing the email name. Passwords are hashed with bcrypt (cost 12). Duplicate emails return `409 email_taken`
  (the unique constraint decides, so concurrent registrations create exactly one account).
  *Trade-off:* a 409 reveals that an address is registered. Registration is rate limited (10 per client per hour).
* **No email verification.** Anyone can register any address; an address squatted this way cannot later be registered
  or used for Google sign-up by its real owner (Google then reports "account exists"). Adding verification needs email delivery.
* Login failures, rate limiting, generic errors and timing equalisation are the existing behaviour. Failed logins for
  addresses that match no account are **not** written to any organisation's audit log (they only feed `auth_failures`).

### Forgot / reset password

* `POST /auth/password/forgot` always answers `202` with the same text for unknown, inactive, demo and rate-limited addresses.
  Rate limits: 10 requests per client and 3 per address per hour (the per-address cap is silent).
* A reset token is `secrets.token_urlsafe(32)`, stored **hashed** (SHA-256) in `auth_tokens`, valid
  `PASSWORD_RESET_TTL_MINUTES` (default 30), single use (atomic `UPDATE … WHERE used_at IS NULL AND expires_at > now`),
  and a new request invalidates earlier links.
* `POST /auth/password/reset` re-checks the password policy **before** consuming the token (a weak password does not burn
  the link), sets the new hash, bumps `token_version` (**every existing session of that account is revoked**), and audits the event.
* **No email service exists in this project.** `PASSWORD_RESET_DELIVERY=none` (default) sends nothing: the endpoint still
  answers generically but nobody receives a link. `PASSWORD_RESET_DELIVERY=log` writes the link to the server log for local
  development only and is refused when `APP_ENV=production`. The token is never returned in an HTTP response. Production
  needs a real mail provider wired into `_deliver_reset` in `app/api/v1/auth.py`.

## Google sign-in (authorization-code flow + PKCE, server side)

1. `GET /auth/google/start` creates a single-use **state**, **nonce** and **PKCE verifier** (stored hashed/server side in
   `auth_tokens`, valid 10 minutes), sets an HttpOnly `SameSite=Lax` cookie `ag_oauth_bind` that ties the flow to this
   browser (login-CSRF protection), and redirects to Google with scope `openid email profile` only.
2. Google redirects to `GET /auth/google/callback`. The backend consumes the state (single use), checks the browser cookie,
   exchanges the code **server side** with the client secret and the PKCE verifier, and validates the ID token: RS256
   signature against Google's published keys (`PyJWKClient`), `iss` (`https://accounts.google.com` / `accounts.google.com`),
   `aud` = your client id, `exp`, `iat`, required claims, the **nonce**, and `email_verified`. The stable identity is
   Google's `sub`, stored in `external_identities` with unique `(provider, subject)`.
3. The browser is redirected to a **fixed** frontend route (`FRONTEND_URL` + `/auth/callback`) carrying only a one-time
   *login ticket* (60 s, single use, hashed at rest) or a fixed error code. Nothing from the request is echoed into the
   redirect, so there is no open redirect. The SPA exchanges the ticket with `POST /auth/google/exchange` for our own JWT
   (same as `/login`), and removes the ticket from the address bar. No Google token or secret ever reaches the browser.

Outcomes of the callback:

| Situation | Result |
|---|---|
| Identity (`sub`) already linked | sign in as that user (inactive or demo users are refused) |
| No identity, **no** account with that email | create a **candidate** (only if registration is enabled), link the identity, sign in |
| No identity, an account with that email exists (password, staff, demo…) | **refused** (`google_account_exists`): never merged on an email match |
| Email not verified, consent denied, invalid/expired/reused state, bad token, provider outage | refused with a fixed error code; nothing is created |

### Linking Google to an existing account

Only the signed-in owner can do it: `POST /auth/google/link/start` (bearer token) → the browser goes through the same flow in
*link* mode. The link succeeds only if the verified Google email **equals** the account's email, the Google account is not
already linked elsewhere, and the account has no Google identity yet. Demo accounts cannot start it. The UI offers it in
Settings → System (staff) and on the candidate home page. There is no "unlink" yet.

## Data model (migration `0008`)

`external_identities(user_id → users, provider, subject, email, created_at)` with `UNIQUE(provider, subject)` and
`UNIQUE(user_id, provider)`; `auth_tokens(kind, token_hash UNIQUE, user_id, payload, expires_at, used_at)` for OAuth state,
login tickets and reset tokens. Two new tables only; no existing row or column is changed. `users.password_hash` stays
NOT NULL: accounts created through Google get a bcrypt hash of a random secret nobody knows, so password login is impossible
until the owner uses "forgot password".

**The live database must be migrated explicitly** (`cd backend && .venv/bin/alembic upgrade head`) after a backup; until
then the new endpoints fail on the missing tables while demo and password login keep working.
Downgrade (`alembic downgrade 0007`) drops both tables: linked Google identities and pending tokens are lost, local accounts are untouched.

## Configuration

| Variable | Meaning |
|---|---|
| `REGISTRATION_ORG_SLUG` | Organisation that self-registered candidates join. Empty = sign-up disabled. (The seeded demo tenant's slug is `integraminds-demo`.) |
| `FRONTEND_URL` | Where the OAuth callback sends the browser. Default `http://localhost:5173`. Must be `https` in production. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From Google Cloud Console. Backend environment only; never committed, never sent to the browser. |
| `GOOGLE_REDIRECT_URI` | Default `http://localhost:8000/api/v1/auth/google/callback`. Must match the console **exactly**. `https` required in production. |
| `PASSWORD_RESET_DELIVERY` | `none` (default) or `log` (dev only, refused in production). |
| `PASSWORD_RESET_TTL_MINUTES` | Reset-link lifetime, 5–120, default 30. |

Put them in a git-ignored `.env` at the repository root (see `.env.example`); `start.sh` needs no change.

## Google Cloud Console setup (local development)

1. Open <https://console.cloud.google.com/>, create or select a project.
2. Open **Google Auth Platform** (APIs & Services → OAuth consent screen). If prompted, click **Get started** and fill **Branding**:
   app name (e.g. "AptiGuard AI"), user-support email, developer contact email.
3. **Audience**: choose **External**. Leave the publishing status on **Testing**. Under *Test users* add every Google account
   that should be able to sign in (only listed test users can sign in while the app is in Testing; limit 100).
4. **Data access** (scopes): `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`. These are non-sensitive, so no Google verification is needed.
5. **Clients → Create client → Application type: Web application**, name it, then:
   * **Authorised JavaScript origins**: `http://localhost:5173` (this flow runs on the server, but registering the app origin is harmless and expected).
   * **Authorised redirect URIs**: exactly `http://localhost:8000/api/v1/auth/google/callback`
     (this is the route implemented in `app/api/v1/auth.py`; scheme, host, port and path must match character for character; `localhost` and `127.0.0.1` are different hosts).
6. Click **Create** and copy the **Client ID** and **Client secret**. Do not paste them into chat or commit them.
7. Create/edit `.env` in the repository root:
   ```
   GOOGLE_CLIENT_ID=<your client id>
   GOOGLE_CLIENT_SECRET=<your client secret>
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
   FRONTEND_URL=http://localhost:5173
   REGISTRATION_ORG_SLUG=integraminds-demo     # only if you want Google/password sign-up enabled; candidates join the demo tenant
   ```
8. Apply migration 0008 to your database (backup first), then **restart the backend** (`.env` is read at start-up): stop `./start.sh`
   (Ctrl+C) and run it again. `GET /api/v1/auth/providers` should now report `"google": true`.
9. Test: open <http://localhost:5173/login> → **Continue with Google** → choose a listed test user → you land on the candidate page
   (first time: a candidate account is created). Sign out and repeat: it signs the same user in. To test linking, register or sign
   in with a password account whose email equals the Google address, then use **Link Google account**.

Use the same browser host for the whole flow (`localhost`, not `127.0.0.1`): the state cookie is host-scoped.

### Going public later (not needed locally)

* Register an **https** redirect URI and set `FRONTEND_URL` to the https origin (the backend refuses to start in production otherwise).
* Move the consent screen to **In production**; for the basic scopes above Google does not require app verification, but you must provide
  branding, privacy-policy and terms links and authorised domains for a public app.
* Serve the API and SPA over https on the same site, keep the secret in a secret manager, and review the limitations below.

## Tests

`backend/tests/test_registration_password.py` (registration, login, reset, rate limits, demo regression, authorisation),
`test_google_oauth.py` (mocked provider with a locally generated RSA key: state/CSRF, ID-token validation, linking, takeover protection),
`test_auth_migration.py` (migration on a disposable database), `frontend/tests/unit/auth.test.tsx`, and Playwright journeys 9–11.
Google's token endpoint and key set are replaced in tests; **no real Google flow has been run** by the test suite.

## Known limitations

* Not production ready: no email verification, no email delivery, no MFA, no account lock-out notification, no unlink, no admin UI for staff invitations.
* The bearer token still lives in `sessionStorage` and sessions are not bound to devices (see `docs/security-review.md`).
* The login ticket travels in a URL for up to 60 seconds (single use, stripped by the SPA, `Referrer-Policy: no-referrer` on the API).
* Registration reveals whether an email is taken; reset answers do not.
* Failed logins for real accounts are still audited in the shared global audit chain (unchanged design).
