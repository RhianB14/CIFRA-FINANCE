from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER_FUNCTION_DDL = """
CREATE OR REPLACE FUNCTION forbid_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_CREATE_DDL = """
CREATE TRIGGER audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION forbid_audit_mutation()
"""

TRIGGER_DROP_DDL = "DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events"

TRIGGER_FUNCTION_DROP_DDL = "DROP FUNCTION IF EXISTS forbid_audit_mutation()"


def upgrade() -> None:
    op.execute(TRIGGER_FUNCTION_DDL)
    op.execute(TRIGGER_CREATE_DDL)


def downgrade() -> None:
    op.execute(TRIGGER_DROP_DDL)
    op.execute(TRIGGER_FUNCTION_DROP_DDL)
