"""Add tags to cfp reviewers

Revision ID: 214878041f05
Revises: fe4331fac361
Create Date: 2024-02-09 18:39:33.235916

"""

# revision identifiers, used by Alembic.
revision = "214878041f05"
down_revision = "fe4331fac361"

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "cfp_reviewer_tags_version",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("tag_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "transaction_id", sa.BigInteger(), autoincrement=False, nullable=False
        ),
        sa.Column("operation_type", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id",
            "tag_id",
            "transaction_id",
            name=op.f("pk_cfp_reviewer_tags_version"),
        ),
    )
    op.create_index(
        op.f("ix_cfp_reviewer_tags_version_operation_type"),
        "cfp_reviewer_tags_version",
        ["operation_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cfp_reviewer_tags_version_transaction_id"),
        "cfp_reviewer_tags_version",
        ["transaction_id"],
        unique=False,
    )
    op.create_table(
        "cfp_reviewer_tags",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tag.id"], name=op.f("fk_cfp_reviewer_tags_tag_id_tag")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_cfp_reviewer_tags_user_id_user")
        ),
        sa.PrimaryKeyConstraint("user_id", "tag_id", name=op.f("pk_cfp_reviewer_tags")),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("cfp_reviewer_tags")
    op.drop_index(
        op.f("ix_cfp_reviewer_tags_version_transaction_id"),
        table_name="cfp_reviewer_tags_version",
    )
    op.drop_index(
        op.f("ix_cfp_reviewer_tags_version_operation_type"),
        table_name="cfp_reviewer_tags_version",
    )
    op.drop_table("cfp_reviewer_tags_version")
    # ### end Alembic commands ###
