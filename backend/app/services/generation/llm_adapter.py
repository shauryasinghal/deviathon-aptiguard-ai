"""Optional LLM variant generator (Anthropic Claude via the official SDK, structured output).

Disabled unless LLM_PROVIDER=anthropic and LLM_API_KEY are set. The `anthropic` package is an optional
dependency (requirements-llm.txt) and is imported lazily. LLM output is *never* trusted:
it passes through the same schema checks, duplicate checks and mandatory human review as template output,
and is labelled generation_method="llm".
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.generation.base import KEYS, GeneratedItem

log = logging.getLogger("aptiguard.llm")
PROMPT_VERSION = "llm-variant-v1"


class LLMOption(BaseModel):
    key: str = Field(description="One of A, B, C, D")
    text: str
    is_correct: bool
    rationale: str = Field(description="Why this option is correct, or which misconception it targets")


class LLMVariant(BaseModel):
    stem: str
    options: list[LLMOption]
    explanation: str
    verification_expression: str | None = Field(
        default=None,
        description="Quantitative items only: a pure arithmetic expression (numbers, + - * / ** and parentheses) "
                    "whose value equals the correct option's numeric value.",
    )


class LLMVariantBatch(BaseModel):
    variants: list[LLMVariant]


class LLMUnavailable(RuntimeError):
    pass


SYSTEM = (
    "You write parallel forms of aptitude-test items. A parallel form tests the SAME concept and skill at the SAME "
    "difficulty, but changes the surface: scenario, names, numbers, wording. Never copy the source wording. "
    "Each item has exactly four options (A–D) with exactly one correct answer; distractors must reflect specific, "
    "realistic misconceptions and must be unambiguously wrong. Return only the structured output."
)


def generate_llm_variants(source: dict, n: int, difficulty: str) -> list[GeneratedItem]:
    s = get_settings()
    if not s.llm_configured or s.llm_provider != "anthropic":
        raise LLMUnavailable("LLM provider not configured (set LLM_PROVIDER=anthropic and LLM_API_KEY)")
    try:
        import anthropic  # optional dependency
    except ImportError as e:  # pragma: no cover - depends on optional install
        raise LLMUnavailable("Install backend/requirements-llm.txt to enable the LLM provider") from e

    client = anthropic.Anthropic(api_key=s.llm_api_key, timeout=float(s.llm_timeout_seconds))
    opts = "\n".join(f"{o['key']}. {o['text']}{'  (correct)' if o['is_correct'] else ''}" for o in source["options"])
    user = (
        f"Section: {source['section']}\nSkill: {source['skill']}\nConcept: {source['concept']}\n"
        f"Target difficulty: {difficulty}\n\nSource item:\n{source['stem']}\n{opts}\n\n"
        f"Write {n} parallel variants."
        + (" Include verification_expression for each." if source["section"] == "QUANT" else "")
    )
    try:
        resp = client.messages.parse(
            model=s.llm_model,
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=LLMVariantBatch,
        )
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable(f"LLM provider unreachable: {e.__class__.__name__}") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"LLM provider error HTTP {e.status_code}") from e
    except (anthropic.APIError, ValueError) as e:  # ValueError covers pydantic ValidationError and bad JSON
        raise LLMUnavailable(f"LLM returned malformed output ({e.__class__.__name__})") from e  # class name only: no provider text
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise LLMUnavailable(f"LLM returned no usable output (stop_reason={resp.stop_reason})")

    items: list[GeneratedItem] = []
    for v in resp.parsed_output.variants[:n]:
        options = [
            {"key": KEYS[i] if i < len(KEYS) else o.key, "text": o.text.strip(), "is_correct": o.is_correct,
             "rationale": o.rationale[:300]}
            for i, o in enumerate(v.options)
        ]
        items.append(GeneratedItem(
            section=source["section"], template_id=source.get("template_id") or "LLM", concept=source["concept"],
            skill=source["skill"], difficulty=difficulty, stem=v.stem.strip(), options=options,
            explanation=v.explanation.strip(),
            params={"llm_model": s.llm_model, "prompt_version": PROMPT_VERSION,
                    "verification_expression": v.verification_expression},
            tags=list(source.get("tags") or []),
            review_requirement="LLM-generated: answer correctness is not proven by the model; reviewer must verify.",
        ))
    log.info("llm generated %d variants", len(items))
    return items
