"""Source, invoice claims, and lightweight evidence contracts."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class SourceChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    page: int | None = None
    row: int | None = None
    kind: str
    extraction_method: str


class SourceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    file_type: str
    chunks: tuple[SourceChunk, ...]


class NormalizedLineItem(BaseModel):
    item_name: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_amount: Decimal | None = None
    additional_fields: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizedInvoice(BaseModel):
    invoice_number: str | None = None
    vendor: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    items: list[NormalizedLineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    shipping: Decimal | None = None
    discount: Decimal | None = None
    invoice_total: Decimal | None = None
    amount_due: Decimal | None = None
    additional_fields: dict[str, JsonValue] = Field(default_factory=dict)


class FieldEvidence(BaseModel):
    field_path: str = Field(description="Path relative to invoice, e.g. items[0].quantity; no invoice. prefix")
    source_chunk_ids: list[str]
    source_text: str | None = None

    @field_validator("field_path")
    @classmethod
    def relative_field_path(cls, value: str) -> str:
        # A wrapper prefix is path syntax, not an invoice claim or source edit.
        return value.removeprefix("invoice.")


class NormalizationResult(BaseModel):
    invoice: NormalizedInvoice
    evidence: list[FieldEvidence]
