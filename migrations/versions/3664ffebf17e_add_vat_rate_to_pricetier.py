"""Add VAT rate to pricetier

Revision ID: 3664ffebf17e
Revises: 214878041f05
Create Date: 2024-04-21 22:42:15.193592

"""

# revision identifiers, used by Alembic.
revision = '3664ffebf17e'
down_revision = '214878041f05'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('price_tier', sa.Column('vat_rate', sa.Numeric(precision=4, scale=3), nullable=True))
    op.execute('update price_tier set vat_rate = 0.2')

def downgrade():
    op.drop_column('price_tier', 'vat_rate')

