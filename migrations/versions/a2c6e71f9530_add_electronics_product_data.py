"""add electronics product brand and specifications

Revision ID: a2c6e71f9530
Revises: 4b72c9a81d30
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa


revision = "a2c6e71f9530"
down_revision = "4b72c9a81d30"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(sa.Column("brand", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("specifications", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_column("specifications")
        batch_op.drop_column("brand")
