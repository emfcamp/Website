"""

Revision ID: e303484d5984
Revises: 7aa0e3890262
Create Date: 2016-07-03 19:40:56.898476

"""

# revision identifiers, used by Alembic.
revision = 'e303484d5984'
down_revision = '7aa0e3890262'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('email_job',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject', sa.String(), nullable=False),
    sa.Column('text_body', sa.String(), nullable=False),
    sa.Column('html_body', sa.String(), nullable=False),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_job'))
    )
    op.create_table('email_recipient',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('sent', sa.Boolean(), nullable=True, server_default=sa.false()),
    sa.ForeignKeyConstraint(['job_id'], ['email_job.id'], name=op.f('fk_email_recipient_job_id_email_job')),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_email_recipient_user_id_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_recipient'))
    )


def downgrade():
    op.drop_table('email_recipient')
    op.drop_table('email_job')
