"""Specialist relay maps + specialist message credits on user_balances.

Revision ID: 002_specialist
Revises: 001_baseline
Create Date: 2026-04-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_specialist"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_balances",
        sa.Column("specialist_free_used", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "user_balances",
        sa.Column("specialist_pack_credits", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "specialist_relay_maps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("specialist_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("bridge_message_id", sa.Integer(), nullable=False),
        sa.Column("patient_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("specialist_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_relay_specialist_bridge",
        "specialist_relay_maps",
        ["specialist_chat_id", "bridge_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_relay_specialist_bridge", table_name="specialist_relay_maps")
    op.drop_table("specialist_relay_maps")
    op.drop_column("user_balances", "specialist_pack_credits")
    op.drop_column("user_balances", "specialist_free_used")
