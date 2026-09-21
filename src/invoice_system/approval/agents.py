"""Small structured-output agents for approval decisions."""

import json
from typing import Any

from ..agent_runtime import invoke_structured
from .models import ApprovalRequest, BusinessRuleDecision, VPDecision
from .policy import load_approval_policy


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, default=str)


def business_rule_agent(request: ApprovalRequest) -> BusinessRuleDecision:
    system_prompt = f"""You are Acme's Business Rule Agent.
Apply only the approval policy below to the validated and reconciled invoice.
You are not a validation agent: do not redo OCR, repair fields, recalculate totals,
or invent policy. Interpret reasonable semantic equivalents such as amount_due and
grand_total. If upstream data is missing, contradictory, or unusable, state that
clearly as a concern. Return ACCEPT, REJECT, or VP_REVIEW.

APPROVAL POLICY:
{load_approval_policy()}"""
    if request.invoice_history is not None and request.invoice_history.requires_human_review:
        system_prompt += """

INVOICE HISTORY CONTROL:
The deterministic invoice history check found a paid prior version. Route this
case to VP_REVIEW. Do not authorize a replacement payment. The VP stage must
return HUMAN_REVIEW_REQUIRED so a human can decide whether a credit, refund, or
adjustment is appropriate."""
    content = _json({
        "invoice_id": request.invoice_id,
        "original_document": request.source_document,
        "normalized_invoice": request.normalization,
        "validation_result": request.validation_result,
        "reconciliation_result": request.reconciliation_result,
        "invoice_history": request.invoice_history,
    })
    return invoke_structured(
        system_prompt=system_prompt,
        content=content,
        output_model=BusinessRuleDecision,
    )


def vp_agent(request: ApprovalRequest, business_decision: BusinessRuleDecision) -> VPDecision:
    system_prompt = """You are Acme's VP authorization agent. Decide whether to authorize
payment for an invoice that passed upstream validation and reconciliation but was
escalated under Acme's approval policy. Return GO, NO_GO, or
HUMAN_REVIEW_REQUIRED with concise reasoning.
This is not a second validation pass: do not rewrite invoice data, redo OCR, query
databases, or invent policy. If the supplied evidence materially undermines the
upstream result, explain that in NO_GO reasoning. If invoice history says a
paid prior version exists, return HUMAN_REVIEW_REQUIRED and do not authorize
another full payment for the revised invoice."""
    content = _json({
        "invoice_id": request.invoice_id,
        "original_document": request.source_document,
        "normalized_invoice": request.normalization,
        "validation_result": request.validation_result,
        "reconciliation_result": request.reconciliation_result,
        "business_rule_decision": business_decision,
        "escalation_reason": business_decision.reasoning,
        "triggered_rules": business_decision.triggered_rules,
        "concerns": business_decision.concerns,
        "invoice_history": request.invoice_history,
    })
    result = invoke_structured(
        system_prompt=system_prompt,
        content=content,
        output_model=VPDecision,
    )
    if request.invoice_history is not None and request.invoice_history.requires_human_review:
        return result.model_copy(update={
            "decision": "HUMAN_REVIEW_REQUIRED",
            "reasoning": (
                "A paid prior invoice version exists. Human review is required "
                "before any adjustment, credit, refund, or replacement payment. "
                + result.reasoning
            ),
        })
    return result
