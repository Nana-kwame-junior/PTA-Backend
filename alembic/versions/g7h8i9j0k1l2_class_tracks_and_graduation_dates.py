"""Add track columns to class_levels, academic_years and graduation dates to students."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TYPE classleveltrack AS ENUM ('BASIC', 'SHS');")

    op.add_column(
        "class_levels",
        sa.Column(
            "track",
            sa.Enum("BASIC", "SHS", name="classleveltrack"),
            server_default="BASIC",
            nullable=False,
        ),
    )

    op.execute(
        "UPDATE class_levels SET track = 'SHS' WHERE name LIKE 'Form %';"
    )
    op.execute(
        "UPDATE class_levels SET track = 'BASIC' WHERE name NOT LIKE 'Form %';"
    )

    op.alter_column("class_levels", "track", server_default=None)

    op.add_column(
        "academic_years",
        sa.Column(
            "track",
            sa.Enum("BASIC", "SHS", name="classleveltrack"),
            server_default="BASIC",
            nullable=False,
        ),
    )

    op.add_column("students", sa.Column("graduated_basic_at", sa.DateTime(), nullable=True))
    op.add_column("students", sa.Column("graduated_shs_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("students", "graduated_shs_at")
    op.drop_column("students", "graduated_basic_at")
    op.drop_column("academic_years", "track")
    op.drop_column("class_levels", "track")
    op.execute("DROP TYPE classleveltrack;")
