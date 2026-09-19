"""Contracts for the final approval stage."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..ingestion.models import NormalizationResult, SourceDocument


class BusinessRuleDecision(BaseModel):
    decision: Literal["ACCEPT", "REJECT", "VP_REVIEW"]
    triggered_rules: list[str] = Field(default_factory=list)
    reasoning: str
    concerns: list[str] = Field(default_factory=list)


class VPDecision(BaseModel):
    decision: Literal["GO", "NO_GO"]
    reasoning: str
    addressed_concerns: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """The already-validated inputs supplied to approval."""

    invoice_id: str
    source_document: SourceDocument | None = None
    normalization: NormalizationResult
    validation_result: Any = None
    reconciliation_result: Any = None


class ApprovalResult(BaseModel):
    invoice_id: str
    final_status: Literal["APPROVED", "REJECTED"]
    decision_source: Literal["BUSINESS_RULE_AGENT", "VP_AGENT"]
    business_rule_decision: BusinessRuleDecision
    vp_decision: VPDecision | None = None
    reasoning: str
