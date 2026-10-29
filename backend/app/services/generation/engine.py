"""Variant generation orchestration. Every generated item lands in the review queue; nothing auto-publishes."""
from __future__ import annotations

import random
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Unprocessable
from app.db.base import utcnow
from app.models import GenerationRun, Question, User
from app.services import audit
from app.services.generation.base import TEMPLATE_VERSION, GeneratedItem
from app.services.generation.llm_adapter import PROMPT_VERSION, LLMUnavailable, generate_llm_variants
from app.services.generation.registry import TEMPLATES, generate
from app.services.questions import add_revision, bank_entries, create_from_item, next_variant_code, persist_checks
from app.services.textsim import item_fulltext, normalize, text_hash
from app.services.validation.validator import BankEntry, validate

MAX_ATTEMPTS_PER_VARIANT = 6


def generate_variants(
    db: Session, source: Question, n: int, difficulty: str | None, user: User | None,
    seed: int | None = None, method: str = "auto", keep_rejected: bool = True,
) -> tuple[GenerationRun, list[Question], list[dict]]:
    """Generate n variants of `source`. Returns (run, persisted questions, rejection log)."""
    difficulty = difficulty or source.difficulty_target
    settings = get_settings()
    use_llm = method == "llm" or (method == "auto" and settings.llm_configured and source.template_id not in TEMPLATES)
    if method == "template" or not use_llm:
        if source.template_id not in TEMPLATES:
            raise Unprocessable(
                "No deterministic template exists for this item and no LLM provider is configured. "
                "Configure LLM_PROVIDER/LLM_API_KEY or author variants manually.",
                {"source": source.code, "template_id": source.template_id},
            )
        use_llm = False
    seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31)
    run = GenerationRun(
        source_question_id=source.id, requested_by=user.id if user else None, method="llm" if use_llm else "template",
        provider=settings.llm_provider if use_llm else "deterministic-template",
        model=settings.llm_model if use_llm else None,
        prompt_version=PROMPT_VERSION if use_llm else f"template-{TEMPLATE_VERSION}", seed=seed,
        target_difficulty=difficulty, n_requested=n,
    )
    db.add(run)
    db.flush()
    t0 = time.perf_counter()

    bank: list[BankEntry] = bank_entries(db, source.org_id)
    candidates: list[GeneratedItem]
    if use_llm:
        try:
            candidates = generate_llm_variants(
                {"section": source.section.code, "skill": source.skill, "concept": source.family.concept,
                 "stem": source.stem, "template_id": source.template_id, "tags": source.tags,
                 "options": [{"key": o.key, "text": o.text, "is_correct": o.is_correct} for o in source.options]},
                n, difficulty)
        except LLMUnavailable as e:
            run.status, run.message, run.finished_at = "failed", str(e), utcnow()
            audit.record(db, user, "variants.generate_failed", "question", source.code, f"LLM generation failed: {e}")
            db.commit()
            raise Unprocessable(str(e), {"generation_run_id": run.id})
        attempts = [(c, None) for c in candidates]
    else:
        rng = random.Random(seed)
        attempts = []
        for _ in range(n * MAX_ATTEMPTS_PER_VARIANT):
            s = rng.randrange(1, 2**31)
            attempts.append((generate(source.template_id, difficulty, s), s))

    created: list[Question] = []
    rejections: list[dict] = []
    for item, s in attempts:
        if len(created) >= n:
            break
        if s is not None:
            item.params = {**item.params, "_seed": s}
        status, checks = validate(item, bank, "llm" if use_llm else "template", source_difficulty=source.difficulty_target)
        method_label = "llm" if use_llm else "template"
        if status == "failed":
            reasons = [c.message for c in checks if c.status == "fail"]
            rejections.append({"seed": s, "reasons": reasons, "stem_preview": item.stem[:120]})
            run.n_rejected += 1
            if keep_rejected and use_llm:
                q = create_from_item(db, item, org_id=source.org_id, family=source.family, code=next_variant_code(db, source.family),
                                     parent=source, method=method_label, status="rejected", user=user,
                                     generation_run_id=run.id, data_source="generated")
                q.status_reason = "Auto-rejected by validator: " + "; ".join(reasons)[:280]
                q.validation_status = "failed"
                persist_checks(db, q, checks)
            continue
        q = create_from_item(db, item, org_id=source.org_id, family=source.family, code=next_variant_code(db, source.family),
                             parent=source, method=method_label, status="pending_review", user=user,
                             generation_run_id=run.id, data_source="generated", is_synthetic=source.is_synthetic)
        q.validation_status = status
        persist_checks(db, q, checks)
        add_revision(db, q, "created", user, f"Generated by run #{run.id} ({run.provider})")
        created.append(q)
        bank.append(BankEntry(q.id, q.code, normalize(item_fulltext(q.stem, [o.text for o in q.options])),
                              text_hash(item_fulltext(q.stem, [o.text for o in q.options])), q.template_id, q.params))

    run.n_generated = len(created)
    run.status = "succeeded" if len(created) == n else ("partial" if created else "failed")
    run.finished_at = utcnow()
    run.message = (f"{len(created)}/{n} variants passed validation; {run.n_rejected} candidate(s) rejected "
                   f"in {int((time.perf_counter() - t0) * 1000)} ms")
    audit.record(db, user, "variants.generated", "question", source.code, run.message,
                 {"run_id": run.id, "codes": [q.code for q in created], "method": run.method})
    return run, created, rejections
