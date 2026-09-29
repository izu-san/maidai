"""add household finance ledger"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260929_08"
down_revision = "20260929_07"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("finance_transactions", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("kind", sa.String(16), nullable=False), sa.Column("amount_yen", sa.Integer, nullable=False), sa.Column("category", sa.String(32), nullable=False), sa.Column("occurred_on", sa.Date, nullable=False), sa.Column("note", sa.String(200)), sa.Column("status", sa.String(16), nullable=False, server_default="active"), sa.Column("version", sa.Integer, nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.CheckConstraint("kind IN ('expense', 'income')", name="ck_finance_kind"), sa.CheckConstraint("amount_yen > 0", name="ck_finance_amount"), sa.CheckConstraint("status IN ('active', 'cancelled')", name="ck_finance_status"))
    op.create_index("ix_finance_transactions_date_category", "finance_transactions", ["occurred_on", "category"])
    op.create_table("finance_transaction_history", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("finance_transactions.id"), nullable=False), sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("life_events.id"), nullable=False, unique=True), sa.Column("before", postgresql.JSONB), sa.Column("after", postgresql.JSONB, nullable=False), sa.Column("reason", sa.String(160), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_finance_history_transaction", "finance_transaction_history", ["transaction_id", "created_at"])
def downgrade() -> None:
    op.drop_index("ix_finance_history_transaction", table_name="finance_transaction_history"); op.drop_table("finance_transaction_history")
    op.drop_index("ix_finance_transactions_date_category", table_name="finance_transactions"); op.drop_table("finance_transactions")
