"""server-observed item timing columns on attempts

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29 19:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('current_item_ref', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('current_item_since', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.drop_column('current_item_since')
        batch_op.drop_column('current_item_ref')
