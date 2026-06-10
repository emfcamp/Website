"""youthworkshop to familyworkshop

Revision ID: ff096360d712
Revises: 3b07c4eea8ea
Create Date: 2026-06-09 23:56:07.598766

"""

# revision identifiers, used by Alembic.
revision = 'ff096360d712'
down_revision = '3b07c4eea8ea'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('schedule_item', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(length=13),
               type_=sa.VARCHAR(),
               existing_nullable=False)

    with op.batch_alter_table('schedule_item_version', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(length=13),
               type_=sa.VARCHAR(),
               existing_nullable=True,
               autoincrement=False)

    with op.batch_alter_table('time_block', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(length=13),
               type_=sa.VARCHAR(),
               existing_nullable=False)

    op.execute(sa.text("""update proposal set type = 'familyworkshop' where type = 'youthworkshop'"""))
    op.execute(sa.text("""update proposal_version set type = 'familyworkshop' where type = 'youthworkshop'"""))

    op.execute(sa.text("""update schedule_item set type = 'familyworkshop' where type = 'youthworkshop'"""))
    op.execute(sa.text("""update schedule_item_version set type = 'familyworkshop' where type = 'youthworkshop'"""))

    op.execute(sa.text("""update time_block set type = 'familyworkshop' where type = 'youthworkshop'"""))

    op.execute(sa.text("""update feature_flag set feature = 'CFP_FAMILYWORKSHOPS_CLOSED' where feature = 'CFP_YOUTHWORKSHOPS_CLOSED'"""))
    op.execute(sa.text("""update feature_flag_version set feature = 'CFP_FAMILYWORKSHOPS_CLOSED' where feature = 'CFP_YOUTHWORKSHOPS_CLOSED'"""))



def downgrade():
    op.execute(sa.text("""update proposal set type = 'youthworkshop' where type = 'familyworkshop'"""))
    op.execute(sa.text("""update proposal_version set type = 'youthworkshop' where type = 'familyworkshop'"""))

    op.execute(sa.text("""update schedule_item set type = 'youthworkshop' where type = 'familyworkshop'"""))
    op.execute(sa.text("""update schedule_item_version set type = 'youthworkshop' where type = 'familyworkshop'"""))

    op.execute(sa.text("""update time_block set type = 'youthworkshop' where type = 'familyworkshop'"""))

    op.execute(sa.text("""update feature_flag set feature = 'CFP_YOUTHWORKSHOPS_CLOSED' where feature = 'CFP_FAMILYWORKSHOPS_CLOSED'"""))
    op.execute(sa.text("""update feature_flag_version set feature = 'CFP_YOUTHWORKSHOPS_CLOSED' where feature = 'CFP_FAMILYWORKSHOPS_CLOSED'"""))

    with op.batch_alter_table('time_block', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(),
               type_=sa.VARCHAR(length=13),
               existing_nullable=False)

    with op.batch_alter_table('schedule_item_version', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(),
               type_=sa.VARCHAR(length=13),
               existing_nullable=True,
               autoincrement=False)

    with op.batch_alter_table('schedule_item', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(),
               type_=sa.VARCHAR(length=13),
               existing_nullable=False)

