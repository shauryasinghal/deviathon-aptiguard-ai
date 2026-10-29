"""add the two cyclic foreign keys that create_table skipped (use_alter) on non-SQLite databases

Alembic's create_table ignores ForeignKeyConstraint(use_alter=True), so on PostgreSQL migration 0001 never created
questions.generation_run_id -> generation_runs.id and variant_families.source_question_id -> questions.id.
SQLite already has them (they were emitted inline), so this migration only acts where they are missing.
If orphaned rows exist, creating the constraint fails loudly instead of silently skipping enforcement.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FKS = [
    ("fk_question_generation_run", "questions", "generation_runs", ["generation_run_id"]),
    ("fk_family_source_question", "variant_families", "questions", ["source_question_id"]),
]


def _existing(table: str) -> set[str]:
    return {fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys(table) if fk.get("name")} | {
        tuple(fk["constrained_columns"]) for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return  # present since 0001 (inline FKs)
    for name, table, ref, cols in FKS:
        have = _existing(table)
        if name in have or tuple(cols) in have:
            continue
        op.create_foreign_key(name, table, ref, cols, ["id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for name, table, _ref, _cols in FKS:
        op.drop_constraint(name, table, type_="foreignkey")
