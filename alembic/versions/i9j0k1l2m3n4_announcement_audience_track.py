"""Add audience_track to announcements for BASIC / SHS / BOTH SMS targeting."""

from alembic import op
import sqlalchemy as sa

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TYPE announcementaudience AS ENUM ('BOTH', 'BASIC', 'SHS');")
    op.add_column(
        "announcements",
        sa.Column(
            "audience_track",
            sa.Enum("BOTH", "BASIC", "SHS", name="announcementaudience", create_type=False),
            nullable=False,
            server_default="BOTH",
        ),
    )
    op.alter_column("announcements", "audience_track", server_default=None)


def downgrade():
    op.drop_column("announcements", "audience_track")
    op.execute("DROP TYPE IF EXISTS announcementaudience;")
