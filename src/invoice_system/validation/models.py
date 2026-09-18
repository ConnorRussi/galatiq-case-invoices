"""Validation contracts. Source claims reuse ingestion's evidence-bearing models."""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from ..ingestion.models import EvidenceLocator, IngestionResult, Invoice, StrictModel
InvoiceCandidate = Invoice


class CheckStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNRESOLVED = "unresolved"


class ValidationCheck(StrictModel):
    code: str
    status: CheckStatus = CheckStatus.PENDING
    required: bool = True
    tool_calls: list[str] = Field(default_factory=list)
    finding_codes: list[str] = Field(default_factory=list)
    skip_reason: str | None = None
    unresolved_reason: str | None = None


class ValidationFinding(StrictModel):
    code: str
    severity: str
    message: str
    field: str | None = None
    subject: str | None = None
    expected: str | None = None
    actual: str | None = None
    evidence: list[EvidenceLocator] = Field(default_factory=list)


RecheckReason = Literal["SOURCE_CONTRADICTION", "AMBIGUOUS_EXTRACTION", "MISSING_EXPECTED_EVIDENCE"]


class IngestionRecheckRequest(StrictModel):
    fields: list[str] = Field(min_length=1)
    reason_code: RecheckReason
    explanation: str = Field(min_length=1)
    evidence: list[EvidenceLocator] = Field(default_factory=list)


class ConsolidatedItem(StrictModel):
    item: str | None
    quantity: Decimal | None
    source_rows: list[int]
    unavailable_fields: list[str] = Field(default_factory=list)
    evidence: list[EvidenceLocator] = Field(default_factory=list)


class LineArithmetic(StrictModel):
    source_row: int
    quantity: Decimal | None
    unit_price: Decimal | None
    declared_amount: Decimal | None
    computed_amount: Decimal | None
    variance: Decimal | None
    within_tolerance: bool | None


class ArithmeticResult(StrictModel):
    lines: list[LineArithmetic] = Field(default_factory=list)
    declared_subtotal: Decimal | None = None
    sum_declared_line_amounts: Decimal | None = None
    computed_subtotal: Decimal | None = None
    subtotal_variance: Decimal | None = None
    subtotal_within_tolerance: bool | None = None
    declared_lines_subtotal_variance: Decimal | None = None
    declared_lines_subtotal_within_tolerance: bool | None = None
    tax: Decimal | None = None
    shipping: Decimal | None = None
    fees: Decimal | None = None
    declared_total: Decimal | None = None
    computed_total: Decimal | None = None
    variance: Decimal | None = None
    within_tolerance: bool | None = None
    tolerance: Decimal
    absent_components: list[str] = Field(default_factory=list)
    unavailable_fields: list[str] = Field(default_factory=list)


class InventoryRecord(StrictModel):
    item: str
    stock: Decimal = Field(ge=0, allow_inf_nan=False)


class InventoryResult(StrictModel):
    records: list[InventoryRecord] = Field(default_factory=list)
    unknown_items: list[str] = Field(default_factory=list)
    requested_items: list[str] = Field(default_factory=list)
    source: str | None = None
    error: str | None = None


ToolName = Literal["consolidate_items", "recalculate_invoice", "get_inventory"]


class ToolCall(StrictModel):
    id: str
    tool: ToolName
    error: str | None = None


class ValidationSettings(StrictModel):
    money_tolerance: Decimal = Field(default=Decimal("0.01"), ge=0, allow_inf_nan=False)
    high_value_threshold: Decimal | None = Field(default=Decimal("10000"), ge=0, allow_inf_nan=False)
    policy_currency: str = "USD"
    max_tool_calls: int = Field(default=6, ge=0, le=100)
    max_agent_turns: int = Field(default=8, ge=1, le=100)


class AgentDecision(StrictModel):
    """An agent can request investigation, never submit facts or dispositions."""
    additional_checks: list[str] = Field(default_factory=list)
    recheck: IngestionRecheckRequest | None = None
    tool: ToolName | None = None
    explanation: str = ""


class AgentView(StrictModel):
    phase: Literal["handoff", "investigate"]
    handoff: IngestionResult
    checks: list[ValidationCheck] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)
    consolidated_items: list[ConsolidatedItem] = Field(default_factory=list)
    arithmetic: ArithmeticResult | None = None
    inventory: InventoryResult | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    remaining_tool_calls: int
    reingestion_attempts: int = 0


class ValidationReport(StrictModel):
    findings: list[ValidationFinding]
    checks: list[ValidationCheck]
    unresolved_questions: list[str]
    validation_complete: bool
    disposition: Literal["clear", "blocked", "unresolved"]
    original_invoice: InvoiceCandidate | None
    invoice: InvoiceCandidate | None
    consolidated_items: list[ConsolidatedItem]
    arithmetic: ArithmeticResult | None
    inventory: InventoryResult | None
    tool_calls: list[ToolCall]
    recheck_request: IngestionRecheckRequest | None = None
    recheck_result: IngestionResult | None = None
    reingestion_attempts: int = 0
    tool_budget_exhausted: bool = False

    @model_validator(mode="after")
    def consistent_outcome(self):
        complete, disposition = derive_outcome(self.checks, self.findings, self.tool_budget_exhausted)
        if (self.validation_complete, self.disposition) != (complete, disposition):
            raise ValueError("Report outcome must be mechanically derived")
        return self


def derive_outcome(checks, findings, exhausted=False):
    """UNRESOLVED is terminal execution; budget exhaustion is incomplete execution.

    Blocking findings take precedence over unresolved checks, except explicit tool
    exhaustion, which always reports unresolved/incomplete per the runtime contract.
    """
    complete = not exhausted and all(
        c.status != CheckStatus.PENDING and (c.status != CheckStatus.SKIPPED or bool(c.skip_reason))
        for c in checks if c.required
    )
    if exhausted:
        return False, "unresolved"
    if any(f.severity == "blocking" for f in findings):
        return complete, "blocked"
    if not complete or any(c.required and c.status == CheckStatus.UNRESOLVED for c in checks):
        return complete, "unresolved"
    return complete, "clear"


class ValidationState(StrictModel):
    original: IngestionResult
    handoff: IngestionResult
    consolidated_items: list[ConsolidatedItem] = Field(default_factory=list)
    arithmetic: ArithmeticResult | None = None
    inventory: InventoryResult | None = None
    validation_findings: list[ValidationFinding] = Field(default_factory=list)
    validation_checks: list[ValidationCheck] = Field(default_factory=list)
    validation_complete: bool = False
    validation_tool_calls: int = 0
    tool_calls: list[ToolCall] = Field(default_factory=list)
    additional_checks: list[str] = Field(default_factory=list)
    operational_issues: list[str] = Field(default_factory=list)
    recheck_request: IngestionRecheckRequest | None = None
    recheck_result: IngestionResult | None = None
    reingestion_attempts: int = 0
    agent_turns: int = 0
    next_tool: ToolName | None = None
    next_node: str = "finalize"
    tool_budget_exhausted: bool = False
    report: ValidationReport | None = None
