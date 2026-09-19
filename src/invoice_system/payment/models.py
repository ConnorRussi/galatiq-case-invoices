"""Typed contracts for the local mock payment boundary."""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class PaymentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentRequest(BaseModel):
    invoice_id: str = Field(min_length=1)
    vendor: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def iso_currency_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isascii() or not value.isalpha():
            raise ValueError("currency must be a three-letter ISO currency code")
        return value


class PaymentResult(BaseModel):
    status: PaymentStatus
    invoice_id: str
    vendor: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    transaction_id: str | None = None
    reason: str
