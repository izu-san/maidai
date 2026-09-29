"""make the consumable catalogue safely manageable at runtime"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_07"
down_revision = "20260929_06"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("consumables", sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()))
    op.create_index("ix_consumables_active", "consumables", ["active"])

def downgrade() -> None:
    op.drop_index("ix_consumables_active", table_name="consumables")
    op.drop_column("consumables", "active")
