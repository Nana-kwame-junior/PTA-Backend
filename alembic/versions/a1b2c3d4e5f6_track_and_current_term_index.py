"""Add track columns to academic_terms and students; partial unique index on current terms per track."""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "academic_terms",
        sa.Column(
            "track",
            sa.Enum("BASIC", "SHS", name="classleveltrack"),
            server_default="BASIC",
            nullable=False,
        ),
    )

    op.execute("""
        UPDATE academic_terms t
        SET track = y.track
        FROM academic_years y
        WHERE t.academic_year_id = y.id
    """)

    op.alter_column("academic_terms", "track", server_default=None)

    op.add_column(
        "students",
        sa.Column(
            "track",
            sa.Enum("BASIC", "SHS", name="classleveltrack"),
            server_default="BASIC",
            nullable=False,
        ),
    )

    op.execute("""
        UPDATE students s
        SET track = COALESCE(
            (SELECT c.track FROM class_levels c WHERE c.name = s.form LIMIT 1),
            CASE WHEN s.form LIKE 'Form %' THEN CAST('SHS' AS classleveltrack)
                 ELSE CAST('BASIC' AS classleveltrack) END
        )
        WHERE s.form IS NOT NULL AND s.form <> ''
    """)

    op.create_index(
        "one_current_term_per_track",
        "academic_terms",
        ["track"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE"),
    )


def downgrade():
    op.drop_index("one_current_term_per_track", table_name="academic_terms")
    op.drop_column("students", "track")
    op.drop_column("academic_terms", "track")
