"""Server-side access control for assessments, forms and cross-organisation data (allowed and denied requests)."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.models import (
    Attempt,
    Candidate,
    CandidateAssignment,
    Organization,
    Question,
    Role,
    TestForm,
    User,
)

V1 = "/api/v1"


def _assigned_forms(db, code):
    cand = db.scalar(select(Candidate).where(Candidate.code == code))
    return [a.form_id for a in db.scalars(select(CandidateAssignment).where(CandidateAssignment.candidate_id == cand.id)).all()]


def _unassigned_published_form(db, code):
    mine = set(_assigned_forms(db, code))
    return next(f for f in db.scalars(select(TestForm).where(TestForm.status == "published")).all() if f.id not in mine)


def test_candidate_lists_only_assigned_forms(client, auth, db):
    listed = {f["form_id"] for f in client.get(f"{V1}/assessment/available", headers=auth("candidate3")).json()["forms"]}
    assert listed == set(_assigned_forms(db, "DEMO-CAND-03")) and listed


def test_candidate_cannot_open_or_start_unassigned_form(client, auth, db):
    f = _unassigned_published_form(db, "DEMO-CAND-03")
    h = auth("candidate3")
    assert client.get(f"{V1}/assessment/forms/{f.id}", headers=h).status_code == 404
    assert client.post(f"{V1}/assessment/forms/{f.id}/attempts", headers=h).status_code == 404
    assert db.scalar(select(Attempt).join(Candidate).where(Candidate.code == "DEMO-CAND-03", Attempt.form_id == f.id)) is None


def test_unpublished_form_cannot_be_started_even_if_assigned(client, auth, db):
    fid = _assigned_forms(db, "DEMO-CAND-03")[0]
    f = db.get(TestForm, fid)
    prev = f.status
    f.status = "draft"
    db.commit()
    try:
        r = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=auth("candidate3"))
        assert r.status_code == 409
    finally:
        f.status = prev
        db.commit()


def test_slot_window_enforced_when_policy_on(client, auth, db):
    h_admin = auth("admin")
    assert client.put(f"{V1}/settings/policies/assessment", json={"values": {"enforce_slot_window": True}}, headers=h_admin).status_code == 200
    try:
        fid = _assigned_forms(db, "DEMO-CAND-03")[0]  # upcoming drive: slot starts in the future
        r = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=auth("candidate3"))
        assert r.status_code == 409 and r.json()["error"]["details"]["state"] == "not_yet_open"
        avail = client.get(f"{V1}/assessment/available", headers=auth("candidate3")).json()["forms"]
        assert not any(f["can_start"] for f in avail if f["form_id"] == fid)
    finally:
        client.put(f"{V1}/settings/policies/assessment", json={"values": {"enforce_slot_window": False}}, headers=h_admin)


def test_answers_rejected_after_deadline_and_attempt_auto_submitted(client, auth, db):
    h = auth("candidate1")
    fid = _assigned_forms(db, "DEMO-CAND-01")[0]
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    form = client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()
    a = db.get(Attempt, at["attempt_id"])
    a.deadline_at = utcnow() - timedelta(minutes=5)
    db.commit()
    r = client.put(f"{V1}/assessment/attempts/{a.id}/responses",
                   json={"answers": [{"item_ref": form["items"][0]["item_ref"], "selected_key": "A"}]}, headers=h)
    assert r.status_code == 409
    db.refresh(a)
    assert a.status == "submitted"
    assert client.post(f"{V1}/assessment/attempts/{a.id}/submit", headers=h).status_code == 409
    score = a.score
    assert client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()["attempt_id"] == a.id  # no second attempt
    db.refresh(a)
    assert a.score == score


def test_invalid_batch_does_not_partially_save(client, auth, db):
    h = auth("candidate2")
    fid = _assigned_forms(db, "DEMO-CAND-02")[0]
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    if at["status"] != "in_progress":
        pytest.skip("attempt already used by another test")
    form = client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()
    good = form["items"][1]["item_ref"]
    r = client.put(f"{V1}/assessment/attempts/{at['attempt_id']}/responses",
                   json={"answers": [{"item_ref": good, "selected_key": "C"}, {"item_ref": 10 ** 9, "selected_key": "A"}]}, headers=h)
    assert r.status_code == 422
    st = client.get(f"{V1}/assessment/attempts/{at['attempt_id']}", headers=h).json()
    assert str(good) not in st["answers"]


def test_quarantine_flags_forms_and_blocks_new_attempts_then_release_restores(client, auth, db):
    fid = _assigned_forms(db, "DEMO-CAND-03")[0]
    f = db.get(TestForm, fid)
    qid = f.items[0].question_id
    h_rev = auth("reviewer")
    r = client.post(f"{V1}/exposure/items/{qid}/quarantine", json={"reason": "Possible exposure under review"}, headers=h_rev)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(TestForm, fid).status == "needs_review"
    assert client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=auth("candidate3")).status_code == 409
    manifest = client.get(f"{V1}/assembly/forms/{fid}", headers=auth("designer")).json()
    assert manifest["status"] == "needs_review" and manifest["validation"]["reassessment"]["question_id"] == qid
    assert client.post(f"{V1}/exposure/items/{qid}/release", json={"reason": "Cleared after review"}, headers=h_rev).status_code == 200
    db.expire_all()
    assert db.get(TestForm, fid).status == "published"


def test_publish_rechecks_item_eligibility(client, auth, db):
    cfg = {"drive": "Publish recheck drive", "n_slots": 2, "per_section": {"QUANT": 3, "LOGICAL": 3, "VERBAL": 3},
           "max_adjacent_overlap_pct": 0, "max_slot_exposures": 3, "min_slot_spacing": 2, "seed": 5}
    run = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()
    assert run["status"] == "succeeded"
    qid = run["forms"][0]["items"][0]["question_id"]
    q = db.get(Question, qid)
    q.leak_status = "suspected"  # e.g. raised by detection after assembly but before publishing
    db.commit()
    try:
        out = client.post(f"{V1}/assembly/runs/{run['id']}/publish", headers=auth("designer")).json()
        assert out["published"] == 1 and out["blocked"][0]["items"][0]["code"] == q.code
    finally:
        q.leak_status = "none"
        db.commit()


def test_assignment_rules(client, auth, db):
    cfg = {"drive": "Assignment drive", "n_slots": 1, "forms_per_slot": 2, "per_section": {"QUANT": 3, "LOGICAL": 3, "VERBAL": 3},
           "max_adjacent_overlap_pct": 0, "max_slot_exposures": 3, "min_slot_spacing": 2, "seed": 11}
    run = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()
    assert run["status"] == "succeeded"
    f1, f2 = run["forms"][0]["id"], run["forms"][1]["id"]
    assert client.post(f"{V1}/assembly/forms/{f1}/assignments", json={"candidate_codes": ["DEMO-CAND-03"]}, headers=auth("reviewer")).status_code == 403
    assert client.post(f"{V1}/assembly/forms/{f1}/assignments", json={"candidate_codes": ["NOPE"]}, headers=auth("designer")).status_code == 409
    r = client.post(f"{V1}/assembly/forms/{f1}/assignments", json={"candidate_codes": ["DEMO-CAND-03"]}, headers=auth("designer")).json()
    assert r["added"] == ["DEMO-CAND-03"]
    r2 = client.post(f"{V1}/assembly/forms/{f2}/assignments", json={"candidate_codes": ["DEMO-CAND-03"]}, headers=auth("designer")).json()
    assert r2["added"] == [] and "slot" in r2["skipped"][0]["reason"]
    # same-slot forms obey the overlap limit too
    shared = set(i["code"] for i in run["forms"][0]["items"]) & set(i["code"] for i in run["forms"][1]["items"])
    assert not shared


def test_candidate_cannot_reach_staff_or_other_results(client, auth):
    h = auth("candidate1")
    for url in ("/questions", "/leaks/alerts", "/assembly/runs", "/calibration/items", "/reports/question_bank.csv", "/audit"):
        assert client.get(V1 + url, headers=h).status_code == 403
    assert client.get(f"{V1}/assessment/attempts/1", headers=auth("candidate3")).status_code in (404,)


@pytest.fixture(scope="module")
def other_org(seeded):
    """A second tenant with one user and one question, to check cross-organisation isolation."""
    from app.core.security import hash_password
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        org = Organization(name="Other Tenant", slug="other-tenant")
        db.add(org)
        db.flush()
        role = db.scalar(select(Role).where(Role.name == "admin"))
        db.add(User(org_id=org.id, email="admin@other.test", full_name="Other Admin", password_hash=hash_password("Other-Tenant-Pass-1"), role_id=role.id))
        src = db.scalar(select(Question).where(Question.code == "QNT-INT-E1-S"))
        q = Question(code="OTHER-Q-1", org_id=org.id, section_id=src.section_id, family_id=src.family_id, skill="x", stem="Other tenant question stem text",
                     explanation="x", difficulty_target="easy", status="approved", normalized_hash="other", is_synthetic=True)
        db.add(q)
        db.commit()
        return {"question_id": q.id}


def test_cross_org_isolation(client, auth, other_org):
    h = auth("admin")
    qid = other_org["question_id"]
    assert client.get(f"{V1}/questions/{qid}", headers=h).status_code == 404
    assert client.get(f"{V1}/exposure/items/{qid}/history", headers=h).status_code == 404
    assert client.post(f"{V1}/exposure/items/{qid}/quarantine", json={"reason": "cross tenant"}, headers=h).status_code == 404
    assert "OTHER-Q-1" not in str(client.get(f"{V1}/search?q=OTHER", headers=h).json())
    tok = client.post(f"{V1}/auth/login", json={"email": "admin@other.test", "password": "Other-Tenant-Pass-1"}).json()["access_token"]
    oh = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"{V1}/questions?page_size=5", headers=oh).json()["total"] == 1
    assert client.get(f"{V1}/leaks/alerts", headers=oh).json()["total"] == 0


def test_oversized_request_rejected(client, auth):
    big = "x" * (13 * 1024 * 1024)
    r = client.post(f"{V1}/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ------------------------------------------------------------------ pre-commit review regressions
def test_quarantine_during_live_attempt_flags_but_never_invalidates(client, auth, db):
    """Policy: the candidate keeps going, the official score is computed as normal, staff get an auditable flag with an
    alternative score excluding the withdrawn item; releasing the item annotates (does not delete) the flag."""
    from app.models import AuditEvent

    h = auth("candidate1")
    fid = _assigned_forms(db, "DEMO-CAND-01")[1]
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    assert at["status"] == "in_progress"
    form = client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()
    refs = [i["item_ref"] for i in form["items"]]
    client.put(f"{V1}/assessment/attempts/{at['attempt_id']}/responses",
               json={"answers": [{"item_ref": r, "selected_key": "A"} for r in refs[:5]]}, headers=h)
    withdrawn_qid = db.get(TestForm, fid).items[0].question_id
    rv = auth("reviewer")
    assert client.post(f"{V1}/exposure/items/{withdrawn_qid}/quarantine", json={"reason": "Possible exposure mid-slot"}, headers=rv).status_code == 200

    # the candidate is not interrupted: resume, save and submit all still work
    assert client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()["attempt_id"] == at["attempt_id"]
    assert client.put(f"{V1}/assessment/attempts/{at['attempt_id']}/responses",
                      json={"answers": [{"item_ref": refs[6], "selected_key": "B"}]}, headers=h).status_code == 200
    res = client.post(f"{V1}/assessment/attempts/{at['attempt_id']}/submit", headers=h).json()
    assert res["status"] == "submitted" and res["result"]["max_score"] == len(refs)  # official score covers all items
    assert "review_flags" not in str(res)  # staff-only

    db.expire_all()
    a = db.get(Attempt, at["attempt_id"])
    flags = a.review_flags
    assert flags["decision"] == "pending" and flags["items"][0]["question_id"] == withdrawn_qid
    assert flags["items"][0]["attempt_status_when_flagged"] == "in_progress"
    assert flags["max_excluding_flagged"] == a.max_score - 1 and flags["score_excluding_flagged"] <= a.score
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "assessment.attempts_flagged")) is not None

    staff = client.get(f"{V1}/assembly/forms/{fid}/attempts", headers=auth("designer")).json()
    assert any(x["attempt_id"] == a.id and x["review_flags"] for x in staff)
    assert client.get(f"{V1}/assembly/forms/{fid}/attempts", headers=h).status_code == 403
    assert client.get(f"{V1}/assembly/forms/{fid}", headers=auth("designer")).json()["flagged_attempts"] >= 1

    # a second withdrawal after submission is flagged too, with a recomputed alternative score
    second = db.get(TestForm, fid).items[1].question_id
    client.post(f"{V1}/exposure/items/{second}/quarantine", json={"reason": "Second exposure report"}, headers=rv)
    db.expire_all()
    a = db.get(Attempt, at["attempt_id"])
    assert len(a.review_flags["items"]) == 2 and a.review_flags["max_excluding_flagged"] == a.max_score - 2
    assert a.review_flags["items"][1]["attempt_status_when_flagged"] == "submitted"

    for q in (withdrawn_qid, second):
        client.post(f"{V1}/exposure/items/{q}/release", json={"reason": "Cleared after review"}, headers=rv)
    db.expire_all()
    a = db.get(Attempt, at["attempt_id"])
    assert all("released_at" in i for i in a.review_flags["items"])  # annotated, not deleted
    assert db.get(TestForm, fid).status == "published"


def test_save_cannot_land_on_an_attempt_scored_concurrently(client, auth, db):
    """Deterministic reproduction of the save/submit race: the save session still believes the attempt is live."""
    from app.core.errors import Conflict
    from app.db.session import SessionLocal
    from app.models import Response
    from app.services import assessment as svc

    h = auth("candidate3")
    fid = _assigned_forms(db, "DEMO-CAND-03")[0]
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    if at["status"] != "in_progress":
        pytest.skip("attempt already used")
    ref = client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()["items"][2]["item_ref"]
    with SessionLocal() as s_save:
        cand = s_save.scalar(select(Candidate).where(Candidate.code == "DEMO-CAND-03"))
        stale = s_save.get(Attempt, at["attempt_id"])
        assert stale.status == "in_progress"
        assert client.post(f"{V1}/assessment/attempts/{at['attempt_id']}/submit", headers=h).status_code == 200
        with pytest.raises(Conflict):
            svc.save_answers(s_save, at["attempt_id"], cand, [{"item_ref": ref, "selected_key": "D"}])
        s_save.rollback()
    db.expire_all()
    from app.models import FormItem
    qid = db.get(FormItem, ref).question_id
    r = db.scalar(select(Response).where(Response.attempt_id == at["attempt_id"], Response.question_id == qid))
    assert r is None or r.is_correct is not None  # nothing written after scoring


def test_candidate_cannot_save_or_submit_another_candidates_attempt(client, auth, db):
    a = db.scalar(select(Attempt).join(Candidate).where(Candidate.code == "DEMO-CAND-01"))
    h = auth("candidate3")
    assert client.put(f"{V1}/assessment/attempts/{a.id}/responses", json={"answers": []}, headers=h).status_code == 404
    assert client.post(f"{V1}/assessment/attempts/{a.id}/submit", headers=h).status_code == 404


def test_seed_refuses_to_wipe_database_with_foreign_organisation(other_org, db):
    from sqlalchemy import func

    from app.demo.seed import seed_demo

    before = db.scalar(select(func.count()).select_from(Question))
    with pytest.raises(RuntimeError, match="non-demo organisation"):
        seed_demo(db)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Question)) == before
    assert db.scalar(select(Organization).where(Organization.slug == "other-tenant")) is not None
