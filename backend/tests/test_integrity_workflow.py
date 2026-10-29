"""Staff resolution of flagged attempts, assignment removal, deadline policy and concurrency-sensitive paths."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import Attempt, AuditEvent, Candidate, CandidateAssignment, ExposureEvent, TestForm

V1 = "/api/v1"


def _drive(client, auth, name, seed, candidates):
    cfg = {"drive": name, "n_slots": 1, "per_section": {"QUANT": 3, "LOGICAL": 3, "VERBAL": 3},
           "max_adjacent_overlap_pct": 0, "max_slot_exposures": 5, "min_slot_spacing": 0, "seed": seed}
    run = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()
    assert run["status"] == "succeeded", run["diagnostics"]
    assert client.post(f"{V1}/assembly/runs/{run['id']}/publish", headers=auth("designer")).json()["published"] == 1
    fid = run["forms"][0]["id"]
    if candidates:
        assert client.post(f"{V1}/assembly/forms/{fid}/assignments", json={"candidate_codes": candidates}, headers=auth("designer")).status_code == 201
    return run, fid


def test_flagged_attempt_resolution_workflow(client, auth, db):
    run, fid = _drive(client, auth, "Resolution drive", 301, ["DEMO-CAND-02"])
    h = auth("candidate2")
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    items = client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()["items"]
    client.put(f"{V1}/assessment/attempts/{at['attempt_id']}/responses",
               json={"answers": [{"item_ref": i["item_ref"], "selected_key": "A"} for i in items]}, headers=h)
    q1 = run["forms"][0]["items"][0]["question_id"]
    rv = auth("reviewer")
    client.post(f"{V1}/exposure/items/{q1}/quarantine", json={"reason": "Reported in a forum thread"}, headers=rv)

    url = f"{V1}/integrity/attempts/{at['attempt_id']}/resolution"
    body = {"decision": "use_alternative", "reason": "Question confirmed exposed before the slot."}
    assert client.post(url, json=body, headers=rv).status_code == 409  # still in progress: decide after submission
    res = client.post(f"{V1}/assessment/attempts/{at['attempt_id']}/submit", headers=h).json()["result"]
    assert "integrity review" in res["status_note"] and "final" not in res

    for role in ("designer", "analyst", "candidate2"):
        assert client.post(url, json=body, headers=auth(role)).status_code == 403
    assert client.get(f"{V1}/integrity/flagged-attempts", headers=auth("designer")).status_code == 403
    pending = client.get(f"{V1}/integrity/flagged-attempts", headers=rv).json()["items"]
    me = next(x for x in pending if x["attempt_id"] == at["attempt_id"])
    assert me["decision"] == "pending" and me["alternative_max"] == me["official_max"] - 1 and me["candidate"] == "DEMO-CAND-02"
    assert "display_name" not in str(me) and "Demo Candidate" not in str(me)

    assert client.post(url, json={"decision": "use_alternative", "reason": "short"}, headers=rv).status_code == 422
    assert client.post(url, json={"decision": "invent", "reason": "x" * 20}, headers=rv).status_code == 422
    out = client.post(url, json=body, headers=rv).json()
    assert out["decision"] == "use_alternative" and out["resolutions"][-1]["by"]["name"] == "Dr. Kavya Iyer"
    db.expire_all()
    a = db.get(Attempt, at["attempt_id"])
    assert a.score == out["official_score"]  # official score never overwritten
    assert a.review_flags["resolutions"][-1]["final_score"] == out["alternative_score"]
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "assessment.flag_resolved", AuditEvent.entity_id == str(a.id)))
    view = client.get(f"{V1}/assessment/attempts/{a.id}", headers=h).json()["result"]
    assert view["final"]["max_score"] == out["alternative_max"] and "withdrawn" in view["final"]["basis"]
    assert "items" not in str(view)  # candidate never sees which question

    # new evidence reopens the decision; history is kept
    q2 = run["forms"][0]["items"][1]["question_id"]
    client.post(f"{V1}/exposure/items/{q2}/quarantine", json={"reason": "Second report"}, headers=rv)
    db.expire_all()
    a = db.get(Attempt, at["attempt_id"])
    assert a.review_flags["decision"] == "pending" and a.review_flags["reopened_at"] and len(a.review_flags["resolutions"]) == 1
    out2 = client.post(url, json={"decision": "retain_original", "reason": "Exposure window was after this slot."}, headers=rv).json()
    assert [r["decision"] for r in out2["resolutions"]] == ["use_alternative", "retain_original"]
    csv = client.get(f"{V1}/reports/attempt_reviews.csv", headers=auth("analyst")).text
    assert f"{a.id},DEMO-CAND-02" in csv and "retain_original" in csv and "Demo Candidate" not in csv
    assert client.get(f"{V1}/reports/attempt_reviews.csv", headers=h).status_code == 403
    for q in (q1, q2):
        client.post(f"{V1}/exposure/items/{q}/release", json={"reason": "Cleared after review"}, headers=rv)


def test_resolution_requires_a_flag_and_same_org(client, auth, db):
    a = db.scalar(select(Attempt).where(Attempt.review_flags.is_(None), Attempt.status == "submitted"))
    r = client.post(f"{V1}/integrity/attempts/{a.id}/resolution", json={"decision": "retain_original", "reason": "nothing to do here"}, headers=auth("reviewer"))
    assert r.status_code == 409
    assert client.post(f"{V1}/integrity/attempts/99999999/resolution", json={"decision": "retain_original", "reason": "x" * 12}, headers=auth("reviewer")).status_code == 404


def test_assignment_removal_rules(client, auth, db):
    run, fid = _drive(client, auth, "Unassign drive", 302, ["DEMO-CAND-01", "DEMO-CAND-03"])
    url = f"{V1}/assembly/forms/{fid}/assignments"
    assert client.delete(f"{url}/DEMO-CAND-01", headers=auth("reviewer")).status_code == 403
    assert client.delete(f"{url}/DEMO-CAND-01", headers=auth("designer")).status_code == 200
    assert client.get(f"{V1}/assessment/forms/{fid}", headers=auth("candidate1")).status_code == 404
    assert client.delete(f"{url}/DEMO-CAND-01", headers=auth("designer")).status_code == 404
    client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=auth("candidate3"))
    assert client.delete(f"{url}/DEMO-CAND-03", headers=auth("designer")).status_code == 409  # started: preserved


def test_deadline_mode_slot_end_caps_late_starts(client, auth, db):
    adm = auth("admin")
    assert client.put(f"{V1}/settings/policies/assessment", json={"values": {"deadline_mode": "whenever"}}, headers=adm).status_code == 422
    run, fid = _drive(client, auth, "Deadline drive", 303, ["DEMO-CAND-01"])
    f = db.get(TestForm, fid)
    from app.db.base import utcnow

    f.slot.starts_at = utcnow() - timedelta(minutes=50)
    f.slot.ends_at = utcnow() + timedelta(minutes=10)  # 10 minutes of slot left, form lasts 40
    db.commit()
    assert client.put(f"{V1}/settings/policies/assessment", json={"values": {"deadline_mode": "slot_end"}}, headers=adm).status_code == 200
    try:
        at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=auth("candidate1")).json()
        assert at["remaining_seconds"] <= 10 * 60 + 5
    finally:
        client.put(f"{V1}/settings/policies/assessment", json={"values": {"deadline_mode": "full_duration"}}, headers=adm)


def test_exposure_upsert_accumulates(db):
    from app.services.exposure.service import record_administration

    f = db.scalar(select(TestForm).where(TestForm.status == "published"))
    qid = f.items[0].question_id
    before = db.scalar(select(func.coalesce(func.sum(ExposureEvent.candidate_count), 0)).where(
        ExposureEvent.form_id == f.id, ExposureEvent.question_id == qid))
    record_administration(db, f, f.slot_id, 1)
    record_administration(db, f, f.slot_id, 2)
    db.flush()
    after = db.scalar(select(ExposureEvent.candidate_count).where(ExposureEvent.form_id == f.id, ExposureEvent.question_id == qid))
    rows = db.scalar(select(func.count()).select_from(ExposureEvent).where(ExposureEvent.form_id == f.id, ExposureEvent.question_id == qid))
    db.rollback()
    assert after == before + 3 and rows == 1


def test_start_race_returns_the_winning_attempt_without_aborting(client, auth, db, monkeypatch):
    """Deterministic version of the race found on PostgreSQL: the duplicate insert must stay inside the savepoint."""
    from app.db.session import SessionLocal
    from app.services import assessment as svc

    run, fid = _drive(client, auth, "Race drive", 304, ["DEMO-CAND-02"])
    with SessionLocal() as winner:
        cand = winner.scalar(select(Candidate).where(Candidate.code == "DEMO-CAND-02"))
        svc.start_attempt(winner, cand, winner.get(TestForm, fid))
        winner.commit()
    with SessionLocal() as loser:
        cand = loser.scalar(select(Candidate).where(Candidate.code == "DEMO-CAND-02"))
        real_scalar = loser.scalar
        state = {"hidden": True}

        def scalar(stmt, *a, **k):  # simulate the race window: the existence check misses the winner's row once
            if state["hidden"] and "FROM attempts" in str(stmt) and "candidate_assignments" not in str(stmt):
                state["hidden"] = False
                return None
            return real_scalar(stmt, *a, **k)

        monkeypatch.setattr(loser, "scalar", scalar)
        out = svc.start_attempt(loser, cand, loser.get(TestForm, fid))
        loser.commit()  # the outer transaction must still be usable
    n = db.scalar(select(func.count()).select_from(Attempt).join(Candidate).where(Candidate.code == "DEMO-CAND-02", Attempt.form_id == fid))
    assert n == 1 and out["status"] == "in_progress"
