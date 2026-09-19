"""Typed contracts for the local mock payment boundary."""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class PaymentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentRequest(BaseModel):
    invoice_id: str = Field(min_length=1)
    vendor: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str | None = None


class PaymentResult(BaseModel):
    status: PaymentStatus
    invoice_id: str
    vendor: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    transaction_id: str | None = None
    reason: str
