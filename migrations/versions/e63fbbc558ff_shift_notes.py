"""shift notes

Revision ID: e63fbbc558ff
Revises: c2f0c1f7d1ee
Create Date: 2026-07-05 19:55:34.607434

"""

# revision identifiers, used by Alembic.
revision = "e63fbbc558ff"
down_revision = "3b7a93819f43"

import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notes", sa.String(), nullable=True))

    with op.batch_alter_table("volunteer_shift_version", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notes", sa.String(), autoincrement=False, nullable=True))


def downgrade():
    with op.batch_alter_table("volunteer_shift_version", schema=None) as batch_op:
        batch_op.drop_column("notes")

    with op.batch_alter_table("volunteer_shift", schema=None) as batch_op:
        batch_op.drop_column("notes")
