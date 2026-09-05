from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("limit_cents", sa.BigInteger(), nullable=False),
        sa.Column("closing_day", sa.Integer(), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("last_four", sa.CHAR(length=4), nullable=True),
        sa.Column("archived_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "closing_day BETWEEN 1 AND 28 AND due_day BETWEEN 1 AND 28",
            name=op.f("ck_credit_cards_days_valid"),
        ),
        sa.CheckConstraint("limit_cents >= 0", name=op.f("ck_credit_cards_limit_non_negative")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_credit_cards_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_credit_cards_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_cards")),
    )
    op.create_index(
        "uq_credit_cards_user_id_name", "credit_cards", ["user_id", "name"], unique=True
    )
    op.create_table(
        "card_invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("closed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'partially_paid', 'paid', 'overdue')",
            name=op.f("ck_card_invoices_status_allowed"),
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name=op.f("ck_card_invoices_month_valid")),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["credit_cards.id"],
            name=op.f("fk_card_invoices_card_id_credit_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_card_invoices_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_invoices")),
    )
    op.create_index("ix_card_invoices_user_id", "card_invoices", ["user_id"], unique=False)
    op.create_index(
        "uq_card_invoices_card_period", "card_invoices", ["card_id", "year", "month"], unique=True
    )
    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_signature", sa.CHAR(length=64), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("reversed_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('payment', 'reversal')", name=op.f("ck_invoice_payments_kind_allowed")
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_invoice_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_invoice_payments_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["card_invoices.id"],
            name=op.f("fk_invoice_payments_invoice_id_card_invoices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversed_by_id"],
            ["invoice_payments.id"],
            name=op.f("fk_invoice_payments_reversed_by_id_invoice_payments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_invoice_payments_transaction_id_transactions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_invoice_payments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_payments")),
    )
    op.create_index(
        "ix_invoice_payments_invoice_id", "invoice_payments", ["invoice_id"], unique=False
    )
    op.create_index(
        "uq_invoice_payments_account_idempotency",
        "invoice_payments",
        ["account_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_invoice_payments_reversed_payment",
        "invoice_payments",
        ["reversed_by_id"],
        unique=True,
        postgresql_where=sa.text("reversed_by_id IS NOT NULL"),
    )
    op.add_column("transactions", sa.Column("card_id", sa.UUID(), nullable=True))
    op.add_column("transactions", sa.Column("invoice_id", sa.UUID(), nullable=True))
    op.add_column("transactions", sa.Column("charge_kind", sa.String(length=20), nullable=True))
    op.add_column("transactions", sa.Column("installment_group_id", sa.UUID(), nullable=True))
    op.add_column("transactions", sa.Column("installment_number", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("installment_total", sa.Integer(), nullable=True))
    op.create_index("ix_transactions_card_id", "transactions", ["card_id"], unique=False)
    op.create_index(
        "ix_transactions_installment_group_id",
        "transactions",
        ["installment_group_id"],
        unique=False,
    )
    op.create_index("ix_transactions_invoice_id", "transactions", ["invoice_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_transactions_card_id_credit_cards"),
        "transactions",
        "credit_cards",
        ["card_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_transactions_invoice_id_card_invoices"),
        "transactions",
        "card_invoices",
        ["invoice_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("transactions_charge_kind_allowed"),
        "transactions",
        "charge_kind IS NULL OR charge_kind IN ('purchase', 'interest', 'late_fee', "
        "'iof', 'withdrawal_fee', 'other', 'payment', 'payment_reversal')",
    )
    op.create_check_constraint(
        op.f("transactions_card_linkage"),
        "transactions",
        "card_id IS NULL OR (invoice_id IS NOT NULL AND charge_kind IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("transactions_card_operation"),
        "transactions",
        "operation_type NOT IN ('card_purchase', 'card_payment') OR card_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("transactions_installment_pair"),
        "transactions",
        "(installment_number IS NULL) = (installment_total IS NULL)",
    )
    op.create_check_constraint(
        op.f("transactions_installment_range"),
        "transactions",
        "installment_number IS NULL OR "
        "(installment_number BETWEEN 1 AND installment_total AND installment_total <= 48)",
    )
    op.drop_constraint("transactions_operation_allowed", "transactions", type_="check")
    op.create_check_constraint(
        "transactions_operation_allowed",
        "transactions",
        "operation_type IN ('deposit', 'withdrawal', 'reversal', 'transfer_in', "
        "'transfer_out', 'card_purchase', 'card_payment')",
    )
    for table in ("credit_cards", "card_invoices", "invoice_payments"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner ON {table} USING "
            "(user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid) "
            "WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)"
        )
        op.execute(
            f"CREATE POLICY {table}_bypass ON {table} USING "
            "(current_setting('app.auth_scope', true) = 'bypass') WITH CHECK "
            "(current_setting('app.auth_scope', true) = 'bypass')"
        )
    op.execute(
        """
        CREATE FUNCTION reject_invoice_payment_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'invoice_payments are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER invoice_payments_append_only BEFORE UPDATE OR DELETE ON invoice_payments "
        "FOR EACH ROW EXECUTE FUNCTION reject_invoice_payment_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS invoice_payments_append_only ON invoice_payments")
    op.execute("DROP FUNCTION IF EXISTS reject_invoice_payment_mutation()")
    op.drop_constraint("transactions_operation_allowed", "transactions", type_="check")
    op.create_check_constraint(
        "transactions_operation_allowed",
        "transactions",
        "operation_type IN ('deposit', 'withdrawal', 'reversal', 'transfer_in', 'transfer_out')",
    )
    op.drop_constraint(op.f("transactions_charge_kind_allowed"), "transactions", type_="check")
    op.drop_constraint(op.f("transactions_card_linkage"), "transactions", type_="check")
    op.drop_constraint(op.f("transactions_card_operation"), "transactions", type_="check")
    op.drop_constraint(op.f("transactions_installment_pair"), "transactions", type_="check")
    op.drop_constraint(op.f("transactions_installment_range"), "transactions", type_="check")
    op.drop_constraint(
        op.f("fk_transactions_invoice_id_card_invoices"), "transactions", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_transactions_card_id_credit_cards"), "transactions", type_="foreignkey"
    )
    op.drop_index("ix_transactions_invoice_id", table_name="transactions")
    op.drop_index("ix_transactions_installment_group_id", table_name="transactions")
    op.drop_index("ix_transactions_card_id", table_name="transactions")
    op.drop_column("transactions", "installment_total")
    op.drop_column("transactions", "installment_number")
    op.drop_column("transactions", "installment_group_id")
    op.drop_column("transactions", "charge_kind")
    op.drop_column("transactions", "invoice_id")
    op.drop_column("transactions", "card_id")
    op.drop_index("uq_invoice_payments_account_idempotency", table_name="invoice_payments")
    op.drop_index("uq_invoice_payments_reversed_payment", table_name="invoice_payments")
    op.drop_index("ix_invoice_payments_invoice_id", table_name="invoice_payments")
    op.drop_table("invoice_payments")
    op.drop_index("uq_card_invoices_card_period", table_name="card_invoices")
    op.drop_index("ix_card_invoices_user_id", table_name="card_invoices")
    op.drop_table("card_invoices")
    op.drop_index("uq_credit_cards_user_id_name", table_name="credit_cards")
    op.drop_table("credit_cards")
