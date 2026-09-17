"""Provider-neutral evidence, proposal, and trusted ingestion contracts."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceDocument(StrictModel):
    path: Path
    sha256: str
    size_bytes: int
    media_type: str = "application/pdf"


class EvidenceLocator(StrictModel):
    page: int = Field(ge=1)
    block_id: str | None = None
    word_ids: list[int] = Field(default_factory=list)
    bbox: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_box(self):
        x0, y0, x1, y1 = self.bbox
        if not all(Decimal(str(v)).is_finite() for v in self.bbox) or not (0 <= x0 < x1 and 0 <= y0 < y1):
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
    source: SourceDocument | None
    pages: list[Page]
    text: str
    usable_text: bool


class TransformationProposal(StrictModel):
    normalized: str
    explanation: str


class ObservedField(StrictModel):
    literal: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    evidence: list[EvidenceLocator] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    transformation: TransformationProposal | None = None


class ProposedLineItem(StrictModel):
    name: ObservedField = Field(default_factory=ObservedField)
    quantity: ObservedField = Field(default_factory=ObservedField)
    unit_price: ObservedField = Field(default_factory=ObservedField)
    declared_amount: ObservedField = Field(default_factory=ObservedField)
    note: ObservedField = Field(default_factory=ObservedField)


class InvoiceProposal(StrictModel):
    invoice_number: ObservedField = Field(default_factory=ObservedField)
    revision: ObservedField = Field(default_factory=ObservedField)
    vendor: ObservedField = Field(default_factory=ObservedField)
    invoice_date: ObservedField = Field(default_factory=ObservedField)
    due_date: ObservedField = Field(default_factory=ObservedField)
    currency: ObservedField = Field(default_factory=ObservedField)
    subtotal: ObservedField = Field(default_factory=ObservedField)
    tax: ObservedField = Field(default_factory=ObservedField)
    shipping: ObservedField = Field(default_factory=ObservedField)
    fees: ObservedField = Field(default_factory=ObservedField)
    declared_total: ObservedField = Field(default_factory=ObservedField)
    payment_terms: ObservedField = Field(default_factory=ObservedField)
    line_items: list[ProposedLineItem] = Field(default_factory=list)
    recommend_review: bool = False


class Issue(StrictModel):
    code: str
    field: str | None = None
    message: str
    evidence: list[EvidenceLocator] = Field(default_factory=list)


class NormalizedField(StrictModel):
    value_type: Literal["text", "decimal", "date"] = "text"
    value: str | Decimal | date | None = None
    observed: ObservedField
    applied_rule: str | None = None

    @model_validator(mode="before")
    @classmethod
    def restore_typed_value(cls, data):
        if isinstance(data, dict) and isinstance(data.get("value"), str):
            data = dict(data)
            if data.get("value_type") == "decimal":
                data["value"] = Decimal(data["value"])
            elif data.get("value_type") == "date":
                data["value"] = date.fromisoformat(data["value"])
        return data


class LineItem(StrictModel):
    name: NormalizedField
    quantity: NormalizedField
    unit_price: NormalizedField
    declared_amount: NormalizedField
    note: NormalizedField


class InvoiceCandidate(StrictModel):
    invoice_number: NormalizedField
    revision: NormalizedField
    vendor: NormalizedField
    invoice_date: NormalizedField
    due_date: NormalizedField
    currency: NormalizedField
    subtotal: NormalizedField
    tax: NormalizedField
    shipping: NormalizedField
    fees: NormalizedField
    declared_total: NormalizedField
    payment_terms: NormalizedField
    line_items: list[LineItem]


class Critique(StrictModel):
    decision: Literal["accept", "revise", "review"]
    issues: list[Issue] = Field(default_factory=list)


class Counters(StrictModel):
    model_requests: int = 0
    interpret_attempts: int = 0
    critic_runs: int = 0
    revisions: int = 0
    pro_escalations: int = 0
    graph_steps: int = 0
    transport_retries: int = 0


IngestionStatus = Literal["ready_for_validation", "invalid_input", "needs_review", "technical_failure"]


class IngestionResult(StrictModel):
    run_id: str
    status: IngestionStatus
    source: SourceDocument | None = None
    invoice: InvoiceCandidate | None = None
    issues: list[Issue] = Field(default_factory=list)
    counters: Counters = Field(default_factory=Counters)


class WorkflowState(StrictModel):
    run_id: str
    path: Path
    source: SourceDocument | None = None
    extraction: ExtractedDocument | None = None
    proposal: InvoiceProposal | None = None
    candidate: InvoiceCandidate | None = None
    critique: Critique | None = None
    issues: list[Issue] = Field(default_factory=list)
    normalization_issues: list[Issue] = Field(default_factory=list)
    counters: Counters = Field(default_factory=Counters)
    operation: Literal["interpret", "critique", "revise", "pro"] = "interpret"
    last_outcome: str = ""
    next_node: str = "model"
    visual: bool = False
    status: IngestionStatus | None = None
    result: IngestionResult | None = None


class BatchItemResult(StrictModel):
    artifact: str | None
    result: IngestionResult


class BatchResult(StrictModel):
    status: Literal["completed", "completed_with_errors"]
    results: list[BatchItemResult]
