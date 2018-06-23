"""Add user table full-text indexes

Revision ID: b63d697994ef
Revises: eb8d9b6aef7c
Create Date: 2018-06-21 22:08:27.860648

"""

# revision identifiers, used by Alembic.
revision = 'b63d697994ef'
down_revision = 'eb8d9b6aef7c'

from alembic import op
import sqlalchemy as sa
from sqlalchemy import func


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_user_email_tsearch'), [sa.text("to_tsvector('simple', replace(email, '@', ' '))")], unique=False, postgresql_using='gin')
            batch_op.create_index(batch_op.f('ix_user_name_tsearch'), [sa.text("to_tsvector('simple', name)")], unique=False, postgresql_using='gin')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_email_tsearch'))
        batch_op.drop_index(batch_op.f('ix_user_name_tsearch'))
