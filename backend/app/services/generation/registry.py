from __future__ import annotations

import random

from app.services.generation.base import GeneratedItem, Template
from app.services.generation.logical import LOGICAL_TEMPLATES
from app.services.generation.quant import QUANT_TEMPLATES
from app.services.generation.verbal import VERBAL_TEMPLATES

TEMPLATES: dict[str, Template] = {t.id: t for t in QUANT_TEMPLATES + LOGICAL_TEMPLATES + VERBAL_TEMPLATES}
DIFFICULTY_B = {"easy": -1.0, "medium": 0.0, "hard": 1.0}


def templates_for(section: str) -> list[Template]:
    return [t for t in TEMPLATES.values() if t.section == section]


def generate(template_id: str, difficulty: str, seed: int) -> GeneratedItem:
    return TEMPLATES[template_id].generate(random.Random(seed), difficulty)


def catalog() -> list[dict]:
    return [{"id": t.id, "section": t.section, "concept": t.concept, "skill": t.skill} for t in TEMPLATES.values()]
