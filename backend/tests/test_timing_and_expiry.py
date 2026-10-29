"""Server-observed item timing and reliable finalisation of expired attempts."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.base import utcnow
from app.models import Attempt, AuditEvent, Response
from app.services import assessment as svc
from tests.test_integrity_workflow import _drive

V1 = "/api/v1"
_seed = iter(range(401, 460))


def _start(client, auth, db, who="candidate2", code="DEMO-CAND-02"):
    run, fid = _drive(client, auth, f"Timing drive {next(_seed)}", next(_seed) + 1000, [code])
    h = auth(who)
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    refs = [i["item_ref"] for i in client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()["items"]]
    return h, at["attempt_id"], refs, fid


def _responses(db, aid):
    db.expire_all()
    from app.models import FormItem

    out = {}
    for r in db.scalars(select(Response).where(Response.attempt_id == aid)).all():
        fi = db.scalar(select(FormItem).where(FormItem.question_id == r.question_id,
                                              FormItem.form_id == db.get(Attempt, aid).form_id))
        out[fi.id] = r
    return out


def _backdate_interval(db, aid, seconds):
    a = db.get(Attempt, aid)
    a.current_item_since = a.current_item_since - timedelta(seconds=seconds)
    db.commit()


def test_client_reported_time_is_ignored(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    r = client.put(f"{V1}/assessment/attempts/{aid}/responses",
                   json={"answers": [{"item_ref": refs[0], "selected_key": "A", "time_spent_ms": 3_000_000}]}, headers=h)
    assert r.status_code == 200
    assert _responses(db, aid)[refs[0]].response_time_ms is None  # nothing observed by the server => unknown, not 3000 s


def test_server_clock_measures_interval_and_duplicates_are_noops(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    url = f"{V1}/assessment/attempts/{aid}/focus"
    assert client.post(url, json={"item_ref": refs[0]}, headers=h).json() == {"recorded": True}
    assert client.post(url, json={"item_ref": refs[0]}, headers=h).json() == {"recorded": False}  # refresh / retry
    _backdate_interval(db, aid, 7)
    assert client.post(url, json={"item_ref": refs[1]}, headers=h).json() == {"recorded": True}
    ms = _responses(db, aid)[refs[0]].response_time_ms
    assert 6900 <= ms <= 9000  # 7 s back-dated + test execution time
    assert client.post(url, json={"item_ref": refs[1]}, headers=h).json() == {"recorded": False}
    assert _responses(db, aid)[refs[0]].response_time_ms == ms  # duplicate did not credit anything again
    # returning to an earlier item accumulates, it does not overwrite
    _backdate_interval(db, aid, 3)
    client.post(url, json={"item_ref": refs[0]}, headers=h)
    assert 2900 <= _responses(db, aid)[refs[1]].response_time_ms <= 5000


def test_interval_is_capped_and_submit_closes_the_open_interval(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    client.post(f"{V1}/assessment/attempts/{aid}/focus", json={"item_ref": refs[2]}, headers=h)
    _backdate_interval(db, aid, 3 * 3600)  # walked away for three hours
    res = client.post(f"{V1}/assessment/attempts/{aid}/submit", headers=h)
    assert res.status_code == 200
    assert _responses(db, aid)[refs[2]].response_time_ms == svc.MAX_ITEM_INTERVAL_MS
    db.expire_all()
    a = db.get(Attempt, aid)
    assert a.current_item_ref is None and a.current_item_since is None


def test_focus_rejects_invalid_sequences(client, auth, db):
    h, aid, refs, fid = _start(client, auth, db)
    url = f"{V1}/assessment/attempts/{aid}/focus"
    assert client.post(url, json={"item_ref": 10 ** 9}, headers=h).status_code == 422
    assert client.post(url, json={"item_ref": "x"}, headers=h).status_code == 422
    assert client.post(url, json={}, headers=h).status_code == 422
    # fresh login: the cached token may have been revoked by an earlier sign-out test
    tok = client.post(f"{V1}/auth/login", json={"email": "candidate3@aptiguard.demo", "password": "AptiGuard-Demo-2026"}).json()["access_token"]
    assert client.post(url, json={"item_ref": refs[0]}, headers={"Authorization": f"Bearer {tok}"}).status_code == 404  # not their attempt
    assert client.post(url, json={"item_ref": refs[0]}).status_code == 401
    client.post(f"{V1}/assessment/attempts/{aid}/submit", headers=h)
    assert client.post(url, json={"item_ref": refs[0]}, headers=h).status_code == 409  # attempt finished


def test_stale_concurrent_event_is_discarded_by_compare_and_swap(client, auth, db):
    from app.db.session import SessionLocal
    from app.services.assessment import get_candidate

    h, aid, refs, _ = _start(client, auth, db)
    client.post(f"{V1}/assessment/attempts/{aid}/focus", json={"item_ref": refs[0]}, headers=h)
    _backdate_interval(db, aid, 5)
    with SessionLocal() as s_stale, SessionLocal() as s_fast:
        a_stale = s_stale.get(Attempt, aid)  # request B read the attempt while item 0 was current
        assert a_stale.current_item_ref == refs[0]
        cand = get_candidate(s_fast, _user_of(s_fast, aid))
        assert svc.focus_item(s_fast, aid, cand, refs[1]) == {"recorded": True}  # request A wins
        s_fast.commit()
        cand2 = get_candidate(s_stale, _user_of(s_stale, aid))
        assert svc.focus_item(s_stale, aid, cand2, refs[2]) == {"recorded": False}  # request B is stale
        s_stale.commit()
    resp = _responses(db, aid)
    credited = resp[refs[0]].response_time_ms
    assert 4900 <= credited <= 8000
    assert db.get(Attempt, aid).current_item_ref == refs[1]
    assert refs[2] not in resp  # the losing event credited nothing


def _user_of(s, aid):
    from app.models import Candidate

    return s.get(Candidate, s.get(Attempt, aid).candidate_id).user_id


# ------------------------------------------------------------------ expiry / finalisation
def _expire(db, aid, seconds_past_deadline):
    a = db.get(Attempt, aid)
    a.deadline_at = utcnow() - timedelta(seconds=seconds_past_deadline)
    db.commit()


def _submitted_events(db, aid):
    return db.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "assessment.attempt_submitted", AuditEvent.entity_id == str(aid)))


def test_expired_attempt_is_finalised_without_candidate_activity(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    client.put(f"{V1}/assessment/attempts/{aid}/responses", json={"answers": [{"item_ref": refs[0], "selected_key": "A"}]}, headers=h)
    client.post(f"{V1}/assessment/attempts/{aid}/focus", json={"item_ref": refs[1]}, headers=h)
    _backdate_interval(db, aid, 600)  # the item has been "open" for 10 minutes
    _expire(db, aid, 60)  # deadline passed 60 s ago (> 30 s grace)
    db.expire_all()
    deadline = db.get(Attempt, aid).deadline_at
    assert svc.finalize_expired(db) >= 1
    db.expire_all()
    a = db.get(Attempt, aid)
    assert a.status == "submitted" and a.score is not None and a.max_score == len(refs)
    assert a.submitted_at == deadline  # stamped at the deadline, not at sweep time
    assert a.current_item_ref is None
    # the open interval is clipped to the deadline: only the ~540 s before the deadline can be credited, never the sweep delay
    ms = _responses(db, aid)[refs[1]].response_time_ms
    assert ms <= svc.MAX_ITEM_INTERVAL_MS and ms <= 600_000
    assert _submitted_events(db, aid) == 1


def test_expiry_boundary_respects_the_grace_period(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, svc.GRACE_SECONDS - 10)  # inside the network grace period
    svc.finalize_expired(db)
    db.expire_all()
    assert db.get(Attempt, aid).status == "in_progress"
    _expire(db, aid, svc.GRACE_SECONDS + 5)
    svc.finalize_expired(db)
    db.expire_all()
    assert db.get(Attempt, aid).status == "submitted"


def test_finalisation_is_idempotent_and_never_double_scores(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 120)
    svc.finalize_expired(db)
    db.expire_all()
    first = db.get(Attempt, aid)
    snap = (first.score, first.submitted_at, first.section_scores)
    assert svc.finalize_expired(db) == 0
    db.expire_all()
    again = db.get(Attempt, aid)
    assert (again.score, again.submitted_at, again.section_scores) == snap
    assert _submitted_events(db, aid) == 1
    assert client.post(f"{V1}/assessment/attempts/{aid}/submit", headers=h).status_code == 409


def test_two_runners_cannot_both_finalise_the_same_attempt(client, auth, db):
    from app.core.errors import Conflict
    from app.db.session import SessionLocal

    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 120)
    with SessionLocal() as s1, SessionLocal() as s2:
        a2 = s2.get(Attempt, aid)  # runner 2 has already seen it as in_progress
        assert svc.finalize_expired(s1) >= 1  # runner 1 scores and commits
        with pytest.raises(Conflict):
            svc._finalize(s2, a2, auto=True)  # runner 2's claim fails: the guarded UPDATE matches no row
        s2.rollback()
        assert svc.finalize_expired(s2) == 0
    assert _submitted_events(db, aid) == 1


def test_interrupted_finalisation_leaves_the_attempt_retryable(client, auth, db, monkeypatch):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 120)
    real = svc.audit.record

    def boom(*a, **k):
        raise RuntimeError("simulated crash after scoring, before commit")

    monkeypatch.setattr(svc.audit, "record", boom)
    svc.finalize_expired(db)  # must not raise: the sweeper survives a failing attempt
    monkeypatch.setattr(svc.audit, "record", real)
    db.expire_all()
    a = db.get(Attempt, aid)
    assert a.status == "in_progress" and a.score is None  # whole finalisation rolled back, nothing half-scored
    assert svc.finalize_expired(db) >= 1  # the next sweep succeeds
    db.expire_all()
    assert db.get(Attempt, aid).status == "submitted" and _submitted_events(db, aid) == 1


def test_expired_attempts_are_scored_before_calibration_runs(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 300)
    assert client.post(f"{V1}/calibration/runs", json={}, headers=auth("analyst")).status_code == 201
    db.expire_all()
    assert db.get(Attempt, aid).status == "submitted"
