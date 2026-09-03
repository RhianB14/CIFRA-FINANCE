import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InvoicePayment


async def test_invoice_payments_are_append_only(db_session: AsyncSession) -> None:
    trigger = await db_session.scalar(
        sa.text("SELECT COUNT(*) FROM pg_trigger WHERE tgname = 'invoice_payments_append_only'")
    )
    assert trigger == 1


async def test_f4_tables_force_rls(db_session: AsyncSession) -> None:
    rows = await db_session.execute(
        sa.text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('credit_cards', 'card_invoices', 'invoice_payments')"
        )
    )
    assert {row[0]: (row[1], row[2]) for row in rows.all()} == {
        "credit_cards": (True, True),
        "card_invoices": (True, True),
        "invoice_payments": (True, True),
    }
    assert InvoicePayment.__tablename__ == "invoice_payments"
