from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_audit_events_append_only()")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_audit_events_append_only()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only'
            USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION enforce_audit_events_append_only()
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cifra_app') THEN
            CREATE ROLE cifra_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
          END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO cifra_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cifra_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cifra_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO cifra_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO cifra_app"
    )

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE backup_codes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE backup_codes FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY users_self_scope ON users
        FOR ALL
        USING (
          current_setting('app.current_user_id', true) = id::text
          OR current_setting('app.auth_scope', true) = 'bypass'
        )
        WITH CHECK (
          current_setting('app.current_user_id', true) = id::text
          OR current_setting('app.auth_scope', true) = 'bypass'
        )
        """
    )
    op.execute(
        """
        CREATE POLICY audit_events_self_scope ON audit_events
        FOR ALL
        USING (
          current_setting('app.current_user_id', true) = user_id::text
          OR current_setting('app.auth_scope', true) = 'bypass'
        )
        WITH CHECK (
          user_id IS NULL
          OR current_setting('app.current_user_id', true) = user_id::text
          OR current_setting('app.auth_scope', true) = 'bypass'
        )
        """
    )

    op.execute(
        """
        CREATE POLICY refresh_tokens_self_scope ON refresh_tokens
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
        CREATE POLICY backup_codes_self_scope ON backup_codes
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
    op.execute("DROP POLICY IF EXISTS backup_codes_self_scope ON backup_codes")
    op.execute("DROP POLICY IF EXISTS refresh_tokens_self_scope ON refresh_tokens")
    op.execute("DROP POLICY IF EXISTS audit_events_self_scope ON audit_events")
    op.execute("DROP POLICY IF EXISTS users_self_scope ON users")
    op.execute("ALTER TABLE backup_codes NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE backup_codes DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_audit_events_append_only()")
