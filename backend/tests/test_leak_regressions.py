"""Leak-detection lifecycle regressions: dismissal followed by new evidence, evidence that later disappears, and repeated
runs. Every test builds its own evidence (a synthetic post copied from a real bank item), runs the real `run_detection` /
`transition_alert`, and rolls the session back, so the shared throw-away database is left exactly as it was."""
import pytest
from sqlalchemy import func, select

from app.models import AuditEvent, FormItem, LeakAlert, LeakDataset, LeakRecord, Question, TestForm, User
from app.services import audit
from app.services.leakage.service import run_detection, transition_alert
from app.services.textsim import normalize

NOTE = "Reviewed the evidence in detail."


def _post(db, q: Question, ext: str, channel: str) -> LeakDataset:
    ds = LeakDataset(org_id=q.org_id, name=f"regression-{ext}", source_type="synthetic_demo", file_name="t.jsonl",
                     file_sha256="0" * 64, n_records=1, is_synthetic=True)
    db.add(ds)
    db.flush()
    text = q.stem + " " + " ".join(f"({o.key}) {o.text}" for o in q.options)
    db.add(LeakRecord(dataset_id=ds.id, external_id=ext, channel=channel, channel_type="messaging", posted_at=None,
                      text=text, normalized_text=normalize(text)))
    db.flush()
    return ds


def _count(db, action: str) -> int:
    return db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)) or 0


def _alerts(db, q) -> list[LeakAlert]:
    return db.scalars(select(LeakAlert).where(LeakAlert.question_id == q.id)).all()


class Scene:
    def __init__(self, db):
        self.db = db
        self.reviewer = db.scalar(select(User).where(User.email == "reviewer@aptiguard.demo"))
        self.q = db.scalars(
            select(Question).join(FormItem, FormItem.question_id == Question.id).join(TestForm, TestForm.id == FormItem.form_id)
            .where(TestForm.status == "published", Question.status == "approved", Question.leak_status == "none",
                   Question.id.not_in(select(LeakAlert.question_id)))
            .order_by(Question.id)).first()
        assert self.q is not None, "seed should contain an unalerted approved item that is part of a published form"
        self.form = db.scalars(select(TestForm).join(FormItem, FormItem.form_id == TestForm.id)
                               .where(FormItem.question_id == self.q.id, TestForm.status == "published")).first()
        self.fid = self.form.id

    def detect(self):
        run = run_detection(self.db, self.q.org_id, self.reviewer, replay=False)
        self.db.flush()
        self.db.refresh(self.q)
        self.db.refresh(self.form)
        return run

    def alert(self) -> LeakAlert:
        found = _alerts(self.db, self.q)
        assert len(found) == 1, f"expected exactly one alert for the item, got {len(found)}"
        return found[0]

    def dismiss(self):
        transition_alert(self.db, self.alert(), "dismiss", self.reviewer, NOTE)
        self.db.flush()
        self.db.refresh(self.q)
        self.db.refresh(self.form)


@pytest.fixture()
def scene(db):
    s = Scene(db)
    yield s
    db.rollback()


# ------------------------------------------------------------------ baseline: detection and dismissal behave
def test_text_evidence_creates_one_alert_suspects_the_item_and_flags_its_form(scene, db):
    _post(db, scene.q, "post-1", "t.me/first")
    scene.detect()
    a = scene.alert()
    assert a.severity in ("high", "critical") and a.evidence_class == "confirmed_text_match" and a.status == "open"
    assert scene.q.leak_status == "suspected"
    assert scene.form.status == "needs_review"  # new starts on the form are blocked while the item is suspected


def test_dismissing_the_alert_clears_the_item_and_restores_the_form(scene, db):
    _post(db, scene.q, "post-1", "t.me/first")
    scene.detect()
    scene.dismiss()
    assert scene.alert().status == "dismissed" and scene.q.leak_status == "cleared"
    assert scene.form.status == "published"


# ------------------------------------------------------------------ issue 1: dismissed alert, then stronger/new evidence
@pytest.mark.xfail(strict=True, reason="SUSPECTED DEFECT (service.py: `q.leak_status in ('none',)`): once an alert is "
                                       "dismissed the item is 'cleared' and later high/critical evidence neither re-suspects it, "
                                       "re-flags its forms nor reopens the dismissed alert")
def test_new_high_severity_evidence_after_dismissal_is_not_ignored(scene, db):
    _post(db, scene.q, "post-1", "t.me/first")
    scene.detect()
    scene.dismiss()
    assert scene.q.leak_status == "cleared" and scene.form.status == "published"
    _post(db, scene.q, "post-2", "t.me/second-channel")  # a new post from a different channel appears later
    scene.detect()
    a = scene.alert()
    assert a.severity in ("high", "critical")  # the evidence itself is recorded on the alert ...
    assert scene.q.leak_status == "suspected"  # ... so the item should be suspected again
    assert scene.form.status == "needs_review"  # ... and its form held back
    assert a.status != "dismissed"  # ... and a human should be asked to decide again


def test_dismissed_alert_is_updated_in_place_when_evidence_is_rerun(scene, db):
    """What does happen today (facts, not endorsement): same alert row, no duplicate, new run id recorded."""
    _post(db, scene.q, "post-1", "t.me/first")
    first = scene.detect()
    scene.dismiss()
    second = scene.detect()
    a = scene.alert()
    assert a.run_id == second.id != first.id and a.status == "dismissed"
    assert scene.q.leak_status == "cleared"  # current behaviour: the earlier human decision stands


# ------------------------------------------------------------------ issue 2: evidence disappears after an alert exists
def test_alert_is_retained_when_a_later_run_finds_no_evidence(scene, db):
    ds = _post(db, scene.q, "post-1", "t.me/first")
    scene.detect()
    before = scene.alert()
    alert_id, severity, score = before.id, before.severity, before.score
    db.query(LeakRecord).filter(LeakRecord.dataset_id == ds.id).delete()
    db.query(LeakDataset).filter(LeakDataset.id == ds.id).delete()
    db.flush()
    run = scene.detect()
    assert run.summary["alerts_created"] == 0
    after = scene.alert()
    # nothing is silently cleared: only a reviewer may dismiss a suspicion
    assert after.id == alert_id and after.status == "open" and after.severity == severity and after.score == score
    assert scene.q.leak_status == "suspected" and scene.form.status == "needs_review"
    # (the alert keeps pointing at the run that produced its evidence; there is no "stale" marker in the design)
    assert after.run_id != run.id


# ------------------------------------------------------------------ repeated runs: no duplicates, consistent audit trail
def test_repeated_runs_do_not_duplicate_alerts_or_audit_noise_and_the_chain_stays_valid(scene, db):
    _post(db, scene.q, "post-1", "t.me/first")
    runs0, flagged0 = _count(db, "leaks.detection_run"), _count(db, "assembly.forms_flagged")
    scene.detect()
    assert _count(db, "assembly.forms_flagged") == flagged0 + 1  # flagged once, when the item became suspected
    first_alert_id = scene.alert().id
    for n in (2, 3):
        run = scene.detect()
        assert run.summary["alerts_created"] == 0 and run.summary["alerts_updated"] >= 1
        assert scene.alert().id == first_alert_id
        assert _count(db, "leaks.detection_run") == runs0 + n  # exactly one audit event per run
        assert _count(db, "assembly.forms_flagged") == flagged0 + 1  # re-runs do not re-flag the same form
    assert audit.verify_chain(db)["ok"] is True
