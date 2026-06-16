"""Remove server_default

Revision ID: 143a1d89b2a2
Revises: bcf21daa6073
Create Date: 2025-08-26 01:55:29.088170

"""

# revision identifiers, used by Alembic.
revision = '143a1d89b2a2'
down_revision = 'bcf21daa6073'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('product_view', schema=None) as batch_op:
        batch_op.alter_column('vouchers_only', server_default=None)

    with op.batch_alter_table('refund_request', schema=None) as batch_op:
        batch_op.alter_column('donation', server_default=None)

    with op.batch_alter_table('venue', schema=None) as batch_op:
        batch_op.alter_column('default_for_types', server_default=None)
        batch_op.alter_column('allowed_types', server_default=None)

    with op.batch_alter_table('voucher', schema=None) as batch_op:
        batch_op.alter_column('tickets_remaining', server_default=None)
        batch_op.alter_column('purchases_remaining', server_default=None)


def downgrade():
    with op.batch_alter_table('voucher', schema=None) as batch_op:
        batch_op.alter_column('purchases_remaining', server_default=sa.text('1'))
        batch_op.alter_column('tickets_remaining', server_default=sa.text('2'))

    with op.batch_alter_table('venue', schema=None) as batch_op:
        batch_op.alter_column('allowed_types', server_default=sa.text("'{}'::character varying[]"))
        batch_op.alter_column('default_for_types', server_default=sa.text("'{}'::character varying[]"))

    with op.batch_alter_table('refund_request', schema=None) as batch_op:
        batch_op.alter_column('donation', server_default=sa.text("'0'::numeric"))

    with op.batch_alter_table('product_view', schema=None) as batch_op:
        batch_op.alter_column('vouchers_only', server_default=sa.text('false'))

