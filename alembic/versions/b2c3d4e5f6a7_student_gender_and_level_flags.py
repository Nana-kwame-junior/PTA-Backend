"""Add gender and class-level flags; nullable student index/stream."""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "ae791ce8d898"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("students", sa.Column("gender", sa.String(length=1), nullable=True))
    op.alter_column("students", "index_number", existing_type=sa.String(length=50), nullable=True)
    op.alter_column("students", "stream", existing_type=sa.String(length=100), nullable=True)

    op.add_column(
        "class_levels",
        sa.Column("requires_index_number", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "class_levels",
        sa.Column("requires_stream", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade():
    op.drop_column("class_levels", "requires_stream")
    op.drop_column("class_levels", "requires_index_number")
    op.alter_column("students", "stream", existing_type=sa.String(length=100), nullable=False)
    op.alter_column("students", "index_number", existing_type=sa.String(length=50), nullable=False)
    op.drop_column("students", "gender")
