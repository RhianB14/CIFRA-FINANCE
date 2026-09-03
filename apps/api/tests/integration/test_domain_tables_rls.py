import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DOMAIN_TABLES = (
    "accounts",
    "transactions",
    "categories",
    "tags",
    "import_batches",
    "account_balance_snapshots",
    "credit_cards",
    "card_invoices",
    "invoice_payments",
)


@pytest.mark.asyncio
async def test_domain_tables_have_row_level_security(db_session: AsyncSession) -> None:
    for table in DOMAIN_TABLES:
        row = await db_session.execute(
            text(
                "SELECT relrowsecurity FROM pg_class"
                " WHERE relname = :table AND relnamespace = 'public'::regnamespace"
            ),
            {"table": table},
        )
        found = row.scalar()
        assert found is not None, f"missing table {table}"
        assert found is True, f"table {table} without row level security"

        policy = await db_session.execute(
            text(
                "SELECT COUNT(*) FROM pg_policies"
                " WHERE tablename = :table AND schemaname = 'public'"
            ),
            {"table": table},
        )
        assert policy.scalar_one() >= 1, f"table {table} without rls policy"
