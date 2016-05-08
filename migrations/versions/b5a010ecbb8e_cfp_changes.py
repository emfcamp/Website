"""CfP changes

Revision ID: b5a010ecbb8e
Revises: 0b289ca23ab8
Create Date: 2016-05-08 14:55:35.687016

"""

# revision identifiers, used by Alembic.
revision = 'b5a010ecbb8e'
down_revision = '0b289ca23ab8'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('cfp_vote', schema=None) as batch_op:
        batch_op.alter_column('created',
               existing_type=sa.DATETIME(),
               nullable=False)
        batch_op.alter_column('has_been_read',
               existing_type=sa.BOOLEAN(),
               nullable=False)
        batch_op.alter_column('modified',
               existing_type=sa.DATETIME(),
               nullable=False)
        batch_op.create_index('ix_cfp_vote_user_id_proposal_id', ['user_id', 'proposal_id'], unique=True)

    with op.batch_alter_table('proposal', schema=None) as batch_op:
        batch_op.alter_column('has_rejected_email',
               existing_type=sa.BOOLEAN(),
               nullable=False)
        batch_op.alter_column('needs_money',
               existing_type=sa.BOOLEAN(),
               nullable=False)
        batch_op.alter_column('one_day',
               existing_type=sa.BOOLEAN(),
               nullable=False)
        batch_op.drop_constraint(u'fk_proposal_category_id_category', type_='foreignkey')
        batch_op.drop_column('category_id')

    with op.batch_alter_table('proposal_version', schema=None) as batch_op:
        batch_op.drop_column('category_id')

    op.drop_table('category_reviewers')
    op.drop_table('category')


def downgrade():
    op.create_table('category',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('name', sa.VARCHAR(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('category_reviewers',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('user_id', sa.INTEGER(), nullable=False),
    sa.Column('category_id', sa.INTEGER(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], [u'category.id'], name=u'fk_category_reviewers_category_id_category'),
    sa.ForeignKeyConstraint(['user_id'], [u'user.id'], name=u'fk_category_reviewers_user_id_user'),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('proposal_version', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.INTEGER(), nullable=True))

    with op.batch_alter_table('proposal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.INTEGER(), nullable=True))
        batch_op.create_foreign_key(u'fk_proposal_category_id_category', 'category', ['category_id'], ['id'])
        batch_op.alter_column('one_day',
               existing_type=sa.BOOLEAN(),
               nullable=True)
        batch_op.alter_column('needs_money',
               existing_type=sa.BOOLEAN(),
               nullable=True)
        batch_op.alter_column('has_rejected_email',
               existing_type=sa.BOOLEAN(),
               nullable=True)

    with op.batch_alter_table('cfp_vote', schema=None) as batch_op:
        batch_op.drop_index('ix_cfp_vote_user_id_proposal_id')
        batch_op.alter_column('modified',
               existing_type=sa.DATETIME(),
               nullable=True)
        batch_op.alter_column('has_been_read',
               existing_type=sa.BOOLEAN(),
               nullable=True)
        batch_op.alter_column('created',
               existing_type=sa.DATETIME(),
               nullable=True)
