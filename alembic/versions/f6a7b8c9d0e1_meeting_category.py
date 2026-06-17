"""Add category to meetings (same values as announcement types)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

announcement_type = postgresql.ENUM(
    "GENERAL",
    "URGENT",
    "FINANCIAL",
    "EVENT",
    name="announcementtype",
    create_type=False,
)


def upgrade():
    op.add_column(
        "meetings",
        sa.Column("category", announcement_type, nullable=False, server_default="GENERAL"),
    )
    op.alter_column("meetings", "category", server_default=None)


def downgrade():
    op.drop_column("meetings", "category")
