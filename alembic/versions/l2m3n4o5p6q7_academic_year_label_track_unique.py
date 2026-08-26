"""Allow the same academic year label on BASIC and SHS tracks."""

from alembic import op
import sqlalchemy as sa

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("academic_years"):
        columns = list(constraint.get("column_names") or [])
        if columns == ["label"]:
            op.drop_constraint(constraint["name"], "academic_years", type_="unique")
            break
    op.create_unique_constraint(
        "uq_academic_year_label_track",
        "academic_years",
        ["label", "track"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_academic_year_label_track", "academic_years", type_="unique")
    op.create_unique_constraint("academic_years_label_key", "academic_years", ["label"])
