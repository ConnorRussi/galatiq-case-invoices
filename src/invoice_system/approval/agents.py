"""Small structured-output agents for approval decisions."""

import json
import os
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
    content = _json({
        "invoice_id": request.invoice_id,
        "original_document": request.source_document,
        "normalized_invoice": request.normalization,
        "validation_result": request.validation_result,
        "reconciliation_result": request.reconciliation_result,
    })
    return invoke_structured(
        system_prompt=system_prompt,
        content=content,
        output_model=BusinessRuleDecision,
        model=os.getenv("BUSINESS_RULE_MODEL") or os.getenv("TAMUS_AI_CHAT_MODEL"),
    )


def vp_agent(request: ApprovalRequest, business_decision: BusinessRuleDecision) -> VPDecision:
    system_prompt = """You are Acme's VP authorization agent. Decide whether to authorize
payment for an invoice that passed upstream validation and reconciliation but was
escalated under Acme's approval policy. Return GO or NO_GO with concise reasoning.
This is not a second validation pass: do not rewrite invoice data, redo OCR, query
databases, or invent policy. If the supplied evidence materially undermines the
upstream result, explain that in NO_GO reasoning."""
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
    })
    return invoke_structured(
        system_prompt=system_prompt,
        content=content,
        output_model=VPDecision,
        model=(
            os.getenv("VP_REASONING_MODEL")
            or os.getenv("VP_REASONING_MODEL-NAME")  # legacy local spelling
            or os.getenv("VP_MODEL")
            or os.getenv("BUSINESS_RULE_MODEL")
            or os.getenv("TAMUS_AI_CHAT_MODEL")
        ),
    )
