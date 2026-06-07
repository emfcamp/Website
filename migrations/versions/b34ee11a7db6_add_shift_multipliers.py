"""Add shift multipliers

Revision ID: b34ee11a7db6
Revises: 3b07c4eea8ea
Create Date: 2026-06-07 10:16:53.549323

"""

# revision identifiers, used by Alembic.
revision = "b34ee11a7db6"
down_revision = "07d0c7108150"

import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.add_column(sa.Column("multiplier", sa.Numeric(), nullable=False, server_default="1"))

    with op.batch_alter_table("volunteer_shift_version", schema=None) as batch_op:
        batch_op.add_column(sa.Column("multiplier", sa.Numeric(), autoincrement=False, nullable=True))

    with op.batch_alter_table("volunteer_shift_template", schema=None) as batch_op:
        batch_op.add_column(sa.Column("multiplier", sa.Numeric(), nullable=False, server_default="1"))

    with op.batch_alter_table("volunteer_shift_template_version", schema=None) as batch_op:
        batch_op.add_column(sa.Column("multiplier", sa.Numeric(), autoincrement=False, nullable=True))


def downgrade():
    with op.batch_alter_table("volunteer_shift_version", schema=None) as batch_op:
        batch_op.drop_column("multiplier")

    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.drop_column("multiplier")

    with op.batch_alter_table("volunteer_shift_template_version", schema=None) as batch_op:
        batch_op.drop_column("multiplier")

    with op.batch_alter_table("volunteer_shift_template", schema=None) as batch_op:
        batch_op.drop_column("multiplier")
