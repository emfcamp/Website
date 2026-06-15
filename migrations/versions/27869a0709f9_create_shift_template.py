"""create shift template

Revision ID: 27869a0709f9
Revises: d18ebf8aaf67
Create Date: 2026-06-15 12:52:42.604760

"""

# revision identifiers, used by Alembic.
revision = "27869a0709f9"
down_revision = "d18ebf8aaf67"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.create_table(
        "volunteer_shift_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("event_day", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("changeover_time", sa.Integer(), nullable=False),
        sa.Column("min_needed", sa.Integer(), nullable=False),
        sa.Column("max_needed", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["volunteer_role.id"],
            name=op.f("fk_volunteer_shift_template_role_id_volunteer_role"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["volunteer_venue.id"],
            name=op.f("fk_volunteer_shift_template_venue_id_volunteer_venue"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_volunteer_shift_template")),
    )
    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shift_template_id", sa.Integer(), nullable=True))
        batch_op.drop_constraint(batch_op.f("fk_volunteer_shift_role_id_volunteer_role"), type_="foreignkey")
        batch_op.drop_constraint(
            batch_op.f("fk_volunteer_shift_venue_id_volunteer_venue"), type_="foreignkey"
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_role_id_volunteer_role"),
            "volunteer_role",
            ["role_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_venue_id_volunteer_venue"),
            "volunteer_venue",
            ["venue_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_shift_template_id_volunteer_shift_template"),
            "volunteer_shift_template",
            ["shift_template_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("volunteer_shift_version", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shift_template_id", sa.Integer(), autoincrement=False, nullable=True))


def downgrade():
    with op.batch_alter_table("volunteer_shift_version", schema=None) as batch_op:
        batch_op.drop_column("shift_template_id")

    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_volunteer_shift_shift_template_id_volunteer_shift_template"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            batch_op.f("fk_volunteer_shift_venue_id_volunteer_venue"), type_="foreignkey"
        )
        batch_op.drop_constraint(batch_op.f("fk_volunteer_shift_role_id_volunteer_role"), type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_venue_id_volunteer_venue"), "volunteer_venue", ["venue_id"], ["id"]
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_role_id_volunteer_role"), "volunteer_role", ["role_id"], ["id"]
        )
        batch_op.drop_column("shift_template_id")

    op.drop_table("volunteer_shift_template")
