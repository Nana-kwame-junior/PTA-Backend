"""Add otp_sessions table for OTP fallback when Redis is unavailable."""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "otp_sessions",
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("phone"),
    )


def downgrade():
    op.drop_table("otp_sessions")
