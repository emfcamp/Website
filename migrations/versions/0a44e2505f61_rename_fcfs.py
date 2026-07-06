"""Rename FCFS

Revision ID: 0a44e2505f61
Revises: e63fbbc558ff
Create Date: 2026-07-06 12:09:22.685762

"""

# revision identifiers, used by Alembic.
revision = '0a44e2505f61'
down_revision = 'e63fbbc558ff'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # non-native enums aren't enforced in the DB, but this will shorten the column length
    op.execute(sa.text("""update lottery set state = 'sign-up-list' where state = 'first-come-first-served' """))

    with op.batch_alter_table('lottery', schema=None) as batch_op:
        batch_op.alter_column('state',
               existing_type=sa.VARCHAR(length=23),
               type_=sa.Enum('closed', 'allow-entry', 'running-lottery', 'completed', 'sign-up-list', native_enum=False),
               existing_nullable=False)


def downgrade():
    with op.batch_alter_table('lottery', schema=None) as batch_op:
        batch_op.alter_column('state',
               existing_type=sa.Enum('closed', 'allow-entry', 'running-lottery', 'completed', 'sign-up-list', native_enum=False),
               type_=sa.VARCHAR(length=23),
               existing_nullable=False)

    op.execute(sa.text("""update lottery set state = 'first-come-first-served' where state = 'sign-up-list' """))

