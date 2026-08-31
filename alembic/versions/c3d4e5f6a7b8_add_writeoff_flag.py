"""add writeoff flag to categories and deduct_from_expenses to operations

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-08-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.add_column(
            sa.Column("is_writeoff", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("operations") as batch_op:
        batch_op.add_column(
            sa.Column("deduct_from_expenses", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("operations") as batch_op:
        batch_op.drop_column("deduct_from_expenses")
    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_column("is_writeoff")
