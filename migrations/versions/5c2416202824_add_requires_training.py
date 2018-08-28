"""Add requires_training

Revision ID: 5c2416202824
Revises: 6e00d3872575
Create Date: 2018-08-28 14:19:02.528289

"""

# revision identifiers, used by Alembic.
revision = '5c2416202824'
down_revision = '6e00d3872575'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import expression


def upgrade():
    op.add_column('volunteer_role', sa.Column('requires_training', sa.Boolean(), nullable=False, server_default=expression.false()))


def downgrade():
    op.drop_column('volunteer_role', 'requires_training')
