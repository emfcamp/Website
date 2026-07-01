"""shift finalisation

Revision ID: 045afaa29b79
Revises: 9dd45df03fb4
Create Date: 2026-07-01 22:43:27.367897

"""

# revision identifiers, used by Alembic.
revision = "045afaa29b79"
down_revision = "9dd45df03fb4"

import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.batch_alter_table("volunteer_role", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shifts_finalised", sa.Boolean(), nullable=False, server_default="f"))

    with op.batch_alter_table("volunteer_role_version", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "shifts_finalised", sa.Boolean(), autoincrement=False, nullable=True, server_default="f"
            )
        )


def downgrade():
    with op.batch_alter_table("volunteer_role_version", schema=None) as batch_op:
        batch_op.drop_column("shifts_finalised")

    with op.batch_alter_table("volunteer_role", schema=None) as batch_op:
        batch_op.drop_column("shifts_finalised")
