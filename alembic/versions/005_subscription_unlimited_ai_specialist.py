"""Subscription: unlimited AI flag + specialist units per period; usage on subscription row.

Revision ID: 005_sub_ai_sp
Revises: 004_sub_answers
Create Date: 2026-04-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_sub_ai_sp"
down_revision: Union[str, None] = "004_sub_answers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column("unlimited_ai", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "specialist_units_included_per_period",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "subscription_specialist_used",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "subscription_specialist_used")
    op.drop_column("subscription_plans", "specialist_units_included_per_period")
    op.drop_column("subscription_plans", "unlimited_ai")
