from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE attachments (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          file_name VARCHAR(255) NOT NULL,
          content_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
          size_bytes BIGINT NOT NULL,
          object_key VARCHAR(512) NOT NULL,
          bucket VARCHAR(255) NOT NULL,
          etag VARCHAR(255) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_attachments_size_non_negative CHECK (size_bytes >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_attachments_account_id ON attachments (account_id)")
    op.execute("ALTER TABLE attachments ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY attachments_isolation ON attachments
          USING (user_id = current_setting('app.current_user_id', true)::uuid)
          WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS attachments_isolation ON attachments")
    op.execute("ALTER TABLE attachments DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS attachments")
