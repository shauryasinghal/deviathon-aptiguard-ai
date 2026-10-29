# Known limitations (honest status)

## Data and evaluation
- All data are synthetic (seed 107). The official 1,500-item bank and leak dataset were not available; importers were
  exercised only with synthetic files and malformed test files.
- Leak-detection results cover **one** synthetic scenario with **9** injected leaked items (6 text+performance,
  1 statistical-only, 2 text-only) plus 3 decoy posts and 25 unrelated posts. They say nothing about real-world accuracy.
- Statistical signals vary with the random realisation: in the current seed two text-leaked items show no significant
  performance shift, so they are flagged on text evidence alone.
- Calibration uses ~150 responses per non-core item; most variant comparisons are therefore *requires review*
  (inconclusive), which is the honest outcome at this sample size. Data were simulated with a guessing parameter and
  fitted with Rasch (1PL), so hard items' differences are compressed. No 2PL/3PL model.

## Content
- Verbal items cannot be machine-proven correct; all are flagged for mandatory human review.
- Template text spaces are finite. After enforcing the near-duplicate gate, narrow templates (e.g. reading inference,
  syllogisms) have smaller families; the generator reports when it cannot produce a non-duplicate variant.
- Difficulty labels of generated items are a-priori template bands until calibrated on responses.
- The optional Anthropic LLM adapter is tested only with a mocked provider (no API key was available).

## Product
- Single tenant in the UI (organisation switcher is display-only); server-side org scoping is enforced.
- In demo mode the assessment policy `enforce_slot_window` is **off** (visible in Settings and on the candidate page)
  because the seeded upcoming drive is in the future. It is on by default for new deployments.
- **Item withdrawn while attempts exist** (quarantine, retirement or confirmed leak): new starts on affected forms are
  blocked; attempts already started continue and are scored normally (official score unchanged). Each affected attempt
  gets a staff-only review flag with an alternative score excluding the withdrawn item(s), and an audit event. The final
  decision (accept official score, use the alternative, or offer a re-sit) is **not yet an in-app workflow** — flags are
  visible via `GET /api/v1/assembly/forms/{id}/attempts` and as a count in the Assembler.
- Attempts that start late in the slot window still receive their full duration (deadline = start + duration).
- Answer saves are accepted up to 30 s after the deadline (network grace); later saves are rejected and the attempt is auto-submitted.
- Login rate limiting is per client address + email: repeated failures can temporarily (5 min) lock out a known email.
- No proctoring, identity verification, accommodations (extra time) or multilingual content.

## Engineering
- Docker images, docker-compose and the GitHub Actions workflow are written but were **not executed** (Docker not
  installed on the build machine; CI runs only after a push).
- Rate limiting is in-process; tokens are not revocable (see security review).
- SQLite is the tested database; PostgreSQL is supported by SQLAlchemy/Alembic but was not run in this environment.
