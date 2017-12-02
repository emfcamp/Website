"""add check constraints

Revision ID: 2f73f2095e58
Revises: 0d10c234333d
Create Date: 2017-12-02 17:02:32.826619

"""

# revision identifiers, used by Alembic.
revision = '2f73f2095e58'
down_revision = '0d10c234333d'

from alembic import op
import sqlalchemy as sa
from models.mixins import CapacityMixin, CAPACITY_CONSTRAINT_SQL, CAPACITY_CONSTRAINT_NAME
from models.purchase import (Purchase, ANON_OWNER_SQL, ANON_OWNER_NAME,
                             ANON_PURCHASER_SQL, ANON_PURCHASER_NAME)


def upgrade():
    op.create_check_constraint(ANON_OWNER_NAME,
                               Purchase.__tablename__,
                               ANON_OWNER_SQL)
    op.create_check_constraint(ANON_PURCHASER_NAME,
                               Purchase.__tablename__,
                               ANON_PURCHASER_SQL)
    for table_class in CapacityMixin.__subclasses__():
        op.create_check_constraint(CAPACITY_CONSTRAINT_NAME,
                                   table_class.__tablename__,
                                   CAPACITY_CONSTRAINT_SQL)

def downgrade():
    op.drop_constraint(ANON_OWNER_NAME, Purchase.__tablename__, "check")
    op.drop_constraint(ANON_PURCHASER_NAME, Purchase.__tablename__, "check")
    for table_class in CapacityMixin.__subclasses__():
        op.drop_constraint(CAPACITY_CONSTRAINT_NAME,
                           table_class.__tablename__,
                           "check")
