"""Make redeemed column not null

Revision ID: 56f4836885de
Revises: 95c452965b74
Create Date: 2024-05-18 11:08:35.757045

"""

# revision identifiers, used by Alembic.
revision = "56f4836885de"
down_revision = "95c452965b74"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.execute("UPDATE purchase SET redeemed = false WHERE redeemed IS NULL")
    op.alter_column("purchase", "redeemed", existing_type=sa.BOOLEAN(), nullable=False)


def downgrade():
    op.alter_column("purchase", "redeemed", existing_type=sa.BOOLEAN(), nullable=True)
