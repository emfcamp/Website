"""create_webpush_target

Revision ID: ee286bc4206a
Revises: 214878041f05
Create Date: 2024-03-25 12:52:56.462206

"""

# revision identifiers, used by Alembic.
revision = "ee286bc4206a"
down_revision = "214878041f05"

from datetime import datetime

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "web_push_target",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=True),
        sa.Column("subscription_info", sa.JSON(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False, default=datetime.utcnow),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_web_push_target_mapping_user_id_user_id"),
        ),
    )
    op.create_index(op.f("ix_web_push_target_user_id"), "web_push_target", ["user_id"])
    op.create_index(
        op.f("ix_web_push_target_user_id_endpoint"),
        "web_push_target",
        ["user_id", "endpoint"],
    )


def downgrade():
    op.drop_index("ix_web_push_target_user_id")
    op.drop_index("ix_web_push_target_user_id_endpoint")
    op.drop_table("web_push_target")
