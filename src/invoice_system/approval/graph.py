"""Business-rule-first approval graph with an escalation-only VP branch."""

import logging

from langgraph.graph import END, START, StateGraph

from .agents import business_rule_agent, vp_agent
from .models import ApprovalResult
from .state import ApprovalState

logger = logging.getLogger(__name__)


def business_rule_node(state: ApprovalState) -> dict:
    decision = business_rule_agent(state["request"])
    logger.info("[business_rule] %s", decision.decision)
    return {"business_rule_decision": decision}


def route_business_decision(state: ApprovalState) -> str:
    decision = state["business_rule_decision"]
    if decision is None:
        raise ValueError("route_business_decision requires a business rule decision")
    return decision.decision.lower()


def vp_node(state: ApprovalState) -> dict:
    decision = state["business_rule_decision"]
    if decision is None:
        raise ValueError("vp_agent requires a business rule decision")
    result = vp_agent(state["request"], decision)
    logger.info("[vp] %s", result.decision)
    return {"vp_decision": result}


def complete_node(state: ApprovalState) -> dict:
    business = state["business_rule_decision"]
    if business is None:
        raise ValueError("approval completion requires a business rule decision")
    vp = state["vp_decision"]
    if business.decision == "VP_REVIEW" and vp is None:
        raise ValueError("VP_REVIEW requires a VP decision")
    approved = vp.decision == "GO" if vp is not None else business.decision == "ACCEPT"
    source = "VP_AGENT" if vp is not None else "BUSINESS_RULE_AGENT"
    reasoning = vp.reasoning if vp is not None else business.reasoning
    return {"result": ApprovalResult(
        invoice_id=state["request"].invoice_id,
        final_status="APPROVED" if approved else "REJECTED",
        decision_source=source,
        business_rule_decision=business,
        vp_decision=vp,
        reasoning=reasoning,
    )}


def build_graph():
    graph = StateGraph(ApprovalState)
    graph.add_node("business_rule_agent", business_rule_node)
    graph.add_node("vp_agent", vp_node)
    graph.add_node("approval_complete", complete_node)
    graph.add_edge(START, "business_rule_agent")
    graph.add_conditional_edges("business_rule_agent", route_business_decision, {
        "accept": "approval_complete", "reject": "approval_complete", "vp_review": "vp_agent",
    })
    graph.add_edge("vp_agent", "approval_complete")
    graph.add_edge("approval_complete", END)
    return graph.compile()
