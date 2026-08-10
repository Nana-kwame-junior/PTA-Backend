"""Widen meetings.term so both-track labels fit (e.g. Term 1 + Semester 1)."""

from alembic import op
import sqlalchemy as sa

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "meetings",
        "term",
        existing_type=sa.String(length=20),
        type_=sa.String(length=80),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "meetings",
        "term",
        existing_type=sa.String(length=80),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
