from collections.abc import Sequence

from alembic import op
from sqlalchemy import text as sa_text

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
    conn = op.get_bind()
    multi_account = conn.execute(
        sa_text(
            "SELECT COUNT(*) FROM ("
            " SELECT user_id, file_sha256 FROM import_batches"
            " GROUP BY user_id, file_sha256 HAVING COUNT(*) > 1"
            ") c"
        )
    ).scalar_one()
    if int(multi_account) > 0:
        raise RuntimeError(
            "cannot downgrade 0009: same file imported into multiple accounts;"
            " the previous uniqueness scope would be violated"
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batches_user_sha256"
        " ON import_batches (user_id, file_sha256)"
    )
    op.execute("DROP INDEX IF EXISTS uq_import_batches_user_account_sha256")
