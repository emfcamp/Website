"""version volunteer tables

Revision ID: 9dd45df03fb4
Revises: 27869a0709f9
Create Date: 2026-06-20 16:23:25.362255

"""

# revision identifiers, used by Alembic.
revision = "9dd45df03fb4"
down_revision = "27869a0709f9"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.create_table(
        "volunteer_shift_template_version",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("role_id", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("venue_id", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("event_day", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("start_time", sa.Time(), autoincrement=False, nullable=True),
        sa.Column("end_time", sa.Time(), autoincrement=False, nullable=True),
        sa.Column("duration", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("changeover_time", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("min_needed", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("max_needed", sa.Integer(), autoincrement=False, nullable=True),
        sa.Column("notes", sa.String(), autoincrement=False, nullable=True),
        sa.Column("transaction_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("operation_type", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", "transaction_id", name=op.f("pk_volunteer_shift_template_version")),
    )
    with op.batch_alter_table("volunteer_shift_template_version", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_volunteer_shift_template_version_operation_type"), ["operation_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_volunteer_shift_template_version_transaction_id"), ["transaction_id"], unique=False
        )

    op.create_table(
        "volunteer_team_version",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(), autoincrement=False, nullable=True),
        sa.Column("slug", sa.String(), autoincrement=False, nullable=True),
        sa.Column("transaction_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("operation_type", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", "transaction_id", name=op.f("pk_volunteer_team_version")),
    )
    with op.batch_alter_table("volunteer_team_version", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_volunteer_team_version_operation_type"), ["operation_type"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_volunteer_team_version_slug"), ["slug"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_volunteer_team_version_transaction_id"), ["transaction_id"], unique=False
        )


def downgrade():
    with op.batch_alter_table("volunteer_team_version", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_volunteer_team_version_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_volunteer_team_version_slug"))
        batch_op.drop_index(batch_op.f("ix_volunteer_team_version_operation_type"))

    op.drop_table("volunteer_team_version")
    with op.batch_alter_table("volunteer_shift_template_version", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_volunteer_shift_template_version_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_volunteer_shift_template_version_operation_type"))

    op.drop_table("volunteer_shift_template_version")
