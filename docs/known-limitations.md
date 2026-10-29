# Known limitations (honest status)

Implemented & tested: everything in the README demo sequence.

Simulated / prototype-only
- All data synthetic; official 1,500-item bank and leak dataset not available. Importers exist but were only exercised on synthetic files.
- Auth: local JWT (HS256) in sessionStorage, demo passwords. Production needs OIDC/SSO, httpOnly cookies, rate limiting, MFA.
- No live monitoring of Telegram/social media/internet — only imported, authorised datasets are searched.
- LLM adapter (Anthropic) is written but untested without an API key; deterministic templates are the default.

Not done (time)
- Docker/Docker Compose files, Playwright E2E suite, PDF slide decks / full doc set requested in the brief.
- Verbal items: correctness cannot be machine-proven; always flagged for human review.
- Rasch only (no 2PL/3PL); guessing in real data compresses estimates for hard items.
- Template parameter spaces are finite: some cells (e.g. easy probability) support only ~14 distinct non-clone items.
- Single tenant; organisation switcher is display-only.
- Slot time windows are not enforced for candidates in demo mode.
