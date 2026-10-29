"""Real concurrent-request check against a LIVE AptiGuard API (multi-worker uvicorn), then verifies database state.

Usage:
    DATABASE_URL=<same DB the server uses> backend/.venv/bin/python scripts/concurrency_check.py --api http://127.0.0.1:8002

Steps (all through HTTP, in parallel threads): designer assembles + publishes a small drive and assigns a demo
candidate; the candidate fires 20 simultaneous starts, 30 parallel saves, then 10 simultaneous submits racing 20 saves.
Expectations: exactly one attempt, exactly one successful submit, no response row written after scoring, stored score
equals the recomputed score. Requires demo mode (uses the synthetic demo accounts). Exit code 0 = all checks passed.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8002")
    ap.add_argument("--candidate", default="DEMO-CAND-03")
    args = ap.parse_args()
    V1 = args.api.rstrip("/") + "/api/v1"
    c = httpx.Client(timeout=60)
    pw = c.get(f"{V1}/demo-status").json()["demo_password"]

    def tok(email):
        r = c.post(f"{V1}/auth/login", json={"email": email, "password": pw})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    d = tok("designer@aptiguard.demo")
    drive = f"Concurrency check {int(time.time())}"
    run = c.post(f"{V1}/assembly/runs", headers=d, json={
        "drive": drive, "n_slots": 1, "per_section": {"QUANT": 4, "LOGICAL": 4, "VERBAL": 4},
        "max_adjacent_overlap_pct": 0, "max_slot_exposures": 5, "min_slot_spacing": 0, "seed": int(time.time()) % 100000}).json()
    assert run["status"] == "succeeded", run["diagnostics"]
    form_id = run["forms"][0]["id"]
    assert c.post(f"{V1}/assembly/runs/{run['id']}/publish", headers=d).json()["published"] == 1
    everyone = ["DEMO-CAND-01", "DEMO-CAND-02", "DEMO-CAND-03"]
    assert len(c.post(f"{V1}/assembly/forms/{form_id}/assignments", headers=d, json={"candidate_codes": everyone}).json()["added"]) == 3

    email = {"DEMO-CAND-01": "candidate1", "DEMO-CAND-02": "candidate2", "DEMO-CAND-03": "candidate3"}
    h = tok(f"{email[args.candidate]}@aptiguard.demo")
    others = [tok(f"{email[x]}@aptiguard.demo") for x in everyone if x != args.candidate]
    results: dict = {"form_id": form_id, "drive": drive}

    # 20 simultaneous starts by the main candidate interleaved with 5 each from two other candidates (same form)
    jobs = [h] * 20 + others[0:1] * 5 + others[1:2] * 5
    with ThreadPoolExecutor(max_workers=30) as pool:
        starts_all = list(pool.map(lambda hh: (hh is h, c.post(f"{V1}/assessment/forms/{form_id}/attempts", headers=hh)), jobs))
    starts = [r for mine, r in starts_all if mine]
    ids = {r.json().get("attempt_id") for r in starts if r.status_code in (200, 201)}
    results["concurrent_starts"] = {"requests": len(jobs), "candidates": 3,
                                    "status_codes": sorted({r.status_code for _, r in starts_all}), "distinct_attempt_ids_main": len(ids)}
    assert len(ids) == 1 and all(r.status_code < 500 for _, r in starts_all), results
    attempt_id = ids.pop()
    refs = [i["item_ref"] for i in c.get(f"{V1}/assessment/forms/{form_id}", headers=h).json()["items"]]

    def save(i):
        return c.put(f"{V1}/assessment/attempts/{attempt_id}/responses", headers=h,
                     json={"answers": [{"item_ref": refs[i % len(refs)], "selected_key": "ABCD"[i % 4], "time_spent_ms": 1000}]})

    with ThreadPoolExecutor(max_workers=30) as pool:
        saves = list(pool.map(save, range(30)))
    results["parallel_saves"] = {"requests": 30, "status_codes": sorted({r.status_code for r in saves})}
    assert all(r.status_code == 200 for r in saves), [r.text for r in saves if r.status_code != 200][:3]

    def submit(_):
        return c.post(f"{V1}/assessment/attempts/{attempt_id}/submit", headers=h)

    with ThreadPoolExecutor(max_workers=30) as pool:
        subs = [pool.submit(submit, i) for i in range(10)] + [pool.submit(save, i) for i in range(20)]
        sub_res = [f.result() for f in subs[:10]]
        race_saves = [f.result() for f in subs[10:]]
    ok_submits = [r for r in sub_res if r.status_code == 200]
    results["concurrent_submits"] = {"requests": 10, "succeeded": len(ok_submits),
                                     "rejected_409": sum(r.status_code == 409 for r in sub_res)}
    results["saves_racing_submit"] = {"requests": 20, "status_codes": sorted({r.status_code for r in race_saves})}
    assert len(ok_submits) == 1 and all(r.status_code in (200, 409) for r in sub_res + race_saves), results
    assert all(r.status_code < 500 for r in saves + sub_res + race_saves), results

    # ---- database verification (same DATABASE_URL as the server)
    from sqlalchemy import func, select

    from app.db.session import SessionLocal
    from app.models import AnswerOption, Attempt, FormItem, Response

    with SessionLocal() as db:
        n_attempts = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.form_id == form_id, Attempt.id == attempt_id))
        a = db.get(Attempt, attempt_id)
        rows = db.scalars(select(Response).where(Response.attempt_id == attempt_id)).all()
        late = [r for r in rows if r.answered_at > a.submitted_at or r.is_correct is None]
        keys = dict(db.execute(select(AnswerOption.question_id, AnswerOption.key).where(AnswerOption.is_correct.is_(True))).all())
        fis = db.scalars(select(FormItem).where(FormItem.form_id == form_id)).all()
        by_q = {r.question_id: r for r in rows}
        recomputed = sum(1 for fi in fis if by_q.get(fi.question_id) and by_q[fi.question_id].selected_key == keys.get(fi.question_id))
        from app.models import ExposureEvent

        exposure_counts = sorted({e.candidate_count for e in db.scalars(select(ExposureEvent).where(ExposureEvent.form_id == form_id)).all()})
        attempts_total = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.form_id == form_id))
        dupes = db.execute(select(Response.question_id, func.count()).where(Response.attempt_id == attempt_id)
                           .group_by(Response.question_id).having(func.count() > 1)).all()
    results["database"] = {"engine": SessionLocal().get_bind().dialect.name, "attempts_for_form": n_attempts,
                           "exposure_candidate_counts_per_item": exposure_counts,
                           "attempt_status": a.status, "responses": len(rows), "responses_after_scoring_or_unscored": len(late),
                           "duplicate_response_rows": len(dupes), "stored_score": a.score, "recomputed_score": recomputed}
    assert attempts_total == 3 and exposure_counts == [3], results  # one attempt per candidate; no lost increments
    assert a.status == "submitted" and not late and not dupes and a.score == recomputed, results
    print(json.dumps({"ok": True, **results}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(json.dumps({"ok": False, "failure": str(e)}, default=str))
        sys.exit(1)
