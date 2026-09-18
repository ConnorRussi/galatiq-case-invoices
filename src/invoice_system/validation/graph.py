"""LangGraph orchestration for semantic validation and critic revisions."""

import logging

from langgraph.graph import END, START, StateGraph

from . import config
from .critic import review_stage
from .models import (
    CriticDecision,
    SemanticStatus,
    ValidationIssue,
    ValidationResult,
    ValidationStage,
    ValidationStatus,
)
from .semantic import validate_semantics
from .state import ValidationState

logger = logging.getLogger(__name__)


def semantic_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    if ingestion is None:
        raise ValueError("semantic requires original_ingestion")
    result = validate_semantics(
        ingestion,
        revision_feedback=state.get("revision_feedback"),
        previous_result=state.get("semantic_result"),
    )
    logger.info("[semantic] Proposed %s with %s issue(s)", result.status.value, len(result.issues))
    return {
        "semantic_result": result,
        "current_stage": ValidationStage.SEMANTIC,
        "critic_revision_count": state.get("critic_revision_count", 0),
    }


def semantic_critic_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    semantic_result = state.get("semantic_result")
    if ingestion is None or semantic_result is None:
        raise ValueError("semantic_critic requires ingestion and semantic_result")
    revision_count = state.get("critic_revision_count", 0)
    result = review_stage(
        ingestion,
        ValidationStage.SEMANTIC,
        semantic_result,
        previous_critic=state.get("critic_result"),
        revision_count=revision_count,
        revision_feedback=state.get("revision_feedback"),
    )
    logger.info("[semantic_critic] %s: %s", result.decision.value, result.summary)
    updates: dict = {"critic_result": result}
    if result.decision == CriticDecision.REVISE:
        if revision_count < config.MAX_CRITIC_REVISIONS:
            updates["critic_revision_count"] = revision_count + 1
            updates["revision_feedback"] = result.revision_instructions or result.summary
        else:
            updates["critic_revision_exhausted"] = True
            updates["revision_feedback"] = result.revision_instructions or result.summary
    return updates


def _finalize(
    state: ValidationState,
    *,
    status: ValidationStatus,
    reason: str,
) -> dict:
    ingestion = state.get("original_ingestion")
    semantic_result = state.get("semantic_result")
    critic_result = state.get("critic_result")
    if ingestion is None or semantic_result is None or critic_result is None:
        raise ValueError("finalize requires complete validation state")
    return {
        "final_result": ValidationResult(
            status=status,
            reason=reason,
            denied_by=ValidationStage.SEMANTIC if status == ValidationStatus.DENIED else None,
            issues=list(semantic_result.issues),
            semantic_result=semantic_result,
            critic_result=critic_result,
            ingestion=ingestion,
        )
    }


def finalize_valid_node(state: ValidationState) -> dict:
    result = _finalize(state, status=ValidationStatus.VALID, reason="semantic_pass")
    logger.info("[finalize] Validation %s", result["final_result"].status.value)
    return result


def finalize_denied_node(state: ValidationState) -> dict:
    result = _finalize(state, status=ValidationStatus.DENIED, reason="semantic_denied")
    logger.info("[finalize] Validation %s", result["final_result"].status.value)
    return result


def finalize_unresolved_node(state: ValidationState) -> dict:
    semantic_result = state.get("semantic_result")
    if semantic_result is None:
        raise ValueError("finalize_unresolved requires semantic_result")
    semantic_result = semantic_result.model_copy(deep=True)
    semantic_result.issues.append(
        ValidationIssue(
            code="unresolved_validation",
            message="The semantic specialist and critic did not resolve their disagreement within the revision limit.",
            severity="error",
        )
    )
    state_copy = dict(state)
    state_copy["semantic_result"] = semantic_result
    result = _finalize(state_copy, status=ValidationStatus.DENIED, reason="unresolved_validation")
    logger.warning("[finalize] Validation DENIED: unresolved critic disagreement")
    return result


def route_after_critic(state: ValidationState) -> str:
    critic_result = state.get("critic_result")
    semantic_result = state.get("semantic_result")
    if critic_result is None or semantic_result is None:
        raise ValueError("route_after_critic requires critic and semantic results")
    if critic_result.decision == CriticDecision.REVISE:
        if state.get("critic_revision_exhausted", False):
            return "finalize_unresolved"
        # The critic node increments the count before routing. Equality still
        # permits the final configured revision; a further REVISE is unresolved.
        if state.get("critic_revision_count", 0) <= config.MAX_CRITIC_REVISIONS:
            return "semantic"
        return "finalize_unresolved"
    if semantic_result.status == SemanticStatus.DENY:
        # Prototype behavior:
        # Validation short-circuits after the first critic-confirmed denial to reduce
        # latency, token usage, and unnecessary downstream tool/database calls.
        # Future improvement:
        # An exhaustive-validation mode could continue through remaining stages after
        # denial to collect all invoice issues for audit/debugging/human review.
        logger.info(
            "Validation short-circuited after critic-confirmed denial. "
            "Future exhaustive validation could continue remaining stages to collect all issues."
        )
        return "finalize_denied"
    return "finalize_valid"


def build_graph():
    graph = StateGraph(ValidationState)
    graph.add_node("semantic", semantic_node)
    graph.add_node("semantic_critic", semantic_critic_node)
    graph.add_node("finalize_valid_for_phase_1", finalize_valid_node)
    graph.add_node("finalize_denied", finalize_denied_node)
    graph.add_node("finalize_unresolved", finalize_unresolved_node)
    graph.add_edge(START, "semantic")
    graph.add_edge("semantic", "semantic_critic")
    graph.add_conditional_edges(
        "semantic_critic",
        route_after_critic,
        {
            "semantic": "semantic",
            "finalize_valid": "finalize_valid_for_phase_1",
            "finalize_denied": "finalize_denied",
            "finalize_unresolved": "finalize_unresolved",
        },
    )
    graph.add_edge("finalize_valid_for_phase_1", END)
    graph.add_edge("finalize_denied", END)
    graph.add_edge("finalize_unresolved", END)
    return graph.compile()
