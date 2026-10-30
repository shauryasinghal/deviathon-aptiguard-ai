"""external identities (Google) and single-use auth tokens

Adds two new tables only; no existing table or row is touched. Downgrade drops them (all linked Google identities,
pending reset tokens and OAuth state are lost; local accounts and passwords are unaffected).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('external_identities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_external_identities_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_external_identities')),
    sa.UniqueConstraint('provider', 'subject', name='uq_external_identities_provider_subject'),
    sa.UniqueConstraint('user_id', 'provider', name='uq_external_identities_user_provider')
    )
    with op.batch_alter_table('external_identities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_external_identities_user_id'), ['user_id'], unique=False)

    op.create_table('auth_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_tokens_token_hash'))
    )
    with op.batch_alter_table('auth_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_tokens_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_tokens_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_tokens_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('auth_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auth_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_auth_tokens_kind'))
        batch_op.drop_index(batch_op.f('ix_auth_tokens_expires_at'))
    op.drop_table('auth_tokens')
    with op.batch_alter_table('external_identities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_external_identities_user_id'))
    op.drop_table('external_identities')
