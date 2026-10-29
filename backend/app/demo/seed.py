"""Deterministic synthetic demo data (seed 107). EVERYTHING produced here is SYNTHETIC and labelled as such.

Pipeline:  bank (templates) → historical drive response log (CSV) → import pipeline → calibration
           → leak post dataset (JSONL) → leak import pipeline → leak detection → upcoming drive assembly.
The injected leak scenario is documented in data/synthetic/leak_ground_truth.json, which the detector never reads.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_DIR
from app.core.security import PERMISSIONS, ROLES, hash_password
from app.db.base import Base
from app.models import (
    Candidate,
    GenerationRun,
    Organization,
    Permission,
    Question,
    ReviewDecision,
    Role,
    Section,
    User,
    VariantFamily,
)
from app.services import audit
from app.services.assembly.service import publish_run, run_assembly
from app.services.calibration.service import run_calibration
from app.services.generation.registry import TEMPLATES, generate
from app.services.importers import import_response_log
from app.services.leakage.importer import import_dataset
from app.services.leakage.service import run_detection
from app.services.questions import SECTION_PREFIX, add_revision, create_from_item, persist_checks
from app.services.textsim import char_cosine_matrix, item_fulltext, normalize
from app.services.validation.validator import _core, answer_checks, overall, structural_checks
from app.services.generation.base import Check

SEED = 107
DEMO_PASSWORD = "AptiGuard-Demo-2026"  # local demo accounts only — documented in README
OUT_DIR = PROJECT_DIR / "data" / "synthetic"
HIST_DRIVE = "Campus Drive 2026-Q3 (synthetic)"
NEXT_DRIVE = "Campus Drive 2026-Q4"
CANDIDATES_PER_SLOT = 150
SLOT_MEAN_THETA = [0.0, 0.05, -0.05, 0.30, 0.0, 0.05, -0.10, 0.05, 0.35, 0.10]  # slots 4 and 9 are stronger cohorts
GUESS = 0.15

USERS = [
    ("admin@aptiguard.demo", "Priya Raman", "admin"),
    ("designer@aptiguard.demo", "Arvind Menon", "designer"),
    ("reviewer@aptiguard.demo", "Dr. Kavya Iyer", "reviewer"),
    ("reviewer2@aptiguard.demo", "Rahul Desai", "reviewer"),
    ("analyst@aptiguard.demo", "Sana Qureshi", "analyst"),
    ("candidate1@aptiguard.demo", "Demo Candidate One", "candidate"),
    ("candidate2@aptiguard.demo", "Demo Candidate Two", "candidate"),
    ("candidate3@aptiguard.demo", "Demo Candidate Three", "candidate"),
]
SECTIONS = [("QUANT", "Quantitative Reasoning", "Arithmetic, rates, interest, ratios and probability"),
            ("LOGICAL", "Logical Reasoning", "Series, syllogisms, arrangements, coding and directions"),
            ("VERBAL", "Verbal Reasoning", "Vocabulary, analogies, grammar and reading inference")]

# core (reused-in-every-slot) items, chosen by (template, band); role documents the injected scenario
CORE = [
    ("QT-INT", "easy", "clean"), ("QT-PCT", "medium", "L1_paraphrase"), ("QT-SDT", "medium", "L1_verbatim"),
    ("QT-WORK", "hard", "clean"),
    ("LG-SERIES", "easy", "L1_verbatim"), ("LG-CODE", "medium", "L1_verbatim"), ("LG-SYLL", "medium", "clean"),
    ("LG-ORDER", "hard", "L2_statistical_only"),
    ("VB-SYN", "easy", "L1_ocr_noise"), ("VB-ANALOGY", "medium", "L1_verbatim"), ("VB-SVA", "medium", "clean"),
    ("VB-INFER", "hard", "clean"),
]
L1_POSTED = datetime(2026, 9, 14, 13, 10)   # after slot 2, before slot 3 (UTC)
L1_REACH = {3: 0.30, 4: 0.45, 5: 0.55, 6: 0.60, 7: 0.60, 8: 0.60, 9: 0.60, 10: 0.60}
L2_REACH = {6: 0.35, 7: 0.40, 8: 0.45, 9: 0.45, 10: 0.45}
L3_POSTED = datetime(2026, 9, 17, 12, 30)  # after slot 8; its items never reappear → text-only evidence


def reset_database(db: Session) -> None:
    """Delete all rows (schema/migrations untouched). Breaks the two intentional FK cycles first."""
    from sqlalchemy import text

    tables = [t.name for t in Base.metadata.sorted_tables]
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    else:
        db.execute(text("UPDATE questions SET generation_run_id = NULL"))
        db.execute(text("UPDATE variant_families SET source_question_id = NULL"))
        db.execute(text("DELETE FROM generation_runs"))
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
    db.commit()


def _slot_start(seq: int) -> datetime:
    day, half = divmod(seq - 1, 2)
    return datetime(2026, 9, 14, 4, 0) + timedelta(days=day, hours=5 * half)


def seed_identity(db: Session) -> dict:
    org = Organization(name="Integraminds (demo tenant)", slug="integraminds-demo")
    db.add(org)
    db.flush()
    perms = {code: Permission(code=code, description=d) for code, d in PERMISSIONS.items()}
    db.add_all(perms.values())
    roles = {}
    for name, spec in ROLES.items():
        r = Role(name=name, label=spec["label"], description=spec["description"],
                 permissions=[perms[p] for p in spec["permissions"]])
        db.add(r)
        roles[name] = r
    db.flush()
    pw = hash_password(DEMO_PASSWORD)
    users = {}
    for email, name, role in USERS:
        u = User(org_id=org.id, email=email, full_name=name, password_hash=pw, role_id=roles[role].id)
        db.add(u)
        users[email.split("@")[0]] = u
    db.flush()
    for i, key in enumerate(["candidate1", "candidate2", "candidate3"], 1):
        db.add(Candidate(org_id=org.id, code=f"DEMO-CAND-{i:02d}", display_name=users[key].full_name,
                         user_id=users[key].id, is_synthetic=True))
    for code, name, desc in SECTIONS:
        db.add(Section(code=code, name=name, description=desc))
    db.flush()
    return {"org": org, "users": users}


def seed_bank(db: Session, org: Organization, users: dict, rng: random.Random) -> dict:
    designer, reviewer, reviewer2 = users["designer"], users["reviewer"], users["reviewer2"]
    seen_params: set[str] = set()
    families: dict[tuple[str, str, int], dict] = {}
    approved_base = datetime(2026, 8, 3, 6, 0)
    k_item = 0

    def fresh(tid: str, band: str):
        for _ in range(600):
            s = rng.randrange(1, 2**31)
            item = generate(tid, band, s)
            key = tid + json.dumps(_core(item.params), sort_keys=True, default=str)
            if key not in seen_params:
                seen_params.add(key)
                item.params = {**item.params, "_seed": s}
                return item
        raise RuntimeError(f"could not create a fresh {tid}/{band} item")

    for tid, tpl in TEMPLATES.items():
        prefix = SECTION_PREFIX[tpl.section]
        short = tid.split("-")[1]
        for band in ("easy", "medium", "hard"):
            for k in range(1, 4):
                fam_code = f"FAM-{prefix}-{short}-{band[0].upper()}{k}"
                sec = db.scalar(select(Section).where(Section.code == tpl.section))
                fam = VariantFamily(code=fam_code, org_id=org.id, section_id=sec.id, concept=tpl.concept, skill=tpl.skill,
                                    template_id=tid)
                db.add(fam)
                db.flush()
                members = []
                for v in range(4):
                    item = fresh(tid, band)
                    code = f"{prefix}-{short}-{band[0].upper()}{k}-" + ("S" if v == 0 else f"V{v:02d}")
                    q = create_from_item(db, item, org_id=org.id, family=fam, code=code,
                                         parent=members[0] if v else None, method="template", status="approved",
                                         user=designer, is_source=(v == 0))
                    k_item += 1
                    q.created_at = approved_base - timedelta(days=10) + timedelta(minutes=7 * k_item)
                    q.approved_by = (reviewer if k_item % 3 else reviewer2).id
                    q.approved_at = approved_base + timedelta(hours=3 * (k_item % 200))
                    checks = structural_checks(item) + answer_checks(item, "template")
                    q.validation_status = overall(checks)
                    persist_checks(db, q, checks)
                    add_revision(db, q, "created", designer, "Seeded synthetic item (template generator)")
                    db.add(ReviewDecision(question_id=q.id, reviewer_id=q.approved_by, decision="approve",
                                          comment="Verified key and distractors (synthetic demo approval)",
                                          question_version=1))
                    members.append(q)
                fam.source_question_id = members[0].id
                families[(tid, band, k)] = {"family": fam, "members": members}
    db.flush()

    # batch near-duplicate screen over the approved bank (single TF-IDF fit)
    allq = [m for f in families.values() for m in f["members"]]
    texts = [normalize(item_fulltext(q.stem, [o.text for o in q.options])) for q in allq]
    sims = char_cosine_matrix(texts, texts)
    np.fill_diagonal(sims, 0)
    for i, q in enumerate(allq):
        j = int(sims[i].argmax())
        st = "fail" if sims[i, j] >= 0.93 else ("warn" if sims[i, j] >= 0.86 else "pass")
        from app.models import ValidationResult
        db.add(ValidationResult(question_id=q.id, check="duplicate_near", status=st,
                                severity="critical" if st == "fail" else ("warning" if st == "warn" else "info"),
                                message=f"Nearest item {allq[j].code} at similarity {sims[i, j]:.2f} (batch screen)",
                                details={"nearest": allq[j].code, "similarity": round(float(sims[i, j]), 3)}))
    return families


def seed_review_queue(db: Session, org: Organization, users: dict, families: dict, rng: random.Random) -> list:
    """Pending variants produced by the real generation engine, plus deliberate failure examples."""
    from app.services.generation.engine import generate_variants

    designer = users["designer"]
    created = []
    picks = [(tid, band, 2) for tid in TEMPLATES for band in ("medium",)][:16]
    for i, key in enumerate(picks):
        src = families[key]["members"][0]
        run, qs, _ = generate_variants(db, src, 1, None, designer, seed=SEED * 100 + i, method="template")
        when = datetime(2026, 10, 20, 5, 0) + timedelta(hours=7 * i)
        run.created_at = when
        for q in qs:
            q.created_at = when
            created.append(q)
    # deliberately invalid answer key: flip the key of a fresh variant → validator must auto-reject
    src = families[("QT-RATIO", "easy", 3)]["members"][0]
    run, qs, _ = generate_variants(db, src, 1, None, designer, seed=SEED * 1000 + 1, method="template")
    bad = qs[0]
    wrong = next(o for o in bad.options if not o.is_correct)
    for o in bad.options:
        o.is_correct = o.key == wrong.key
    from app.services.questions import revalidate
    status, _ = revalidate(db, bad)
    bad.status = "rejected" if status == "failed" else bad.status
    bad.status_reason = "Auto-rejected by validator: recomputed answer disagrees with the key (seeded failure example)"
    bad.version += 1
    add_revision(db, bad, "edited", designer, "Seeded failure example: answer key deliberately corrupted")
    # near-duplicate of an approved item → validator must reject
    approved = families[("QT-PCT", "easy", 1)]["members"][1]
    from app.services.generation.base import GeneratedItem
    from app.services.questions import bank_entries, next_variant_code
    from app.services.validation.validator import validate
    dup_item = GeneratedItem("QUANT", approved.template_id, approved.family.concept, approved.skill, approved.difficulty_target,
                             approved.stem.replace("The price of", "The cost of"),
                             [{"key": o.key, "text": o.text, "is_correct": o.is_correct, "rationale": o.rationale} for o in approved.options],
                             approved.explanation, {**(approved.params or {}), "_seed": -1, "manual_copy": True})
    st, checks = validate(dup_item, bank_entries(db, org.id), "template")
    dq = create_from_item(db, dup_item, org_id=org.id, family=approved.family, code=next_variant_code(db, approved.family),
                          parent=db.get(Question, approved.parent_id), method="human_authored", status="rejected", user=designer)
    dq.validation_status = st
    dq.status_reason = "Auto-rejected by validator: near-duplicate of " + approved.code
    persist_checks(db, dq, checks)
    add_revision(db, dq, "created", designer, "Seeded failure example: hand-edited copy of an approved item")
    # one pending item edited by a reviewer (revision history v2)
    if created:
        ed = created[0]
        ed.stem = ed.stem.replace("  ", " ") + ""
        ed.explanation = ed.explanation + " (Reviewer clarified the working.)"
        ed.version += 1
        add_revision(db, ed, "edited", users["reviewer"], "Clarified explanation wording")
    return created


def build_history(db: Session, families: dict, rng: random.Random) -> tuple[pd.DataFrame, dict]:
    np_rng = np.random.default_rng(SEED)
    core = []
    for tid, band, role in CORE:
        q = families[(tid, band, 1)]["members"][0]
        core.append((q, role))
    core_fams = {q.family_id for q, _ in core}
    # true difficulties
    b_true: dict[int, float] = {}
    for f in families.values():
        src = f["members"][0]
        base = src.difficulty_target_b + np_rng.normal(0, 0.3)
        for i, m in enumerate(f["members"]):
            b_true[m.id] = base if i == 0 else base + np_rng.normal(0, 0.12)
    # slot-specific allocation: 2 items per (section, band) per slot, spread families, skip core families
    queues: dict[tuple[str, str], list] = {}
    for (tid, band, k), f in sorted(families.items()):
        if f["family"].id in core_fams:
            continue
        sec = TEMPLATES[tid].section
        queues.setdefault((sec, band), []).extend(f["members"])
    for key in queues:
        rng.shuffle(queues[key])
    slot_items: dict[int, list] = {}
    prev_fams: set[int] = set()
    for seq in range(1, 11):
        chosen, fams = [], set()
        for sec in ("QUANT", "LOGICAL", "VERBAL"):
            for band in ("easy", "medium", "hard"):
                need = 2
                qd = queues[(sec, band)]
                for q in list(qd):
                    if need == 0:
                        break
                    if q.family_id in fams or q.family_id in prev_fams:
                        continue
                    chosen.append(q); fams.add(q.family_id); qd.remove(q); need -= 1
        slot_items[seq] = chosen
        prev_fams = fams
    # drifted (non-parallel) variants among administered variants whose source was also administered
    administered = {q.id: s for s, qs in slot_items.items() for q in qs}
    drift_candidates = [q for qs in slot_items.values() for q in qs if q.parent_id and q.parent_id in administered]
    rng.shuffle(drift_candidates)
    drifted = {}
    for q, off in zip(drift_candidates[:4], [0.9, 0.95, -0.85, -0.9]):
        b_true[q.id] += off
        drifted[q.code] = off
    l1 = [q for q, r in core if r.startswith("L1")]
    l2 = [q for q, r in core if r.startswith("L2")]
    l3 = [next(q for q in slot_items[8] if q.section.code == "QUANT" and q.difficulty_target == "medium"),
          next(q for q in slot_items[8] if q.section.code == "LOGICAL" and q.difficulty_target == "medium")]
    keys = {q.id: next(o.key for o in q.options if o.is_correct) for f in families.values() for q in f["members"]}
    wrong_keys = {q.id: [o.key for o in q.options if not o.is_correct] for f in families.values() for q in f["members"]}
    rt_base = {"QUANT": 70000, "LOGICAL": 55000, "VERBAL": 40000}
    rows = []
    cand_n = 0
    for seq in range(1, 11):
        form_code = f"Q3S-S{seq:02d}-F1"
        items = [q for q, _ in core] + slot_items[seq]
        # deterministic per-slot item order: section, then code
        order = {"QUANT": 0, "LOGICAL": 1, "VERBAL": 2}
        items.sort(key=lambda q: (order[q.section.code], q.code))
        for c in range(CANDIDATES_PER_SLOT):
            cand_n += 1
            theta = np_rng.normal(SLOT_MEAN_THETA[seq - 1], 1.0)
            speed = math.exp(np_rng.normal(0, 0.25))
            saw_l1 = np_rng.random() < L1_REACH.get(seq, 0)
            saw_l2 = np_rng.random() < L2_REACH.get(seq, 0)
            for pos, q in enumerate(items):
                leaked = (saw_l1 and q in l1) or (saw_l2 and q in l2)
                p = GUESS + (1 - GUESS) / (1 + math.exp(-(theta - b_true[q.id])))
                if leaked and np_rng.random() < 0.9:
                    p = 0.98
                omit_p = 0.02 + (0.04 if q.difficulty_target == "hard" else 0) + (0.05 if pos >= 27 else 0)
                rt = rt_base[q.section.code] * math.exp(0.15 * b_true[q.id]) * speed * math.exp(np_rng.normal(0, 0.35))
                if leaked:
                    rt *= 0.35
                if np_rng.random() < omit_p and not leaked:
                    sel = ""
                else:
                    sel = keys[q.id] if np_rng.random() < p else wrong_keys[q.id][int(np_rng.integers(0, 3))]
                rows.append((HIST_DRIVE, f"Q3S-S{seq:02d}", seq, _slot_start(seq).isoformat(), form_code,
                             f"C-Q3-{cand_n:05d}", q.code, pos, sel, int(sel == keys[q.id]) if sel else "", int(rt),
                             (_slot_start(seq) + timedelta(minutes=40)).isoformat()))
    df = pd.DataFrame(rows, columns=["drive", "slot_code", "slot_sequence", "slot_start", "form_code", "candidate_ref",
                                     "item_code", "position", "selected_option", "is_correct", "response_time_ms",
                                     "submitted_at"])
    truth = {"core": [(q.code, r) for q, r in core], "l1": [q.code for q in l1], "l2": [q.code for q in l2],
             "l3": [q.code for q in l3], "drifted_variants": drifted}
    return df, truth


def _ocr_noise(text: str, rng: random.Random) -> str:
    swaps = {"o": "0", "l": "1", "e": "c", "a": "o"}
    out = []
    for ch in text:
        if ch in swaps and rng.random() < 0.06:
            out.append(swaps[ch])
        else:
            out.append(ch)
    return "".join(out)


def _paraphrase_pct(q: Question) -> str:
    p = q.params
    return (f"{p['thing']} was ₹{p['old']}, now it costs ₹{p['new']}. by what percent did the price change?? "
            f"options {', '.join(o.text for o in q.options)}")


def build_leak_posts(db: Session, truth: dict, rng: random.Random) -> list[dict]:
    posts = []
    by_code = {q.code: q for q in db.scalars(select(Question)).all()}
    pid = 0

    def add(text, channel, ctype, when, label):
        nonlocal pid
        pid += 1
        posts.append({"post_id": f"P-{pid:04d}", "channel": channel, "channel_type": ctype,
                      "posted_at": when.isoformat() + "Z", "text": text, "_label": label})

    core_roles = dict(truth["core"])
    for i, code in enumerate(truth["l1"]):
        q = by_code[code]
        opts = "  ".join(f"{o.key}) {o.text}" for o in q.options)
        key = next(o.key for o in q.options if o.is_correct)
        role = core_roles[code]
        when = L1_POSTED + timedelta(minutes=9 * i)
        if role == "L1_paraphrase":
            add(f"slot 2 q quant 👇 {_paraphrase_pct(q)} ans {key}", "t.me/placement_leaks_2026", "telegram_export", when, f"leak:{code}")
        elif role == "L1_ocr_noise":
            add(f"[screenshot text] {_ocr_noise(q.stem, rng)} {opts}", "t.me/aptitude_answers_hub", "telegram_export", when, f"leak:{code}")
        else:
            add(f"Today's slot 2 question 🔥 {q.stem}\n{opts}\nAnswer: {key} — share with friends in later slots",
                "t.me/placement_leaks_2026", "telegram_export", when, f"leak:{code}")
    for i, code in enumerate(truth["l3"]):
        q = by_code[code]
        add(f"[video transcript 03:1{i}] okay so the next question they asked was {q.stem.lower()} and the trick here is",
            "youtube.com/@slotsolutions (transcript)", "video_transcript", L3_POSTED + timedelta(minutes=20 * i), f"leak:{code}")
    # family-level decoys: same templates, freshly generated numbers/names (not in the bank)
    for j, (tid, band) in enumerate([("QT-RATIO", "easy"), ("LG-DIR", "medium"), ("QT-INT", "medium")]):
        item = generate(tid, band, 990000 + j)
        add(f"practice question from a prep book: {item.stem}", "forum.prepcommunity.example", "forum_post",
            datetime(2026, 9, 12 + j, 8, 0), f"decoy_family:{tid}")
    chatter = [
        "Does anyone know the reporting time for slot 5?", "Best books for quantitative aptitude? RS Aggarwal or Arun Sharma?",
        "Is there negative marking in the Integraminds round?", "My test link isn't working, who do I contact?",
        "What is 15% of 240? quick mental math trick thread", "How many questions are in the logical section?",
        "Tips for reading comprehension under time pressure", "Group discussion topics for next week",
        "Anyone from slot 7 here? How was the difficulty?", "Need referral for the drive, DM me",
        "Speed maths: squaring numbers ending in 5", "Profit and loss formulas cheat sheet (generic, not from the test)",
        "Can we use a calculator in the aptitude round?", "Results expected on which date?",
        "Syllogism shortcut: draw Venn diagrams always", "Interview prep resources for freshers",
        "Is the test proctored with webcam?", "Coding round after aptitude or same day?",
        "How to improve vocabulary for verbal section", "Mock test link for practice (unofficial)",
        "Admit card download issue", "Which slot is easiest? lol", "Time management: 40 minutes for 30 questions",
        "Any dress code for the in-person round?", "Thank you all, cleared the round!",
    ]
    for i, t in enumerate(chatter):
        add(t, rng.choice(["t.me/placement_leaks_2026", "t.me/aptitude_answers_hub", "forum.prepcommunity.example"]),
            rng.choice(["telegram_export", "forum_post"]), datetime(2026, 9, 13, 6, 0) + timedelta(hours=7 * i), "unrelated")
    # an exact duplicate record (import pipeline must de-duplicate)
    posts.append({**posts[0], "post_id": "P-DUP-1", "_label": "duplicate_of:" + posts[0]["post_id"]})
    return posts


def write_outputs(df: pd.DataFrame, posts: list[dict], truth: dict, db: Session) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    resp_path = OUT_DIR / "response_logs.csv"
    df.to_csv(resp_path, index=False)
    leak_path = OUT_DIR / "leak_simulation_posts.jsonl"
    with leak_path.open("w") as fh:
        for p in posts:
            fh.write(json.dumps({k: v for k, v in p.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")
    bank_path = OUT_DIR / "item_bank.jsonl"
    with bank_path.open("w") as fh:
        for q in db.scalars(select(Question).order_by(Question.id)).all():
            fh.write(json.dumps({"item_code": q.code, "family": q.family.code, "section": q.section.code,
                                 "skill": q.skill, "difficulty_target": q.difficulty_target, "status": q.status,
                                 "stem": q.stem, "options": {o.key: o.text for o in q.options},
                                 "correct_option": next((o.key for o in q.options if o.is_correct), None),
                                 "template_id": q.template_id, "synthetic": True}, ensure_ascii=False) + "\n")
    gt = {
        "WARNING": "SYNTHETIC ground truth for the deterministic demo (seed 107). Not real-world data. "
                   "The detection pipeline never reads this file; it is used only by scripts/run_validation.py.",
        "historical_drive": HIST_DRIVE, "slots": 10, "candidates_per_slot": CANDIDATES_PER_SLOT,
        "slot_mean_ability": SLOT_MEAN_THETA,
        "design": "12 core items reused in all 10 slots (legacy practice) + 18 slot-specific items per slot",
        "injections": {
            "L1_text_and_performance": {
                "items": truth["l1"], "posted_at_utc": L1_POSTED.isoformat(),
                "mechanism": "Posted to synthetic Telegram exports after slot 2. Candidates in slot s>=3 'saw' the leak with "
                             f"probability {L1_REACH}; those candidates answer the leaked item correctly with p=0.9 and "
                             "70% faster.",
                "variants": "4 verbatim, 1 paraphrased (same numbers), 1 with OCR-style character noise",
            },
            "L2_statistical_only": {
                "items": truth["l2"],
                "mechanism": f"Circulated via a channel NOT in the dataset; reach by slot {L2_REACH}. No text exists.",
            },
            "L3_text_only": {
                "items": truth["l3"], "posted_at_utc": L3_POSTED.isoformat(),
                "mechanism": "Video transcript posted after slot 8; items never re-administered, so no performance evidence.",
            },
            "family_level_decoys": "3 forum posts generated from bank templates with new numbers (concept-level exposure only)",
            "unrelated_posts": 25, "duplicate_records": 1,
            "ability_confounders": "Slots 4 and 9 have stronger cohorts (+0.30/+0.35 logits); ability-adjusted tests must not flag them.",
        },
        "calibration_truth": {"drifted_variants_logit_offset": truth["drifted_variants"],
                              "note": "These administered variants were simulated as NOT parallel to their source."},
        "expected_alerts": {"critical_or_high": sorted(set(truth["l1"]) | set(truth["l3"])),
                            "statistical": truth["l2"]},
    }
    (OUT_DIR / "leak_ground_truth.json").write_text(json.dumps(gt, indent=2))
    manifest = {"seed": SEED, "generated_by": "backend/app/demo/seed.py", "synthetic": True,
                "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (resp_path, leak_path, bank_path)}}
    (OUT_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def seed_demo(db: Session, with_next_drive: bool = True) -> dict:
    rng = random.Random(SEED)
    reset_database(db)
    ident = seed_identity(db)
    org, users = ident["org"], ident["users"]
    families = seed_bank(db, org, users, rng)
    db.commit()
    pending = seed_review_queue(db, org, users, families, rng)
    db.commit()
    df, truth = build_history(db, families, rng)
    report = import_response_log(db, org.id, users["analyst"], df, "synthetic response log (seed 107)", is_synthetic=True)
    db.commit()
    run_calibration(db, org.id, users["analyst"], data_source="data/synthetic/response_logs.csv (SYNTHETIC)")
    db.commit()
    posts = build_leak_posts(db, truth, rng)
    manifest = write_outputs(df, posts, truth, db)
    raw = (OUT_DIR / "leak_simulation_posts.jsonl").read_bytes()
    import_dataset(db, org.id, users["analyst"], raw, "leak_simulation_posts.jsonl",
                   "Leak simulation dataset (SYNTHETIC, seed 107)", "synthetic_demo",
                   "Deterministic synthetic posts: Telegram-style exports, a video transcript and forum posts. "
                   "Not collected from any real channel.", is_synthetic=True)
    db.commit()
    det = run_detection(db, org.id, users["analyst"])
    db.commit()
    # re-calibrate with suspected leaks excluded from the Rasch linking (contaminated anchors bias equating)
    run_calibration(db, org.id, users["analyst"],
                    data_source="data/synthetic/response_logs.csv (SYNTHETIC) — post-detection recalibration")
    db.commit()
    asm = None
    if with_next_drive:
        asm = run_assembly(db, org.id, users["designer"], {
            "drive": NEXT_DRIVE, "n_slots": 10, "per_section": {"QUANT": 10, "LOGICAL": 10, "VERBAL": 10},
            "max_adjacent_overlap_pct": 10, "seed": SEED, "start_date": "2026-11-09T04:00:00", "duration_minutes": 40,
            "section_weights": {"QUANT": 1.0, "LOGICAL": 1.0, "VERBAL": 1.0}})
        if asm.status == "succeeded":
            publish_run(db, asm, users["admin"])
        db.commit()
    audit.record(db, users["admin"], "demo.seeded", "system", "demo", f"Deterministic demo data seeded (seed {SEED})",
                 {"responses": report["responses_created"], "pending_reviews": len(pending)}, org_id=org.id)
    db.commit()
    return {"responses": report["responses_created"], "attempts": report["attempts_created"], "pending": len(pending),
            "leak_run": det.summary, "assembly": asm.status if asm else None, "manifest": manifest,
            "_GenerationRun": GenerationRun.__tablename__, "check": Check.__name__}
