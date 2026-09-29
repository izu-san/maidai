"""add Phase 5 maintenance, waste, delivery, and subscription state"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_06"
down_revision = "20260929_05"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("maintenance_items",
        sa.Column("id", sa.String(128), primary_key=True), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("interval_days", sa.Integer, nullable=False), sa.Column("last_completed_at", sa.DateTime(timezone=True)),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("interval_days > 0", name="ck_maintenance_interval_days"))
    op.create_table("maintenance_history", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("maintenance_id", sa.String(128), sa.ForeignKey("maintenance_items.id"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("life_events.id"), nullable=False, unique=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("notes", sa.Text))
    op.create_table("trash_schedules", sa.Column("id", sa.String(128), primary_key=True), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Tokyo"), sa.Column("schedule", postgresql.JSONB, nullable=False),
        sa.Column("next_collection_at", sa.DateTime(timezone=True)), sa.Column("last_collected_at", sa.DateTime(timezone=True)), sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()))
    op.create_table("deliveries", sa.Column("id", sa.String(128), primary_key=True), sa.Column("carrier", sa.String(128)), sa.Column("tracking_ref", sa.String(256)),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("expected_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_table("subscriptions", sa.Column("id", sa.String(128), primary_key=True), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"), sa.Column("renewal_at", sa.DateTime(timezone=True)),
        sa.Column("amount", sa.Numeric(12, 2)), sa.Column("currency", sa.String(8)), sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))

def downgrade() -> None:
    op.drop_table("subscriptions"); op.drop_table("deliveries"); op.drop_table("trash_schedules")
    op.drop_table("maintenance_history"); op.drop_table("maintenance_items")
