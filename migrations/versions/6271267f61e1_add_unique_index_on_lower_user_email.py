"""Add unique index on lower(User.email)

Revision ID: 6271267f61e1
Revises: 7eeac22cd351
Create Date: 2018-08-13 14:05:42.512566

"""

# revision identifiers, used by Alembic.
revision = '6271267f61e1'
down_revision = '7eeac22cd351'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_index('ix_user_email_lower', 'user', [sa.text('lower(email)')], unique=True)


def downgrade():
    op.drop_index('ix_user_email_lower', table_name='user')
