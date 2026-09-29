"""persist idempotent SwitchBot environmental observations"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_02"
down_revision = "20260929_01"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("environment_state", sa.Column("device_id", sa.String(128), primary_key=True), sa.Column("temperature_c", sa.Numeric(5, 2)), sa.Column("humidity_percent", sa.Numeric(5, 2)), sa.Column("co2_ppm", sa.Integer), sa.Column("device_state", postgresql.JSONB), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("environment_history", sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("device_id", sa.String(128), nullable=False), sa.Column("type", sa.String(160), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("payload", postgresql.JSONB, nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_environment_history_device_observed", "environment_history", ["device_id", "observed_at"])

def downgrade() -> None:
    op.drop_index("ix_environment_history_device_observed", table_name="environment_history")
    op.drop_table("environment_history")
    op.drop_table("environment_state")
