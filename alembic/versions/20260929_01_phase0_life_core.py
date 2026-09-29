"""create phase 0 life core tables"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_01"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("life_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("type", sa.String(160), nullable=False), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("source", sa.String(64), nullable=False), sa.Column("actor", sa.String(128)), sa.Column("confidence", sa.Numeric(3, 2)), sa.Column("correlation_id", sa.String(128)), sa.Column("causation_id", postgresql.UUID(as_uuid=True)), sa.Column("payload", postgresql.JSONB, nullable=False), sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_life_events_confidence"))
    op.create_index("ix_life_events_type_occurred_at", "life_events", ["type", "occurred_at"])
    op.create_index("ix_life_events_correlation_id", "life_events", ["correlation_id"])
    op.create_table("outbox_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("subject", sa.String(160), nullable=False), sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"), sa.Column("payload", postgresql.JSONB, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("attempts", sa.Integer, nullable=False, server_default="0"), sa.Column("last_error", sa.Text()), sa.CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts"))
    op.create_index("ix_outbox_events_unpublished", "outbox_events", ["created_at"], postgresql_where=sa.text("published_at IS NULL"))
    op.create_table("processed_events", sa.Column("consumer_name", sa.String(128), nullable=False), sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.PrimaryKeyConstraint("consumer_name", "event_id", name="pk_processed_events"))

def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_life_events_correlation_id", table_name="life_events")
    op.drop_index("ix_life_events_type_occurred_at", table_name="life_events")
    op.drop_table("life_events")
