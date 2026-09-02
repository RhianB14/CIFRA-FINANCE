from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_transactions_reversal_of_id"
        " ON transactions (reversal_of_id) WHERE reversal_of_id IS NOT NULL"
    )
    op.execute("REVOKE DELETE ON transactions FROM cifra_app")


def downgrade() -> None:
    op.execute("GRANT DELETE ON transactions TO cifra_app")
    op.execute("DROP INDEX IF EXISTS uq_transactions_reversal_of_id")
