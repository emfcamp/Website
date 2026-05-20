"""Add EmailJob.type, etc

Revision ID: 21562f36309d
Revises: a1fe3b750f1e
Create Date: 2026-05-16 14:35:46.544884

"""

# revision identifiers, used by Alembic.
revision = '21562f36309d'
down_revision = 'a1fe3b750f1e'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    op.drop_table('volunteer_notify_recipient')
    op.drop_table('volunteer_notify_job')
    with op.batch_alter_table('email_job', schema=None) as batch_op:
        batch_op.add_column(sa.Column('type', sa.Enum('bulk_contact', 'cfp', 'cfp_speakers', 'notify_volunteer', native_enum=False), server_default='bulk_contact', nullable=False))
        batch_op.alter_column('html_body',
               existing_type=sa.VARCHAR(),
               nullable=True)

    with op.batch_alter_table('email_recipient', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sent_at', sa.TIMESTAMP(), nullable=True))
        batch_op.create_index(batch_op.f('ix_email_recipient_sent_at'), ['sent_at'], unique=False)

    with op.batch_alter_table('volunteer', schema=None) as batch_op:
        batch_op.alter_column('volunteer_email',
               existing_type=sa.VARCHAR(),
               nullable=False)

    # ### end Alembic commands ###


def downgrade():
    with op.batch_alter_table('volunteer', schema=None) as batch_op:
        batch_op.alter_column('volunteer_email',
               existing_type=sa.VARCHAR(),
               nullable=True)

    with op.batch_alter_table('email_recipient', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_recipient_sent_at'))
        batch_op.drop_column('sent_at')

    with op.batch_alter_table('email_job', schema=None) as batch_op:
        batch_op.alter_column('html_body',
               existing_type=sa.VARCHAR(),
               nullable=False)
        batch_op.drop_column('type')

    op.create_table('volunteer_notify_job',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('subject', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('text_body', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('html_body', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('created', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_volunteer_notify_job'))
    )
    op.create_table('volunteer_notify_recipient',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('volunteer_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('job_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('sent', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['volunteer_notify_job.id'], name=op.f('fk_volunteer_notify_recipient_job_id_volunteer_notify_job')),
    sa.ForeignKeyConstraint(['volunteer_id'], ['volunteer.id'], name=op.f('fk_volunteer_notify_recipient_volunteer_id_volunteer')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_volunteer_notify_recipient'))
    )
    # ### end Alembic commands ###
