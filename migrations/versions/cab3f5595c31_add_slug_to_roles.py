"""add-slug-to-roles

Revision ID: cab3f5595c31
Revises: 5ded5fe24ff6
Create Date: 2026-04-09 12:49:27.543757

"""

# revision identifiers, used by Alembic.
revision = "cab3f5595c31"
down_revision = "5ded5fe24ff6"

import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.batch_alter_table("volunteer_role_interest", schema=None) as batch_op:
        batch_op.drop_constraint("fk_volunteer_role_interest_role_id_volunteer_role", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_volunteer_role_interest_role_id_volunteer_role",
            "volunteer_role",
            ["role_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("volunteer_role_training", schema=None) as batch_op:
        batch_op.drop_constraint("fk_volunteer_role_training_role_id_volunteer_role", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_volunteer_role_training_role_id_volunteer_role",
            "volunteer_role",
            ["role_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.drop_constraint("fk_volunteer_shift_role_id_volunteer_role", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_volunteer_shift_role_id_volunteer_role",
            "volunteer_role",
            ["role_id"],
            ["id"],
        )

    op.execute("DELETE FROM volunteer_shift")
    op.execute("DELETE FROM volunteer_role")

    with op.batch_alter_table("volunteer_role", schema=None) as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(), nullable=False))
        batch_op.create_index(batch_op.f("ix_volunteer_role_slug"), ["slug"], unique=True)
        batch_op.drop_index(batch_op.f("ix_volunteer_role_name"))


def downgrade():
    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.drop_constraint("fk_volunteer_shift_role_id_volunteer_role", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_volunteer_shift_role_id_volunteer_role",
            "volunteer_role",
            ["role_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("volunteer_role_training", schema=None) as batch_op:
        batch_op.drop_constraint("fk_volunteer_role_training_role_id_volunteer_role", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_volunteer_role_training_role_id_volunteer_role",
            "volunteer_role",
            ["role_id"],
            ["id"],
        )

    with op.batch_alter_table("volunteer_role_interest", schema=None) as batch_op:
        batch_op.drop_constraint("fk_volunteer_role_interest_role_id_volunteer_role", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_volunteer_role_interest_role_id_volunteer_role",
            "volunteer_role",
            ["role_id"],
            ["id"],
        )

    with op.batch_alter_table("volunteer_role", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_volunteer_role_slug"))
        batch_op.drop_column("slug")
        batch_op.create_index(batch_op.f("ix_volunteer_role_name"), ["name"], unique=True)
