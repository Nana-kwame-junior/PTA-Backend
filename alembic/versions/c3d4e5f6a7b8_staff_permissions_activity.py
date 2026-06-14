"""Staff permissions and activity log tables."""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("permissions", sa.JSON(), nullable=True))
    op.create_table(
        "staff_activity_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("user_name", sa.String(length=255), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("page_label", sa.String(length=120), nullable=False),
        sa.Column("action_label", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_staff_activity_logs_user_id", "staff_activity_logs", ["user_id"])


def downgrade():
    op.drop_index("ix_staff_activity_logs_user_id", table_name="staff_activity_logs")
    op.drop_table("staff_activity_logs")
    op.drop_column("users", "permissions")
