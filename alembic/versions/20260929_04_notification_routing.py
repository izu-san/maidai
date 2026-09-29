"""add notification routing decision audit fields"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_04"
down_revision = "20260929_03"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("notification_history", sa.Column("cooldown_until", sa.DateTime(timezone=True)))
    op.add_column("notification_history", sa.Column("candidate_count", sa.Integer, nullable=False, server_default="1"))
    op.add_column("notification_history", sa.Column("last_event_at", sa.DateTime(timezone=True)))
    op.add_column("notification_history", sa.Column("reason", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_index("ix_notification_history_status", "notification_history", ["status", "cooldown_until"])

def downgrade() -> None:
    op.drop_index("ix_notification_history_status", table_name="notification_history")
    op.drop_column("notification_history", "reason")
    op.drop_column("notification_history", "last_event_at")
    op.drop_column("notification_history", "candidate_count")
    op.drop_column("notification_history", "cooldown_until")
