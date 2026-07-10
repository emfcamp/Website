"""Cascade shift entry deletions

Revision ID: 598e3b09eb38
Revises: b34ee11a7db6
Create Date: 2026-07-10 23:02:06.299281

"""

# revision identifiers, used by Alembic.
revision = "598e3b09eb38"
down_revision = "b34ee11a7db6"

import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.batch_alter_table("volunteer_shift_entry", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_volunteer_shift_entry_shift_id_volunteer_shift"), type_="foreignkey"
        )
        batch_op.drop_constraint(batch_op.f("fk_volunteer_shift_entry_user_id_user"), type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_entry_shift_id_volunteer_shift"),
            "volunteer_shift",
            ["shift_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_entry_user_id_user"),
            "user",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table("volunteer_shift_entry", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_volunteer_shift_entry_user_id_user"), type_="foreignkey")
        batch_op.drop_constraint(
            batch_op.f("fk_volunteer_shift_entry_shift_id_volunteer_shift"), type_="foreignkey"
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_entry_user_id_user"), "user", ["user_id"], ["id"]
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_volunteer_shift_entry_shift_id_volunteer_shift"),
            "volunteer_shift",
            ["shift_id"],
            ["id"],
        )
