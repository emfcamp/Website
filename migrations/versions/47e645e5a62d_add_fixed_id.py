"""add fixed_id

Revision ID: 47e645e5a62d
Revises: b5a010ecbb8e
Create Date: 2016-05-25 19:33:28.769977

"""

# revision identifiers, used by Alembic.
revision = '47e645e5a62d'
down_revision = 'b5a010ecbb8e'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('ticket_type', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fixed_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(batch_op.f('uq_ticket_type_fixed_id'), ['fixed_id'])

    bind = op.get_bind()
    session = sa.orm.Session(bind=bind)

    from models import TicketType

    fixed_tts = session.query(TicketType).filter(TicketType.id <= 12)
    for tt in fixed_tts:
        tt.fixed_id = tt.id

    session.commit()


def downgrade():
    with op.batch_alter_table('ticket_type', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_ticket_type_fixed_id'), type_='unique')
        batch_op.drop_column('fixed_id')

