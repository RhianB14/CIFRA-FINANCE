from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE attachments FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS attachments_isolation ON attachments")
    op.execute(
        """
        CREATE POLICY attachments_isolation ON attachments
          USING (
            user_id = current_setting('app.current_user_id', true)::uuid
            OR current_setting('app.auth_scope', true) = 'bypass'
          )
          WITH CHECK (
            user_id = current_setting('app.current_user_id', true)::uuid
            OR current_setting('app.auth_scope', true) = 'bypass'
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS attachments_isolation ON attachments")
    op.execute(
        """
        CREATE POLICY attachments_isolation ON attachments
          USING (user_id = current_setting('app.current_user_id', true)::uuid)
          WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )
    op.execute("ALTER TABLE attachments NO FORCE ROW LEVEL SECURITY")
