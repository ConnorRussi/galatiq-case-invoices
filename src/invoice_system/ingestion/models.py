"""Small, evidence-preserving contracts for the ingestion proof of concept."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceDocument(StrictModel):
    path: Path
    sha256: str
    size_bytes: int
    media_type: str = "text/plain"


class EvidenceLocator(StrictModel):
    page: int = Field(ge=1)
    block_id: str | None = None
    word_ids: list[int] = Field(default_factory=list)
    bbox: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_box(self):
        x0, y0, x1, y1 = self.bbox
        if not all(Decimal(str(value)).is_finite() for value in self.bbox) or not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError("Invalid evidence coordinates")
        return self


class PageBlock(StrictModel):
    locator: EvidenceLocator
    text: str


class Page(StrictModel):
    number: int
    width: float
    height: float
    blocks: list[PageBlock] = Field(default_factory=list)


class ExtractedDocument(StrictModel):
    source: SourceDocument
    pages: list[Page]
    text: str


FieldValue = TypeVar("FieldValue")


class ExtractedField(StrictModel, Generic[FieldValue]):
    """A source literal, the model's typed reading, and its source location."""
    original: str | None = None
    normalized: FieldValue | None = None
    evidence: list[EvidenceLocator] = Field(default_factory=list)

    @field_validator("normalized")
    @classmethod
    def finite_decimal(cls, value):
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return value


TextField = ExtractedField[str]
DecimalField = ExtractedField[Decimal]
DateField = ExtractedField[date]


class LineItem(StrictModel):
    name: TextField = Field(default_factory=TextField)
    quantity: DecimalField = Field(default_factory=DecimalField)
    unit_price: DecimalField = Field(default_factory=DecimalField)
    declared_amount: DecimalField = Field(default_factory=DecimalField)
    note: TextField = Field(default_factory=TextField)


class Invoice(StrictModel):
    invoice_number: TextField = Field(default_factory=TextField)
    revision: TextField = Field(default_factory=TextField)
    vendor: TextField = Field(default_factory=TextField)
    invoice_date: DateField = Field(default_factory=DateField)
    due_date: DateField = Field(default_factory=DateField)
    currency: TextField = Field(default_factory=TextField)
    payment_terms: TextField = Field(default_factory=TextField)
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: DecimalField = Field(default_factory=DecimalField)
    tax: DecimalField = Field(default_factory=DecimalField)
    shipping: DecimalField = Field(default_factory=DecimalField)
    fees: DecimalField = Field(default_factory=DecimalField)
    declared_total: DecimalField = Field(default_factory=DecimalField)


class Issue(StrictModel):
    code: str
    field: str | None = None
    message: str
    evidence: list[EvidenceLocator] = Field(default_factory=list)


IngestionStatus = Literal["ready_for_validation", "invalid_input", "needs_review", "technical_failure"]


class IngestionResult(StrictModel):
    run_id: str
    status: IngestionStatus
    source: SourceDocument | None = None
    invoice: Invoice | None = None
    issues: list[Issue] = Field(default_factory=list)


class BatchItemResult(StrictModel):
    artifact: str | None
    result: IngestionResult


class BatchResult(StrictModel):
    status: Literal["completed", "completed_with_errors"]
    results: list[BatchItemResult]
