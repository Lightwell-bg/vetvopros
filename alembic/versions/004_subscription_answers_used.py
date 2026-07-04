"""Subscription: answers used in current period (MVP: per subscription row window).

Revision ID: 004_sub_answers
Revises: 003_rag_audit
Create Date: 2026-04-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_sub_answers"
down_revision: Union[str, None] = "003_rag_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("subscription_answers_used", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "subscription_answers_used")
