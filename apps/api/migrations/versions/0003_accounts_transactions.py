from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS transactions_append_only ON transactions")
    op.execute("DROP FUNCTION IF EXISTS enforce_transactions_append_only()")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS accounts")

    op.execute(
        """
        CREATE TABLE accounts (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name VARCHAR(255) NOT NULL,
          kind VARCHAR(20) NOT NULL,
          currency CHAR(3) NOT NULL,
          initial_balance_cents BIGINT NOT NULL DEFAULT 0,
          current_balance_cents BIGINT NOT NULL DEFAULT 0,
          current_balance_version INTEGER NOT NULL DEFAULT 0,
          archived_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT accounts_kind_allowed CHECK (
            kind IN ('checking', 'savings', 'credit', 'cash', 'investment')
          )
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_accounts_user_id_name ON accounts (user_id, name)")

    op.execute(
        """
        CREATE TABLE transactions (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
          idempotency_key VARCHAR(128) NOT NULL,
          payload_signature CHAR(64) NOT NULL,
          kind CHAR(6) NOT NULL,
          operation_type VARCHAR(32) NOT NULL,
          status VARCHAR(10) NOT NULL DEFAULT 'posted',
          amount_cents BIGINT NOT NULL,
          occurred_at TIMESTAMPTZ NOT NULL,
          description VARCHAR(500),
          external_id VARCHAR(255),
          fingerprint CHAR(64),
          reversal_of_id UUID REFERENCES transactions(id) ON DELETE RESTRICT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT transactions_amount_positive CHECK (amount_cents > 0),
          CONSTRAINT transactions_kind_allowed CHECK (kind IN ('credit', 'debit')),
          CONSTRAINT transactions_operation_allowed CHECK (
            operation_type IN ('deposit', 'withdrawal', 'reversal')
          ),
          CONSTRAINT transactions_status_allowed CHECK (status IN ('pending', 'posted'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_transactions_account_idempotency"
        " ON transactions (account_id, idempotency_key)"
    )
    op.execute(
        "CREATE INDEX ix_transactions_account_id_occurred_at"
        " ON transactions (account_id, occurred_at)"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_transactions_append_only()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'transactions is append-only'
            USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER transactions_append_only
        BEFORE UPDATE OR DELETE ON transactions
        FOR EACH ROW EXECUTE FUNCTION enforce_transactions_append_only()
        """
    )

    op.execute("ALTER TABLE accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE accounts FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE transactions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE transactions FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY accounts_self_scope ON accounts
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
    op.execute(
        """
        CREATE POLICY transactions_self_scope ON transactions
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
    op.execute("DROP POLICY IF EXISTS transactions_self_scope ON transactions")
    op.execute("DROP POLICY IF EXISTS accounts_self_scope ON accounts")
    op.execute("ALTER TABLE transactions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE transactions DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE accounts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE accounts DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TRIGGER IF EXISTS transactions_append_only ON transactions")
    op.execute("DROP FUNCTION IF EXISTS enforce_transactions_append_only()")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS accounts")
