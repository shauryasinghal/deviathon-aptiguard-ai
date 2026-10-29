"""tenant-scoped uniqueness for slots (drive, sequence) and candidate codes

Two organisations may run a drive with the same name and use the same candidate references. The old constraints were
global, so the second organisation's insert failed (HTTP 500). Relaxing a global constraint to a per-organisation one
cannot be violated by existing data. Slot.code, TestForm.code and Question.code intentionally stay globally unique.
Downgrade restores the global constraints and FAILS if two organisations now share a drive/sequence or candidate code.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29 20:00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('slots', schema=None) as batch_op:
        batch_op.drop_constraint('uq_slots_drive', type_='unique')
        batch_op.create_unique_constraint('uq_slots_org_drive_sequence', ['org_id', 'drive', 'sequence'])
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_constraint('uq_candidates_code', type_='unique')
        batch_op.create_unique_constraint('uq_candidates_org_code', ['org_id', 'code'])


def downgrade() -> None:
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_constraint('uq_candidates_org_code', type_='unique')
        batch_op.create_unique_constraint('uq_candidates_code', ['code'])
    with op.batch_alter_table('slots', schema=None) as batch_op:
        batch_op.drop_constraint('uq_slots_org_drive_sequence', type_='unique')
        batch_op.create_unique_constraint('uq_slots_drive', ['drive', 'sequence'])
