"""Contracts for the final approval stage."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..ingestion.models import NormalizationResult, SourceDocument
from ..invoice_ledger import InvoiceHistoryDecision


class UpstreamValidationResult(BaseModel):
    """Typed validation status supplied to the isolated approval boundary."""

    model_config = ConfigDict(extra="allow")
    status: Literal["VALID", "DENIED", "TECHNICAL_FAILURE"]


class UpstreamReconciliationResult(BaseModel):
    """Typed reconciliation status supplied to the isolated approval boundary."""

    model_config = ConfigDict(extra="allow")
    status: Literal["PASS", "DENY"]


def upstream_status_value(value: Any) -> str | None:
    """Read a status from typed or legacy-shaped upstream input."""

    if value is None:
        return None
    if hasattr(value, "status"):
        value = value.status
    if isinstance(value, dict):
        value = value.get("status")
    if hasattr(value, "value"):
        value = value.value
    return str(value).upper() if value is not None else None


class BusinessRuleDecision(BaseModel):
    decision: Literal["ACCEPT", "REJECT", "VP_REVIEW"]
    triggered_rules: list[str] = Field(default_factory=list)
    reasoning: str
    concerns: list[str] = Field(default_factory=list)


class VPDecision(BaseModel):
    decision: Literal["GO", "NO_GO", "HUMAN_REVIEW_REQUIRED"]
    reasoning: str
    addressed_concerns: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """The already-validated inputs supplied to approval."""

    invoice_id: str
    source_document: SourceDocument | None = None
    normalization: NormalizationResult
    validation_result: UpstreamValidationResult
    reconciliation_result: UpstreamReconciliationResult
    invoice_history: InvoiceHistoryDecision | None = None


class ApprovalResult(BaseModel):
    invoice_id: str
    final_status: Literal["APPROVED", "REJECTED", "HUMAN_REVIEW_REQUIRED"]
    decision_source: Literal["BUSINESS_RULE_AGENT", "VP_AGENT"]
    business_rule_decision: BusinessRuleDecision
    vp_decision: VPDecision | None = None
    reasoning: str
