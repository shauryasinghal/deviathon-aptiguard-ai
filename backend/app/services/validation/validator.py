"""Item quality gates: schema, answer verification, ambiguity, duplicates.

Overall status: failed (any critical failure) > warning (any warning) > passed.
Only *non-failed* items may be approved, and approval always requires an explicit human decision.
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from fractions import Fraction

from app.services.generation.base import Check, GeneratedItem
from app.services.generation.registry import TEMPLATES
from app.services.textsim import char_cosine_matrix, item_fulltext, normalize, text_hash

NEAR_DUP_FAIL = 0.93
NEAR_DUP_WARN = 0.86
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:/\d+)?")


@dataclass
class BankEntry:
    id: int | None
    code: str
    fulltext_norm: str
    hash: str
    template_id: str | None
    params: dict | None


# ------------------------------------------------------------------ safe arithmetic for LLM verification
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expr: str) -> Fraction:
    """Evaluate a pure arithmetic expression exactly. Rejects names, calls, attributes, huge powers."""

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Fraction(str(node.value))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (right.denominator != 1 or abs(right) > 12):
                raise ValueError("unsupported exponent")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"disallowed syntax: {type(node).__name__}")

    if len(expr) > 200:
        raise ValueError("expression too long")
    return ev(ast.parse(expr, mode="eval"))


def _num_value(text: str) -> Fraction | None:
    m = _NUM_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return Fraction(m.group())
    except (ValueError, ZeroDivisionError):
        return None


# ------------------------------------------------------------------ checks
def structural_checks(item: GeneratedItem) -> list[Check]:
    c: list[Check] = []
    missing = [f for f in ("stem", "explanation", "skill", "difficulty") if not getattr(item, f)]
    if len(item.stem.strip()) < 15:
        missing.append("stem(too short)")
    c.append(Check("schema_complete", "fail" if missing else "pass",
                   f"Missing/invalid: {missing}" if missing else "All required fields present",
                   "critical" if missing else "info"))
    if item.difficulty not in ("easy", "medium", "hard"):
        c.append(Check("difficulty_valid", "fail", f"Unknown difficulty '{item.difficulty}'", "critical"))
    keys = [o["key"] for o in item.options]
    if len(item.options) != 4 or len(set(keys)) != 4:
        c.append(Check("option_count", "fail", f"Expected 4 uniquely keyed options, got {keys}", "critical"))
    else:
        c.append(Check("option_count", "pass", "Four uniquely keyed options"))
    n_correct = sum(1 for o in item.options if o["is_correct"])
    c.append(Check("single_correct", "pass" if n_correct == 1 else "fail",
                   f"{n_correct} option(s) marked correct", "info" if n_correct == 1 else "critical"))
    texts = [normalize(o["text"]) for o in item.options]
    if any(not t for t in texts):
        c.append(Check("options_nonempty", "fail", "Empty option text", "critical"))
    if len(set(texts)) != len(texts):
        c.append(Check("options_distinct", "fail", "Two options have identical text", "critical"))
    else:
        nums = [_num_value(o["text"]) for o in item.options]
        units = [re.sub(_NUM_RE, "", normalize(o["text"])).strip() for o in item.options]
        n = len(item.options)
        clash = [(item.options[i]["key"], item.options[j]["key"]) for i in range(n) for j in range(i + 1, n)
                 if nums[i] is not None and nums[i] == nums[j] and units[i] == units[j]]
        c.append(Check("options_distinct", "fail" if clash else "pass",
                       f"Numerically equivalent options {clash}" if clash else "Options are distinct",
                       "critical" if clash else "info"))
    correct = item.correct_text or ""
    if len(correct) > 3 and normalize(correct) in normalize(item.stem) and item.section == "QUANT":
        c.append(Check("answer_not_in_stem", "warn", "Correct answer text appears in the stem", "warning"))
    return c


def answer_checks(item: GeneratedItem, generation_method: str) -> list[Check]:
    tpl = TEMPLATES.get(item.template_id) if item.template_id else None
    if tpl and item.params and generation_method != "llm":
        try:
            return tpl.verify(item.params, item)
        except Exception as e:  # malformed params from an edit
            return [Check("answer_recomputed", "fail", f"Verification could not run: {e.__class__.__name__}", "critical")]
    expr = (item.params or {}).get("verification_expression")
    if item.section == "QUANT" and expr:
        try:
            val = safe_eval(expr)
        except (ValueError, SyntaxError, ZeroDivisionError) as e:
            return [Check("answer_recomputed", "fail", f"Verification expression invalid: {e}", "critical")]
        keyed = _num_value(item.correct_text or "")
        if keyed is not None and abs(float(keyed) - float(val)) < 0.01:
            return [Check("answer_recomputed", "pass", f"Expression {expr} = {float(val):g} matches key")]
        return [Check("answer_recomputed", "fail", f"Expression gives {float(val):g}, key is '{item.correct_text}'", "critical")]
    if item.section == "VERBAL":
        return [Check("linguistic_review", "warn", "Verbal item: no deterministic verifier; mandatory human review", "warning")]
    return [Check("answer_unverified", "warn",
                  "No deterministic verifier for this item; reviewer must solve it independently", "warning")]


# Parameters that only change the surface (names, objects, scenario framing). Two items that agree on every
# other parameter are answer-equivalent clones, so they count as duplicates even if names differ.
SURFACE_KEYS = {"who", "names", "thing", "ctx", "liquid"}


def _core(params: dict) -> dict:
    return {k: v for k, v in params.items() if not k.startswith("_") and k not in SURFACE_KEYS}


def duplicate_checks(item: GeneratedItem, bank: list[BankEntry], exclude_ids: set[int] | None = None) -> list[Check]:
    exclude_ids = exclude_ids or set()
    full = normalize(item_fulltext(item.stem, [o["text"] for o in item.options]))
    h = text_hash(item_fulltext(item.stem, [o["text"] for o in item.options]))
    others = [b for b in bank if b.id not in exclude_ids]
    for b in others:
        if b.hash == h:
            return [Check("duplicate_exact", "fail", f"Exact duplicate of {b.code}", "critical", {"match": b.code})]
        if b.template_id and b.template_id == item.template_id and b.params and item.params and _core(b.params) == _core(item.params):
            return [Check("duplicate_params", "fail", f"Answer-equivalent clone of {b.code} (same template parameters; only names/scenario differ)", "critical", {"match": b.code})]
    if not others:
        return [Check("duplicate_near", "pass", "No comparison items in bank")]
    sims = char_cosine_matrix([full], [b.fulltext_norm for b in others])[0]
    j = int(sims.argmax())
    best = float(sims[j])
    detail = {"nearest": others[j].code, "similarity": round(best, 3)}
    if best >= NEAR_DUP_FAIL:
        return [Check("duplicate_near", "fail", f"Near-duplicate of {others[j].code} (similarity {best:.2f})", "critical", detail)]
    if best >= NEAR_DUP_WARN:
        return [Check("duplicate_near", "warn", f"Very similar to {others[j].code} (similarity {best:.2f})", "warning", detail)]
    return [Check("duplicate_near", "pass", f"Nearest item {others[j].code} at similarity {best:.2f}", details=detail)]


def validate(item: GeneratedItem, bank: list[BankEntry], generation_method: str = "template",
             exclude_ids: set[int] | None = None, source_difficulty: str | None = None) -> tuple[str, list[Check]]:
    checks = structural_checks(item)
    if not any(c.status == "fail" for c in checks):
        checks += answer_checks(item, generation_method)
    checks += duplicate_checks(item, bank, exclude_ids)
    if source_difficulty and item.difficulty != source_difficulty:
        checks.append(Check("parallel_difficulty", "warn",
                            f"Target difficulty '{item.difficulty}' differs from source '{source_difficulty}': "
                            "this is a new item, not a parallel form", "warning"))
    if item.review_requirement:
        checks.append(Check("review_requirement", "warn", item.review_requirement, "warning"))
    return overall(checks), checks


def overall(checks: list[Check]) -> str:
    if any(c.status == "fail" and c.severity == "critical" for c in checks):
        return "failed"
    if any(c.status in ("warn", "fail") for c in checks):
        return "warning"
    return "passed"
