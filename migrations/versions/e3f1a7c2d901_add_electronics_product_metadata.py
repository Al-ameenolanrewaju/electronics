"""add electronics-specific product metadata

Revision ID: e3f1a7c2d901
Revises: 4b72c9a81d30
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f1a7c2d901"
down_revision = "4b72c9a81d30"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(sa.Column("brand", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("condition", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("warranty_info", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("specifications", sa.JSON(), nullable=True))
        batch_op.create_index("ix_product_brand", ["brand"], unique=False)


def downgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_index("ix_product_brand")
        batch_op.drop_column("specifications")
        batch_op.drop_column("warranty_info")
        batch_op.drop_column("condition")
        batch_op.drop_column("brand")
