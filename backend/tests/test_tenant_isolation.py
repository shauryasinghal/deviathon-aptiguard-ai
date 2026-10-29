"""Cross-organisation isolation: an administrator of tenant B must not read or change any record of the seeded tenant A.

Every object-level route is probed with identifiers that belong to tenant A. Lists must not contain tenant A's codes,
people or comments. This is a regression net, not a proof of completeness: routes added later must be added here.
"""
import pytest
from sqlalchemy import func, select

from app.models import (
    Attempt,
    AssemblyRun,
    CalibrationRun,
    LeakAlert,
    LeakDataset,
    Organization,
    Question,
    ReviewDecision,
    Role,
    TestForm,
    User,
)

V1 = "/api/v1"
PW = "Tenant-B-Passw0rd-1"


@pytest.fixture(scope="module")
def tenant_b(seeded, client):
    from app.core.security import hash_password
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        org = Organization(name="Tenant B", slug="tenant-b")
        db.add(org)
        db.flush()
        role = db.scalar(select(Role).where(Role.name == "admin"))
        db.add(User(org_id=org.id, email="admin@tenantb.test", full_name="Tenant B Admin",
                    password_hash=hash_password(PW), role_id=role.id))
        db.commit()
    tok = client.post(f"{V1}/auth/login", json={"email": "admin@tenantb.test", "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def a_ids(seeded):
    """Identifiers owned by the seeded tenant."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        org_a = db.scalar(select(Organization).where(Organization.slug != "tenant-b").order_by(Organization.id))
        pending = db.scalar(select(Question).where(Question.org_id == org_a.id, Question.status == "pending_review"))
        approved = db.scalar(select(Question).where(Question.org_id == org_a.id, Question.status == "approved"))
        form = db.scalar(select(TestForm).where(TestForm.status == "published"))
        return {
            "org": org_a.id,
            "pending": pending.id, "pending_code": pending.code,
            "approved": approved.id, "approved_code": approved.code,
            "form": form.id,
            "run": db.scalar(select(AssemblyRun.id).order_by(AssemblyRun.id.desc())),
            "alert": db.scalar(select(LeakAlert.id)),
            "dataset": db.scalar(select(LeakDataset.id)),
            "cal_run": db.scalar(select(CalibrationRun.id)),
            "attempt": db.scalar(select(Attempt.id)),
        }


def test_review_queue_recent_decisions_are_org_scoped(client, auth, tenant_b, a_ids, db):
    """Regression: /review/queue used to return the latest ReviewDecision rows of *every* organisation."""
    from app.api.v1 import variants  # noqa: F401  (route module under test)

    # tenant A has real decisions, with reviewer names and free-text comments
    assert db.scalar(select(func.count()).select_from(ReviewDecision)) > 0
    own = client.get(f"{V1}/review/queue", headers=auth("reviewer")).json()
    assert own["recent_decisions"], "tenant A should see its own decisions"
    other = client.get(f"{V1}/review/queue", headers=tenant_b).json()
    assert other["recent_decisions"] == []
    assert other["items"] == [] and other["total"] == 0


def test_object_routes_do_not_expose_other_tenant(client, tenant_b, a_ids):
    h = tenant_b
    pend, appr = a_ids["pending"], a_ids["approved"]
    probes = [
        ("get", f"/questions/{appr}", None),
        ("get", f"/questions/{appr}/history", None),
        ("patch", f"/questions/{appr}", {"stem": "tampered stem for tenant isolation test"}),
        ("post", f"/questions/{appr}/archive", None),
        ("post", f"/questions/{appr}/validate", None),
        ("get", f"/questions/{appr}/compare", None),
        ("post", f"/questions/{appr}/variants:generate", {"count": 1}),
        ("post", f"/review/{pend}/decision", {"decision": "reject", "comment": "cross tenant attempt"}),
        ("get", f"/exposure/items/{appr}/history", None),
        ("post", f"/exposure/items/{appr}/quarantine", {"reason": "cross tenant attempt"}),
        ("get", f"/assembly/runs/{a_ids['run']}", None),
        ("post", f"/assembly/runs/{a_ids['run']}/publish", None),
        ("get", f"/assembly/forms/{a_ids['form']}", None),
        ("get", f"/assembly/forms/{a_ids['form']}/attempts", None),
        ("post", f"/assembly/forms/{a_ids['form']}/assignments", {"candidate_codes": ["DEMO-CAND-01"]}),
        ("delete", f"/assembly/forms/{a_ids['form']}/assignments/DEMO-CAND-01", None),
        ("get", f"/leaks/alerts/{a_ids['alert']}", None),
        ("post", f"/leaks/alerts/{a_ids['alert']}/actions", {"action": "dismiss", "note": "cross tenant attempt"}),
        ("get", f"/leaks/datasets/{a_ids['dataset']}/records", None),
        ("post", f"/integrity/attempts/{a_ids['attempt']}/resolution",
         {"decision": "retain_original", "reason": "cross tenant attempt"}),
    ]
    for method, path, body in probes:
        r = getattr(client, method)(f"{V1}{path}", headers=h, **({"json": body} if body is not None else {}))
        # exactly 404: a 422 would mean the body was rejected before the ownership check ran and prove nothing
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code}: {r.text[:200]}"


def test_cross_tenant_run_ids_on_calibration_endpoints(client, tenant_b, a_ids, auth):
    cr = a_ids["cal_run"]
    for path in (f"/calibration/runs/latest?run_id={cr}", f"/calibration/items?run_id={cr}",
                 f"/calibration/families?run_id={cr}"):
        r = client.get(f"{V1}{path}", headers=tenant_b)
        body = r.text
        assert r.status_code in (200, 404), f"{path} -> {r.status_code}"
        assert "QNT-" not in body and "LOG-" not in body and "VRB-" not in body, f"{path} exposes tenant A items"


def test_list_routes_contain_no_other_tenant_data(client, tenant_b, a_ids):
    lists = ["/questions?page_size=50", "/leaks/alerts", "/leaks/datasets", "/leaks/runs", "/assembly/runs",
             "/generation-runs", "/exposure/items", "/exposure/timeline", "/calibration/runs", "/integrity/flagged-attempts?state=all",
             "/dashboard/summary", "/notifications", "/search?q=QNT", "/search?q=DEMO", "/audit?page_size=50",
             "/reports/templates", "/reports/exposure/preview", "/reports/leaks/preview", "/reports/calibration/preview"]
    for path in lists:
        r = client.get(f"{V1}{path}", headers=tenant_b)
        assert r.status_code in (200, 404, 422), f"{path} -> {r.status_code}"
        for marker in (a_ids["approved_code"], a_ids["pending_code"], "DEMO-CAND", "aptiguard.demo", "Priya Raman", "Kavya Iyer"):
            assert marker not in r.text, f"{path} exposes tenant A data ({marker})"


# ------------------------------------------------------------------ identifiers shared across tenants
HEADER = "drive,slot_code,slot_sequence,slot_start,form_code,candidate_ref,item_code,position,selected_option,response_time_ms\n"


@pytest.fixture(scope="module")
def b_item(tenant_b):
    """One question owned by tenant B, importable by item_code."""
    from app.db.session import SessionLocal
    from app.models import AnswerOption, Section, VariantFamily

    with SessionLocal() as db:
        org_b = db.scalar(select(Organization).where(Organization.slug == "tenant-b"))
        sec = db.scalar(select(Section).where(Section.code == "QUANT"))
        fam = VariantFamily(code="FAM-TB-1", org_id=org_b.id, section_id=sec.id, concept="c", skill="s")
        db.add(fam)
        db.flush()
        q = Question(code="TB-Q-1", org_id=org_b.id, section_id=sec.id, family_id=fam.id, is_source=True, skill="s",
                     stem="Tenant B only stem", explanation="x", difficulty_target="easy", status="approved",
                     normalized_hash="tb1", is_synthetic=True)
        q.options = [AnswerOption(key=k, text=f"opt {k}", is_correct=(k == "A"), position=i) for i, k in enumerate("ABCD")]
        db.add(q)
        db.commit()
        return {"org": org_b.id}


def _import(client, headers, rows):
    body = HEADER + "".join(",".join(map(str, r)) + "\n" for r in rows)
    return client.post(f"{V1}/calibration/import", headers=headers,
                       data={"preview": "false", "label": "tenant isolation test"},
                       files={"file": ("log.csv", body.encode(), "text/csv")})


def test_import_cannot_attach_to_another_tenants_form_or_slot(client, tenant_b, b_item, a_ids, db):
    """Regression: the importer looked forms up across ALL organisations and silently wrote tenant B's attempts onto
    tenant A's form (and tripped over A's globally-unique slot code)."""
    form = db.get(TestForm, a_ids["form"])
    slot_code, form_code = form.slot.code, form.code
    before = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.form_id == form.id))
    r = _import(client, tenant_b, [("Drive X", slot_code, 1, "2026-01-01T09:00:00", form_code, "TB-CAND-1", "TB-Q-1", 0, "A", 1000)])
    assert r.status_code in (409, 422), r.text
    assert "another organisation" in r.text
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Attempt).where(Attempt.form_id == form.id)) == before


def test_tenants_may_reuse_candidate_codes_and_drive_names(client, tenant_b, b_item, a_ids, db):
    """Candidate references and drive/slot numbering are tenant-local: B can use A's candidate code and drive name."""
    from app.models import Candidate, Slot

    a_slot = db.get(TestForm, a_ids["form"]).slot
    a_cand = db.scalar(select(Candidate).where(Candidate.org_id == a_ids["org"]).order_by(Candidate.id))
    r = _import(client, tenant_b, [(a_slot.drive, "TB-SLOT-1", a_slot.sequence, "2026-01-01T09:00:00", "TB-FORM-1",
                                    a_cand.code, "TB-Q-1", 0, "A", 1000)])
    assert r.status_code == 200, r.text
    db.expire_all()
    mine = db.scalars(select(Candidate).where(Candidate.org_id == b_item["org"], Candidate.code == a_cand.code)).all()
    assert len(mine) == 1 and mine[0].id != a_cand.id
    assert db.scalar(select(Slot).where(Slot.org_id == b_item["org"], Slot.drive == a_slot.drive, Slot.sequence == a_slot.sequence))
    assert db.scalar(select(func.count()).select_from(Attempt).where(Attempt.candidate_id == a_cand.id,
                                                                     Attempt.form_id == db.scalar(select(TestForm.id).where(TestForm.code == "TB-FORM-1")))) == 0


def test_assembly_does_not_reuse_another_tenants_slots(client, tenant_b, a_ids, db):
    """Regression: _ensure_slots matched slots by drive name only, so a same-named drive in another tenant would be
    attached to tenant A's slots. Exercised directly because tenant B has no approved bank to assemble from."""
    from app.models import Slot
    from app.services.assembly.service import _ensure_slots
    from datetime import datetime

    a_slot = db.get(TestForm, a_ids["form"]).slot
    b_org = db.scalar(select(Organization).where(Organization.slug == "tenant-b")).id
    slots = _ensure_slots(db, b_org, a_slot.drive, 2, datetime(2027, 1, 1, 9))
    try:
        assert all(s.org_id == b_org for s in slots)
        assert a_slot.id not in {s.id for s in slots}
        codes = [s.code for s in slots]
        assert len(set(codes)) == 2 and a_slot.code not in codes
    finally:
        db.rollback()
    assert db.get(Slot, a_slot.id).org_id == a_ids["org"]
