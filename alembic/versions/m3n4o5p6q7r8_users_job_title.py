"""Staff job titles on users table."""

from alembic import op
import sqlalchemy as sa


revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("job_title", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE users SET job_title = 'Administrator' WHERE role = 'ADMIN'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE users SET job_title = 'Finance Officer' "
            "WHERE role = 'FINANCIAL_STAFF' AND (job_title IS NULL OR job_title = '')"
        )
    )
    op.execute(
        sa.text("UPDATE users SET job_title = 'Other' WHERE job_title IS NULL")
    )


def downgrade() -> None:
    op.drop_column("users", "job_title")
