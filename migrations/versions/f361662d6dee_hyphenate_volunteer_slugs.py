"""hyphenate-volunteer-slugs

Revision ID: f361662d6dee
Revises: b364bc3cac9e
Create Date: 2026-04-10 08:53:27.869230

"""

# revision identifiers, used by Alembic.
revision = "f361662d6dee"
down_revision = "b364bc3cac9e"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.execute(sa.text("UPDATE volunteer_role SET slug = REPLACE(slug, '_', '-')"))
    op.execute(sa.text("UPDATE volunteer_team SET slug = REPLACE(slug, '_', '-')"))
    op.execute(sa.text("UPDATE volunteer_venue SET slug = REPLACE(slug, '_', '-')"))


def downgrade():
    op.execute(sa.text("UPDATE volunteer_role SET slug = REPLACE(slug, '-', '_')"))
    op.execute(sa.text("UPDATE volunteer_team SET slug = REPLACE(slug, '-', '_')"))
    op.execute(sa.text("UPDATE volunteer_venue SET slug = REPLACE(slug, '-', '_')"))
