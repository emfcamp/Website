"""add_user_notification_preferences

Revision ID: 1418c5eca608
Revises: ee286bc4206a
Create Date: 2024-04-15 12:54:53.073931

"""

# revision identifiers, used by Alembic.
revision = "1418c5eca608"
down_revision = "ee286bc4206a"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "user_notification_preference",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("volunteer_shifts", sa.Boolean(), nullable=False),
        sa.Column("favourited_content", sa.Boolean(), nullable=False),
        sa.Column("announcements", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_notification_preference")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_user_notification_preference_user"
        ),
    )


def downgrade():
    op.drop_table("user_notification_preference")
