from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE recurring_transactions (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          template_operation_type VARCHAR(32) NOT NULL,
          template_amount_cents BIGINT NOT NULL,
          template_description VARCHAR(500),
          recurrence VARCHAR(10) NOT NULL,
          starts_on DATE NOT NULL,
          ends_on DATE,
          next_run_on DATE NOT NULL,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT recurring_operations_allowed CHECK (
            template_operation_type IN ('deposit', 'withdrawal')
          ),
          CONSTRAINT recurring_amount_positive CHECK (template_amount_cents > 0),
          CONSTRAINT recurring_cadence_allowed CHECK (
            recurrence IN ('daily', 'weekly', 'monthly', 'yearly')
          ),
          CONSTRAINT recurring_dates_sane CHECK (
            ends_on IS NULL OR ends_on >= starts_on
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_recurring_user_next_run ON recurring_transactions (user_id, next_run_on)"
    )
    op.execute("CREATE INDEX ix_recurring_account_id ON recurring_transactions (account_id)")
    op.execute("ALTER TABLE recurring_transactions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recurring_transactions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY recurring_transactions_self_scope ON recurring_transactions
        FOR ALL
        USING (
          current_setting('app.current_user_id', true) = user_id::text
          OR current_setting('app.auth_scope', true) = 'bypass'
        )
        WITH CHECK (
          current_setting('app.current_user_id', true) = user_id::text
          OR current_setting('app.auth_scope', true) = 'bypass'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS recurring_transactions_self_scope ON recurring_transactions")
    op.execute("ALTER TABLE recurring_transactions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recurring_transactions DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS recurring_transactions")
