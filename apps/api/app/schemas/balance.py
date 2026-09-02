from pydantic import BaseModel


class AccountBalanceOut(BaseModel):
    account_id: str
    current_balance_cents: int
    projected_balance_cents: int
