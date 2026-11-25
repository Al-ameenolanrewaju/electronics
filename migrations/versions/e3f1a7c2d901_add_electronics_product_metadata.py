"""add electronics condition and warranty metadata

Revision ID: e3f1a7c2d901
Revises: a2c6e71f9530
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f1a7c2d901"
down_revision = "a2c6e71f9530"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(sa.Column("condition", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("warranty_info", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_column("warranty_info")
        batch_op.drop_column("condition")
