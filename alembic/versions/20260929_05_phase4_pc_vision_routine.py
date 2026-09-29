"""add PC, Vision candidate, and routine read models"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_05"
down_revision = "20260929_04"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Device events are not life_events, but notification audit must retain their IDs.
    op.drop_constraint("notification_history_event_id_fkey", "notification_history", type_="foreignkey")
    op.create_table("pc_state", sa.Column("device_id", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("storage_free_bytes", sa.BigInteger), sa.Column("storage_total_bytes", sa.BigInteger),
        sa.Column("last_error", postgresql.JSONB), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("pc_history", sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", sa.String(128), nullable=False), sa.Column("type", sa.String(160), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_pc_history_device_observed", "pc_history", ["device_id", "observed_at"])
    op.create_table("vision_candidates", sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("observation_type", sa.String(128), nullable=False), sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("confirmation_required", sa.Boolean, nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB, nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_vision_candidates_status", "vision_candidates", ["status", "observed_at"])
    op.create_table("routine_stats", sa.Column("routine_date", sa.Date, primary_key=True), sa.Column("event_type", sa.String(160), primary_key=True),
        sa.Column("event_count", sa.Integer, nullable=False), sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))

def downgrade() -> None:
    op.drop_table("routine_stats")
    op.drop_index("ix_vision_candidates_status", table_name="vision_candidates")
    op.drop_table("vision_candidates")
    op.drop_index("ix_pc_history_device_observed", table_name="pc_history")
    op.drop_table("pc_history")
    op.drop_table("pc_state")
    op.create_foreign_key("notification_history_event_id_fkey", "notification_history", "life_events", ["event_id"], ["id"])
