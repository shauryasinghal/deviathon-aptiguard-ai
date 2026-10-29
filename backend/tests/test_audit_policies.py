"""Audit-chain failure modes and the policy fields that are stored but not enforced."""
from sqlalchemy import text

from app.services.audit import GENESIS, verify_chain

V1 = "/api/v1"


def test_broken_link_and_tampered_head_are_detected(db):
    row = db.execute(text("SELECT id, prev_hash FROM audit_events ORDER BY id LIMIT 1 OFFSET 7")).one()
    db.execute(text("UPDATE audit_events SET prev_hash = :p WHERE id = :i"), {"p": "f" * 64, "i": row.id})
    res = verify_chain(db)
    db.rollback()
    assert not res["ok"] and res["broken_at_id"] == row.id and res["reason"] == "prev_hash mismatch"

    first = db.execute(text("SELECT id FROM audit_events ORDER BY id LIMIT 1")).one()
    db.execute(text("UPDATE audit_events SET prev_hash = :p WHERE id = :i"), {"p": "1" * 64, "i": first.id})  # wrong genesis
    res = verify_chain(db)
    db.rollback()
    assert not res["ok"] and res["broken_at_id"] == first.id

    last = db.execute(text("SELECT id FROM audit_events ORDER BY id DESC LIMIT 1")).one()
    db.execute(text("UPDATE audit_events SET hash = :h WHERE id = :i"), {"h": "0" * 64, "i": last.id})  # forged head
    res = verify_chain(db)
    db.rollback()
    assert not res["ok"] and res["broken_at_id"] == last.id and res["reason"] == "content hash mismatch"
    assert verify_chain(db)["ok"]


def test_untracked_insert_without_hash_is_reported(db):
    db.execute(text("INSERT INTO audit_events (org_id, actor_label, action, entity_type, summary, created_at) "
                    "VALUES (1, 'x', 'forged', 'x', 'inserted behind the application', CURRENT_TIMESTAMP)"))
    res = verify_chain(db)
    db.rollback()
    assert not res["ok"] and res["reason"] == "event without hash"


def test_tail_truncation_needs_an_external_anchor(db):
    """Documented limitation: deleting the NEWEST events leaves a valid chain. An externally stored head catches it."""
    base = verify_chain(db)
    assert base["ok"]
    anchor = {"anchor_count": base["checked"], "anchor_head": base["head"]}
    assert verify_chain(db, **anchor)["ok"] and verify_chain(db, **anchor)["anchor_verified"]
    db.execute(text("DELETE FROM audit_events WHERE id = (SELECT MAX(id) FROM audit_events)"))
    assert verify_chain(db)["ok"], "the chain alone cannot see the removal of its last event"
    res = verify_chain(db, **anchor)
    db.rollback()
    assert not res["ok"] and "shorter than the anchor" in res["reason"]


def test_rewritten_history_is_caught_by_the_anchor(db):
    """An administrator who recomputes the chain after editing still disagrees with an externally recorded head."""
    from app.models import AuditEvent
    from app.services.audit import canonical, event_hash

    base = verify_chain(db)
    anchor = {"anchor_count": base["checked"], "anchor_head": base["head"]}
    prev = GENESIS
    for i, ev in enumerate(db.query(AuditEvent).order_by(AuditEvent.id).all()):
        if i == 0:
            ev.summary = ev.summary + " (rewritten)"
        ev.prev_hash = prev
        ev.hash = event_hash(prev, canonical(ev.org_id, ev.actor_id, ev.actor_label, ev.action, ev.entity_type,
                                             ev.entity_id, ev.summary, ev.details, ev.created_at))
        prev = ev.hash
    db.flush()
    assert verify_chain(db)["ok"], "a fully recomputed chain is internally consistent (this is the documented weakness)"
    res = verify_chain(db, **anchor)
    db.rollback()
    assert not res["ok"] and res["reason"].startswith("anchor mismatch")


def test_verify_endpoint_anchor_parameters(client, auth):
    h = auth("admin")
    ok = client.get(f"{V1}/audit/verify", headers=h).json()
    assert ok["ok"] and not ok["anchor_verified"]
    anchored = client.get(f"{V1}/audit/verify?anchor_count={ok['checked']}&anchor_head={ok['head']}", headers=h).json()
    assert anchored["ok"] and anchored["anchor_verified"]
    assert client.get(f"{V1}/audit/verify?anchor_count=3", headers=h).status_code == 422
    assert client.get(f"{V1}/audit/verify?anchor_count=3&anchor_head=zz", headers=h).status_code == 422
    wrong = client.get(f"{V1}/audit/verify?anchor_count=3&anchor_head={'a' * 64}", headers=h).json()
    assert not wrong["ok"] and wrong["reason"].startswith("anchor mismatch")


def test_unenforced_policy_fields_are_flagged_and_immutable(client, auth):
    h = auth("admin")
    s = client.get(f"{V1}/settings", headers=h).json()
    assert set(s["inactive_fields"]["retention"]) == {"response_retention_days", "audit_retention_days", "pseudonymize_candidates"}
    assert "verbal_requires_second_look" in s["inactive_fields"]["review"]
    for key, field, val in (("retention", "response_retention_days", 30), ("retention", "audit_retention_days", 30),
                            ("retention", "pseudonymize_candidates", False), ("review", "verbal_requires_second_look", False)):
        r = client.put(f"{V1}/settings/policies/{key}", json={"values": {field: val}}, headers=h)
        assert r.status_code == 422 and "not enforced" in r.text
    # enforced fields stay editable
    assert client.put(f"{V1}/settings/policies/review", json={"values": {"require_independent_reviewer": True}}, headers=h).status_code == 200
