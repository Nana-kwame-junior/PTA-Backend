"""Add image_urls JSON column to announcements."""

from alembic import op
import sqlalchemy as sa

revision = "h8i9j0k1l2m3"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "announcements",
        sa.Column(
            "image_urls",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column("announcements", "image_urls", server_default=None)


def downgrade():
    op.drop_column("announcements", "image_urls")
