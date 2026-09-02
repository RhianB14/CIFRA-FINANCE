from collections.abc import Sequence

from alembic import op
from sqlalchemy import text as sa_text

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_operation_allowed")
    op.execute(
        "ALTER TABLE transactions ADD CONSTRAINT transactions_operation_allowed"
        " CHECK (operation_type IN ('deposit', 'withdrawal', 'reversal',"
        " 'transfer_in', 'transfer_out'))"
    )
    op.execute("ALTER TABLE transactions ADD COLUMN transfer_group_id UUID")
    op.execute("CREATE INDEX ix_transactions_transfer_group_id ON transactions (transfer_group_id)")


def downgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa_text(
            "SELECT COUNT(*) FROM transactions"
            " WHERE operation_type IN ('transfer_in', 'transfer_out')"
        )
    ).scalar_one()
    if existing > 0:
        raise RuntimeError(
            "cannot downgrade 0005: transfer rows present;"
            " remove transfer_in/transfer_out rows before downgrading"
        )
    op.execute("DROP INDEX IF EXISTS ix_transactions_transfer_group_id")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS transfer_group_id")
    op.execute("ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_operation_allowed")
    op.execute(
        "ALTER TABLE transactions ADD CONSTRAINT transactions_operation_allowed"
        " CHECK (operation_type IN ('deposit', 'withdrawal', 'reversal'))"
    )
