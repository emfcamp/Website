"""volunteer self-training

Revision ID: 2e42f8a6c619
Revises: 9b784af36d7f
Create Date: 2026-07-06 20:30:26.812626

"""

# revision identifiers, used by Alembic.
revision = "2e42f8a6c619"
down_revision = "9b784af36d7f"

import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.batch_alter_table("volunteer_role", schema=None) as batch_op:
        batch_op.add_column(sa.Column("training_notes", sa.String(), nullable=False, server_default=""))
        batch_op.add_column(
            sa.Column("allows_self_training", sa.Boolean(), nullable=False, server_default="f")
        )
        batch_op.add_column(sa.Column("uses_bar_training", sa.Boolean(), nullable=False, server_default="f"))

    with op.batch_alter_table("volunteer_role_version", schema=None) as batch_op:
        batch_op.add_column(sa.Column("training_notes", sa.String(), autoincrement=False, nullable=True))
        batch_op.add_column(
            sa.Column("allows_self_training", sa.Boolean(), autoincrement=False, nullable=True)
        )
        batch_op.add_column(sa.Column("uses_bar_training", sa.Boolean(), autoincrement=False, nullable=True))


def downgrade():
    with op.batch_alter_table("volunteer_role_version", schema=None) as batch_op:
        batch_op.drop_column("allows_self_training")
        batch_op.drop_column("training_notes")

    with op.batch_alter_table("volunteer_role", schema=None) as batch_op:
        batch_op.drop_column("allows_self_training")
        batch_op.drop_column("training_notes")
