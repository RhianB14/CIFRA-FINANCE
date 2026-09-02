from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transaction_tags")
    op.execute("DROP TABLE IF EXISTS account_balance_snapshots")
    op.execute("DROP TABLE IF EXISTS import_batches")
    op.execute("DROP TABLE IF EXISTS tags")
    op.execute("DROP TABLE IF EXISTS categories")

    op.execute(
        """
        CREATE TABLE categories (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name VARCHAR(120) NOT NULL,
          kind VARCHAR(10) NOT NULL,
          color CHAR(7),
          archived_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT categories_kind_allowed CHECK (kind IN ('income', 'expense'))
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_categories_user_id_name ON categories (user_id, name)")

    op.execute(
        """
        CREATE TABLE tags (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name VARCHAR(60) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_tags_user_id_name ON tags (user_id, name)")

    op.execute(
        """
        CREATE TABLE import_batches (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
          source_name VARCHAR(120) NOT NULL,
          file_name VARCHAR(255) NOT NULL,
          file_sha256 CHAR(64) NOT NULL,
          row_count INTEGER NOT NULL DEFAULT 0,
          imported_count INTEGER NOT NULL DEFAULT 0,
          skipped_count INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_import_batches_user_sha256 ON import_batches (user_id, file_sha256)"
    )

    op.execute(
        """
        CREATE TABLE account_balance_snapshots (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          reported_balance_cents BIGINT NOT NULL,
          ledger_balance_cents BIGINT NOT NULL,
          difference_cents BIGINT NOT NULL,
          status VARCHAR(20) NOT NULL,
          note VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT account_balance_snapshots_status_allowed CHECK (
            status IN ('matched', 'divergent')
          )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE transaction_tags (
          transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
          tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
          PRIMARY KEY (transaction_id, tag_id)
        )
        """
    )
    op.execute(
        "ALTER TABLE transactions"
        " ADD COLUMN category_id UUID REFERENCES categories(id) ON DELETE SET NULL"
    )

    for table in (
        "categories",
        "tags",
        "import_batches",
        "account_balance_snapshots",
        "transaction_tags",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for table, column in (
        ("categories", "user_id"),
        ("tags", "user_id"),
        ("import_batches", "user_id"),
        ("account_balance_snapshots", "user_id"),
    ):
        op.execute(
            f"""
            CREATE POLICY {table}_self_scope ON {table}
            FOR ALL
            USING (
              current_setting('app.current_user_id', true) = {column}::text
              OR current_setting('app.auth_scope', true) = 'bypass'
            )
            WITH CHECK (
              current_setting('app.current_user_id', true) = {column}::text
              OR current_setting('app.auth_scope', true) = 'bypass'
            )
            """
        )

    op.execute(
        """
        CREATE POLICY transaction_tags_scope ON transaction_tags
        FOR ALL
        USING (
          EXISTS (
            SELECT 1 FROM transactions t
            WHERE t.id = transaction_id
              AND (
                current_setting('app.current_user_id', true) = t.user_id::text
                OR current_setting('app.auth_scope', true) = 'bypass'
              )
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1 FROM transactions t
            WHERE t.id = transaction_id
              AND (
                current_setting('app.current_user_id', true) = t.user_id::text
                OR current_setting('app.auth_scope', true) = 'bypass'
              )
          )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS transaction_tags_scope ON transaction_tags")
    for table in ("import_batches", "account_balance_snapshots", "tags", "categories"):
        op.execute(f"DROP POLICY IF EXISTS {table}_self_scope ON {table}")
    for table in (
        "transaction_tags",
        "account_balance_snapshots",
        "import_batches",
        "tags",
        "categories",
    ):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS category_id")
    op.execute("DROP TABLE IF EXISTS transaction_tags")
    op.execute("DROP TABLE IF EXISTS account_balance_snapshots")
    op.execute("DROP TABLE IF EXISTS import_batches")
    op.execute("DROP TABLE IF EXISTS tags")
    op.execute("DROP TABLE IF EXISTS categories")
