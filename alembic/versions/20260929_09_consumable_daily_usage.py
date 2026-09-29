"""track the last day a PER_DAY consumable was deducted"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_09"
down_revision = "20260929_08"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("consumables", sa.Column("usage_applied_on", sa.Date, nullable=True))

def downgrade() -> None:
    op.drop_column("consumables", "usage_applied_on")
