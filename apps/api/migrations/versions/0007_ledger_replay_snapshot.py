from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE transactions ADD COLUMN result_balance_after_cents BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE transactions ADD COLUMN result_balance_version BIGINT NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE transactions ALTER COLUMN result_balance_after_cents DROP DEFAULT")
    op.execute("ALTER TABLE transactions ALTER COLUMN result_balance_version DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS result_balance_version")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS result_balance_after_cents")
