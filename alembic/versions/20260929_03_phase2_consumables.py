"""add Phase 2 consumable snapshots, history, and notification history"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_03"
down_revision = "20260929_02"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("consumables",
        sa.Column("id", sa.String(128), primary_key=True), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False), sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("capacity", sa.Numeric(12, 3), nullable=False), sa.Column("remaining", sa.Numeric(12, 3), nullable=False),
        sa.Column("stock_unopened", sa.Integer, nullable=False, server_default="0"), sa.Column("estimated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("usage_model", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("reminder", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("capacity > 0", name="ck_consumables_capacity"), sa.CheckConstraint("remaining >= 0 AND remaining <= capacity", name="ck_consumables_remaining"), sa.CheckConstraint("stock_unopened >= 0", name="ck_consumables_stock"))
    op.create_table("consumable_history", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("consumable_id", sa.String(128), sa.ForeignKey("consumables.id"), nullable=False), sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("life_events.id"), nullable=False), sa.Column("before", postgresql.JSONB, nullable=False), sa.Column("after", postgresql.JSONB, nullable=False), sa.Column("reason", sa.String(160), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("consumable_id", "event_id", name="uq_consumable_history_item_event"))
    op.create_index("ix_consumable_history_item_created", "consumable_history", ["consumable_id", "created_at"])
    op.create_table("notification_history", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("dedupe_key", sa.String(256), nullable=False, unique=True), sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("life_events.id")), sa.Column("priority", sa.SmallInteger, nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("acknowledged_at", sa.DateTime(timezone=True)), sa.Column("resolved_at", sa.DateTime(timezone=True)), sa.CheckConstraint("priority >= 0 AND priority <= 4", name="ck_notification_priority"))

def downgrade() -> None:
    op.drop_table("notification_history")
    op.drop_index("ix_consumable_history_item_created", table_name="consumable_history")
    op.drop_table("consumable_history")
    op.drop_table("consumables")
