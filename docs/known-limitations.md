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
  decision is made by a reviewer in **Reviewer Workspace → Flagged attempts** (retain original, use alternative, or arrange
  reassessment, with a mandatory reason; recorded with reviewer and time, audited, history kept; new evidence reopens the
  decision). A "reassessment" decision is recorded but the re-sit itself is arranged manually by assigning another form.
- Late starts: by default an attempt gets its full duration (`deadline_mode=full_duration`); the policy
  `deadline_mode=slot_end` caps the deadline at the slot's end. Which one applies is a human policy decision.
- Answer saves are accepted up to 30 s after the deadline (network grace); later saves are rejected and the attempt is auto-submitted.
- Login rate limiting is per client address + email: repeated failures can temporarily (5 min) lock out a known email.
- No proctoring, identity verification, accommodations (extra time) or multilingual content.

## Engineering
- **Docker**: images, `docker-compose.yml` (demo) and `docker-compose.prod.yml` (PostgreSQL, no demo) are written and
  statically validated (Compose JSON schema; shell syntax), but **not executed locally** — Docker is not installed on the
  build machine and installing it was out of scope. `scripts/docker_smoke.sh` runs them in GitHub Actions after a push.
  The production start-up sequence (migrate → bootstrap → create admin → serve) was rehearsed outside containers on PostgreSQL.
- **Linters**: `actionlint` and `hadolint` run only in CI (downloading their binaries locally was not permitted).
- **PostgreSQL 17** is tested: the full backend suite, migrations from scratch, `alembic check`, a downgrade/upgrade
  round-trip and a live multi-worker concurrency check all pass on a local throw-away cluster.
- Tokens remain in `sessionStorage`; revocation is per user, not per device (see security review).

## Hardening round 2 (what changed, what did not)
- **Tenant isolation:** `GET /review/queue` returned the latest review decisions of *every* organisation (reviewer names,
  comments, item codes); the response importer matched forms across organisations and `_ensure_slots` matched slots by
  drive name only. Fixed and covered by `backend/tests/test_tenant_isolation.py`. That test probes the object-level routes
  listed in it; routes added later must be added there. Isolation is **not** proven complete.
- **Shared namespaces:** `Slot.code`, `TestForm.code`, `Question.code`, `VariantFamily.code` and `LeakAlert.code` are still
  globally unique. The importer refuses codes owned by another organisation (422) and generated slot codes get an `-O<org>`
  suffix on collision. `Slot (org, drive, sequence)` and `Candidate (org, code)` are per-organisation since migration 0007
  (downgrade fails if two organisations now share such values).
- **Response times** are measured by the server from `focus` events (migration 0006). Client `time_spent_ms` is accepted
  but ignored. A time interval is capped at 15 minutes; a missed navigation event misattributes time to the previous item;
  an item never reported on screen has no response time (NULL). This is time-on-screen, not attention or reading time,
  and a response time alone is not evidence of cheating. Older/scripted clients that send no `focus` events produce no RT data.
- **Expiry:** expired attempts are finalised by a sweep every `EXPIRY_SWEEP_SECONDS` (default 60, per API process; safe with
  several workers), by `scripts/finalize_expired.py`, and before calibration and leak detection. If the sweeper is disabled
  and nothing else runs, attempts are still only finalised lazily. Auto-submitted attempts are stamped at their deadline.
- **Policies not enforced** (read-only in the UI, rejected by the API): `retention.response_retention_days`,
  `retention.audit_retention_days`, `retention.pseudonymize_candidates`, `review.verbal_requires_second_look`. No data is
  deleted or anonymised; a retention design (what, who, how audit evidence survives) is needed first.
- **Audit anchor:** `GET /audit/verify?anchor_count=N&anchor_head=<hash>` detects removal of the newest events and a fully
  recomputed history, but only if the operator stored `checked`/`head` somewhere the database administrator cannot write.
  Nothing stores it automatically.
- **Form comparability** is an advisory mean-difficulty comparison from the latest Rasch run (`services/assembly/comparability.py`).
  Assembly still enforces band counts, not equivalence; calibrated coverage must reach 80% of a form before forms are compared.

### Review follow-ups (round 3)
- **Resume semantics:** `POST /assessment/forms/{id}/attempts` on an in-progress attempt discards the open timing interval
  (unobserved time is not credited). A second browser tab therefore also interrupts the first tab's current interval.
  Out-of-order events from two tabs can misattribute time between items, but the total credited never exceeds elapsed
  wall-clock time because there is a single pointer per attempt. A candidate (or script) controls *when* focus events are
  sent, so response times are server-measured, not tamper-proof.
- **Late submit:** `submit` after deadline + 30 s grace finalises the attempt at its deadline (same as the sweep). Answers
  saved inside the grace window (up to 30 s after the deadline) are scored although `submitted_at` is the deadline.
- **Slot pace normalisation** in the response-time test (`leakage/stats.py`, `slot_rt`) uses the median over all rows,
  including unanswered ones; item-level response-time tests use answered rows only. Not changed (would alter results).
- **Migration 0007 downgrade** fails cleanly (revision stays 0007, no data lost) if two organisations share a candidate code or drive/sequence.
