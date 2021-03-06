"""Add ticket_issued payment flag

Revision ID: 17032733727a
Revises: 3c6cca2d97e3
Create Date: 2019-11-05 16:07:14.444915

"""

# revision identifiers, used by Alembic.
revision = '17032733727a'
down_revision = '3c6cca2d97e3'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('purchase', sa.Column('ticket_issued', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('purchase_version', sa.Column('ticket_issued', sa.Boolean(), autoincrement=False, nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('purchase_version', 'ticket_issued')
    op.drop_column('purchase', 'ticket_issued')
    # ### end Alembic commands ###
