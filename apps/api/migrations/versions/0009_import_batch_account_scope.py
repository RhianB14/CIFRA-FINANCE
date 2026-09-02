from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batches_user_account_sha256"
        " ON import_batches (user_id, account_id, file_sha256)"
    )
    op.execute("DROP INDEX IF EXISTS uq_import_batches_user_sha256")


def downgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batches_user_sha256"
        " ON import_batches (user_id, file_sha256)"
    )
    op.execute("DROP INDEX IF EXISTS uq_import_batches_user_account_sha256")
