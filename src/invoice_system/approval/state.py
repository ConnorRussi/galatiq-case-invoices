from typing import TypedDict

from .models import ApprovalRequest, ApprovalResult, BusinessRuleDecision, VPDecision


class ApprovalState(TypedDict):
    request: ApprovalRequest
    business_rule_decision: BusinessRuleDecision | None
    vp_decision: VPDecision | None
    result: ApprovalResult | None
