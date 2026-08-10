"""Add meeting end_date/end_time and audience_track for SMS targeting."""

from alembic import op
import sqlalchemy as sa

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TYPE meetingaudience AS ENUM ('BOTH', 'BASIC', 'SHS');")
    op.add_column(
        "meetings",
        sa.Column("end_date", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "meetings",
        sa.Column("end_time", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "meetings",
        sa.Column(
            "audience_track",
            sa.Enum("BOTH", "BASIC", "SHS", name="meetingaudience", create_type=False),
            nullable=False,
            server_default="BOTH",
        ),
    )
    op.alter_column("meetings", "audience_track", server_default=None)


def downgrade():
    op.drop_column("meetings", "audience_track")
    op.drop_column("meetings", "end_time")
    op.drop_column("meetings", "end_date")
    op.execute("DROP TYPE IF EXISTS meetingaudience;")
