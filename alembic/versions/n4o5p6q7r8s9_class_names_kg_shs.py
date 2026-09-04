"""Rename class levels: KG → KG 1, Form 1–3 → SHS 1–3; add KG 2."""

from alembic import op
import sqlalchemy as sa


revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE class_levels SET name = 'SHS 1' WHERE name = 'Form 1'"))
    op.execute(sa.text("UPDATE class_levels SET name = 'SHS 2' WHERE name = 'Form 2'"))
    op.execute(sa.text("UPDATE class_levels SET name = 'SHS 3' WHERE name = 'Form 3'"))
    op.execute(sa.text("UPDATE students SET form = 'SHS 1' WHERE form = 'Form 1'"))
    op.execute(sa.text("UPDATE students SET form = 'SHS 2' WHERE form = 'Form 2'"))
    op.execute(sa.text("UPDATE students SET form = 'SHS 3' WHERE form = 'Form 3'"))

    op.execute(sa.text("UPDATE class_levels SET name = 'KG 1' WHERE name = 'KG'"))
    op.execute(sa.text("UPDATE students SET form = 'KG 1' WHERE form = 'KG'"))

    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM class_levels WHERE name = 'KG 2' LIMIT 1")
    ).first()
    if not exists:
        op.execute(
            sa.text(
                "UPDATE class_levels SET sequence = sequence + 100 WHERE sequence >= 2"
            )
        )
        op.execute(
            sa.text(
                """
                INSERT INTO class_levels (
                    id, name, sequence, track, is_terminal,
                    requires_index_number, requires_stream, is_active, created_at
                )
                VALUES (
                    gen_random_uuid()::text,
                    'KG 2',
                    2,
                    'BASIC',
                    false,
                    false,
                    false,
                    true,
                    NOW()
                )
                """
            )
        )
        op.execute(
            sa.text(
                "UPDATE class_levels SET sequence = sequence - 99 WHERE sequence >= 102"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE students SET form = 'Form 1' WHERE form = 'SHS 1'"))
    op.execute(sa.text("UPDATE students SET form = 'Form 2' WHERE form = 'SHS 2'"))
    op.execute(sa.text("UPDATE students SET form = 'Form 3' WHERE form = 'SHS 3'"))
    op.execute(sa.text("UPDATE class_levels SET name = 'Form 1' WHERE name = 'SHS 1'"))
    op.execute(sa.text("UPDATE class_levels SET name = 'Form 2' WHERE name = 'SHS 2'"))
    op.execute(sa.text("UPDATE class_levels SET name = 'Form 3' WHERE name = 'SHS 3'"))
    op.execute(sa.text("UPDATE students SET form = 'KG' WHERE form IN ('KG 1', 'KG 2')"))
    op.execute(sa.text("UPDATE class_levels SET name = 'KG' WHERE name = 'KG 1'"))
    op.execute(sa.text("UPDATE class_levels SET is_active = false WHERE name = 'KG 2'"))
