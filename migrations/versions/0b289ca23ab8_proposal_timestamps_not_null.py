"""proposal timestamps not null

Revision ID: 0b289ca23ab8
Revises: 0bf5b5d68a9e
Create Date: 2016-04-19 21:01:15.044807

"""

# revision identifiers, used by Alembic.
revision = '0b289ca23ab8'
down_revision = '0bf5b5d68a9e'

from alembic import op
import sqlalchemy as sa

def upgrade():
    with op.batch_alter_table('proposal', schema=None) as batch_op:
        batch_op.alter_column('created',
               nullable=False)
        batch_op.alter_column('modified',
               nullable=False)


def downgrade():
    with op.batch_alter_table('proposal', schema=None) as batch_op:
        batch_op.alter_column('modified',
               nullable=True)
        batch_op.alter_column('created',
               nullable=True)

