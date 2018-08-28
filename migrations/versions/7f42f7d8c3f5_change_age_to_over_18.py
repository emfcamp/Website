"""Change age to over_18

Revision ID: 7f42f7d8c3f5
Revises: 656fd816bee7
Create Date: 2018-08-28 00:43:00.739669

"""

# revision identifiers, used by Alembic.
revision = '7f42f7d8c3f5'
down_revision = '656fd816bee7'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import expression, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy_continuum import version_class

from main import db

Base = declarative_base()

class Volunteer(Base):
    __tablename__ = 'volunteer'
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    age = db.Column(db.Integer, nullable=False)
    over_18 = db.Column(db.Boolean, nullable=False, default=False)


def upgrade():
    op.add_column('volunteer', sa.Column('over_18', sa.Boolean(), nullable=False, server_default=expression.false()))
    op.add_column('volunteer_version', sa.Column('over_18', sa.Boolean(), autoincrement=False, nullable=True))

    bind = op.get_bind()
    session = sa.orm.Session(bind=bind)

    for volunteer in session.query(Volunteer):
        volunteer.over_18 = (volunteer.age >= 18)

    # include deleted records
    for version in session.query(version_class(Volunteer)):
        version.over_18 = (version.age >= 18)

    session.commit()

    op.drop_column('volunteer', 'age')
    op.drop_column('volunteer_version', 'age')


def downgrade():
    op.add_column('volunteer_version', sa.Column('age', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('volunteer', sa.Column('age', sa.INTEGER(), autoincrement=False, nullable=False, server_default=text('0')))

    # No clean downgrade, as we want to get rid of the data
    bind = op.get_bind()
    session = sa.orm.Session(bind=bind)

    for volunteer in session.query(Volunteer):
        volunteer.age = 18 if volunteer.over_18 else 17

    # include deleted records
    for version in session.query(version_class(Volunteer)):
        version.age = 18 if version.over_18 else 17

    session.commit()

    op.drop_column('volunteer_version', 'over_18')
    op.drop_column('volunteer', 'over_18')

