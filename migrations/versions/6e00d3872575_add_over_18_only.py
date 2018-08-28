"""Add over_18_only

Revision ID: 6e00d3872575
Revises: 7f42f7d8c3f5
Create Date: 2018-08-28 12:41:27.075904

"""

# revision identifiers, used by Alembic.
revision = '6e00d3872575'
down_revision = '7f42f7d8c3f5'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import expression


def upgrade():
    op.add_column('volunteer_role', sa.Column('over_18_only', sa.Boolean(), nullable=False, server_default=expression.false()))


def downgrade():
    op.drop_column('volunteer_role', 'over_18_only')
