from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS transactions_append_only ON transactions")
    op.execute("DROP FUNCTION IF EXISTS enforce_transactions_append_only()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_transactions_append_only()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF NEW.id IS DISTINCT FROM OLD.id
              OR NEW.user_id IS DISTINCT FROM OLD.user_id
              OR NEW.account_id IS DISTINCT FROM OLD.account_id
              OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
              OR NEW.payload_signature IS DISTINCT FROM OLD.payload_signature
              OR NEW.kind IS DISTINCT FROM OLD.kind
              OR NEW.operation_type IS DISTINCT FROM OLD.operation_type
              OR NEW.amount_cents IS DISTINCT FROM OLD.amount_cents
              OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
              OR NEW.description IS DISTINCT FROM OLD.description
              OR NEW.external_id IS DISTINCT FROM OLD.external_id
              OR NEW.fingerprint IS DISTINCT FROM OLD.fingerprint
              OR NEW.reversal_of_id IS DISTINCT FROM OLD.reversal_of_id
              OR NEW.category_id IS DISTINCT FROM OLD.category_id
              OR NEW.transfer_group_id IS DISTINCT FROM OLD.transfer_group_id
              OR (NEW.status = OLD.status)
              OR (OLD.status = 'posted' AND NEW.status <> 'posted')
              OR (OLD.status = 'pending' AND NEW.status NOT IN ('pending', 'posted')) THEN
              RAISE EXCEPTION 'transactions is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          ELSE
            RAISE EXCEPTION 'transactions is append-only'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
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


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS transactions_append_only ON transactions")
    op.execute("DROP FUNCTION IF EXISTS enforce_transactions_append_only()")
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
