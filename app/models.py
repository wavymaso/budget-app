"""Request bodies and helpers for converting money."""
from datetime import date as Date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import BaseModel, Field, field_validator

MAX_AMOUNT = Decimal("1000000")
CATEGORY_SOURCES = {"learned", "rule", "fuzzy", "ai", "manual", "none"}


def parse_amount(amount: Decimal | float | int | str) -> Decimal:
    """Accepts 12.5, "12,50", "1.234,56", "1,234.56", "€ 7"."""
    if isinstance(amount, Decimal):
        return amount
    text = str(amount).strip().replace("€", "").replace("EUR", "").replace(" ", "").replace("\u00a0", "")
    if "," in text and "." in text:
        # Whichever separator comes last is the decimal one.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"not a valid amount: {amount!r}")
    if not value.is_finite():
        raise ValueError(f"not a valid amount: {amount!r}")
    return value


def to_cents(amount: Decimal | float | int | str) -> int:
    """Euros -> integer cents."""
    return int((parse_amount(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class ExpenseIn(BaseModel):
    amount: Decimal = Field(description="Euros. Negative for a refund.")
    merchant: str = Field(min_length=1, max_length=200)
    date: Date | None = None
    note: str | None = Field(default=None, max_length=1000)
    category_id: int | None = None
    # Where the chosen category came from, as shown in the form. If you
    # picked or confirmed it yourself, send "manual".
    category_source: str | None = None
    # Add it again on the same day every month (only when creating an expense).
    repeat_monthly: bool = False

    @field_validator("merchant")
    @classmethod
    def _merchant(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("merchant is required")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, v):
        return parse_amount(v) if isinstance(v, (str, int, float)) else v

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("amount can't be zero")
        if abs(v) >= MAX_AMOUNT:
            raise ValueError("amount is too large")
        return v

    @field_validator("category_source")
    @classmethod
    def _source(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORY_SOURCES:
            raise ValueError(f"category_source must be one of {sorted(CATEGORY_SOURCES)}")
        return v
