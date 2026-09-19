"""LangGraph orchestration for Semantic, Reconciliation, and Database validation."""

import logging

from langgraph.graph import END, START, StateGraph

from . import config
from .critic import review_stage
from .database import resolve_inventory
from .models import (
    CriticDecision,
    ReconciliationStatus,
    DatabaseStatus,
    SemanticStatus,
    ValidationIssue,
    ValidationResult,
    ValidationStage,
    ValidationStatus,
)
from .reconciliation import validate_reconciliation
from .semantic import validate_semantics
from .state import ValidationState

logger = logging.getLogger(__name__)


def semantic_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    if ingestion is None:
        raise ValueError("semantic requires original_ingestion")
    result = validate_semantics(ingestion, revision_feedback=state.get("revision_feedback"), previous_result=state.get("semantic_result"))
    logger.info("[semantic] Proposed %s with %s issue(s)", result.status.value, len(result.issues))
    return {"semantic_result": result, "current_stage": ValidationStage.SEMANTIC, "critic_revision_count": state.get("semantic_critic_revision_count", 0), "semantic_critic_revision_count": state.get("semantic_critic_revision_count", 0)}


def semantic_critic_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    semantic_result = state.get("semantic_result")
    if ingestion is None or semantic_result is None:
        raise ValueError("semantic_critic requires ingestion and semantic_result")
    revision_count = state.get("semantic_critic_revision_count", 0)
    result = review_stage(ingestion, ValidationStage.SEMANTIC, semantic_result, previous_critic=state.get("semantic_critic_result") or state.get("critic_result"), revision_count=revision_count, revision_feedback=state.get("revision_feedback"))
    logger.info("[semantic_critic] %s: %s", result.decision.value, result.summary)
    updates: dict = {"critic_result": result, "semantic_critic_result": result}
    if result.decision == CriticDecision.AGREE:
        updates["revision_feedback"] = None
    if result.decision == CriticDecision.REVISE:
        if revision_count < config.MAX_CRITIC_REVISIONS:
            updates["semantic_critic_revision_count"] = revision_count + 1
            updates["critic_revision_count"] = revision_count + 1
            updates["revision_feedback"] = result.revision_instructions or result.summary
        else:
            updates["semantic_critic_revision_exhausted"] = True
            updates["critic_revision_exhausted"] = True
            updates["revision_feedback"] = result.revision_instructions or result.summary
    return updates


def reconciliation_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    if ingestion is None:
        raise ValueError("reconciliation requires original_ingestion")
    result = validate_reconciliation(ingestion, revision_feedback=state.get("revision_feedback"), previous_result=state.get("reconciliation_result"))
    logger.info("[reconciliation] Proposed %s with %s issue(s)", result.status.value, len(result.issues))
    return {"reconciliation_result": result, "current_stage": ValidationStage.RECONCILIATION, "reconciliation_critic_revision_count": state.get("reconciliation_critic_revision_count", 0)}


def reconciliation_critic_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    reconciliation_result = state.get("reconciliation_result")
    if ingestion is None or reconciliation_result is None:
        raise ValueError("reconciliation_critic requires ingestion and reconciliation_result")
    revision_count = state.get("reconciliation_critic_revision_count", 0)
    result = review_stage(ingestion, ValidationStage.RECONCILIATION, reconciliation_result, previous_critic=state.get("reconciliation_critic_result"), revision_count=revision_count, revision_feedback=state.get("revision_feedback"))
    logger.info("[reconciliation_critic] %s: %s", result.decision.value, result.summary)
    updates: dict = {"critic_result": result, "reconciliation_critic_result": result}
    if result.decision == CriticDecision.REVISE:
        if revision_count < config.MAX_CRITIC_REVISIONS:
            updates["reconciliation_critic_revision_count"] = revision_count + 1
            updates["critic_revision_count"] = revision_count + 1
            updates["revision_feedback"] = result.revision_instructions or result.summary
        else:
            updates["reconciliation_critic_revision_exhausted"] = True
            updates["critic_revision_exhausted"] = True
            updates["revision_feedback"] = result.revision_instructions or result.summary
    return updates


def database_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    if ingestion is None:
        raise ValueError("database requires original_ingestion")
    result = resolve_inventory(
        ingestion,
        reconciliation_result=state.get("reconciliation_result"),
        revision_feedback=state.get("revision_feedback"),
    )
    logger.info("[database] Proposed %s with %s issue(s)", result.status.value, len(result.issues))
    return {
        "database_result": result,
        "current_stage": ValidationStage.DATABASE,
        "database_critic_revision_count": state.get("database_critic_revision_count", 0),
    }


def database_critic_node(state: ValidationState) -> dict:
    ingestion = state.get("original_ingestion")
    database_result = state.get("database_result")
    if ingestion is None or database_result is None:
        raise ValueError("database_critic requires ingestion and database_result")
    revision_count = state.get("database_critic_revision_count", 0)
    result = review_stage(
        ingestion,
        ValidationStage.DATABASE,
        database_result,
        previous_critic=state.get("database_critic_result"),
        revision_count=revision_count,
        revision_feedback=state.get("revision_feedback"),
    )
    logger.info("[database_critic] %s: %s", result.decision.value, result.summary)
    updates: dict = {"critic_result": result, "database_critic_result": result}
    if result.decision == CriticDecision.AGREE:
        updates["revision_feedback"] = None
    if result.decision == CriticDecision.REVISE:
        if revision_count < config.MAX_CRITIC_REVISIONS:
            updates["database_critic_revision_count"] = revision_count + 1
            updates["critic_revision_count"] = revision_count + 1
            updates["revision_feedback"] = result.revision_instructions or result.summary
        else:
            updates["database_critic_revision_exhausted"] = True
            updates["critic_revision_exhausted"] = True
            updates["revision_feedback"] = result.revision_instructions or result.summary
    return updates


def _finalize(state: ValidationState, *, status: ValidationStatus, reason: str, denied_by: ValidationStage | None) -> dict:
    ingestion = state.get("original_ingestion")
    semantic_result = state.get("semantic_result")
    if ingestion is None or semantic_result is None:
        raise ValueError("finalize requires complete validation state")
    reconciliation_result = state.get("reconciliation_result")
    database_result = state.get("database_result")
    issues = (
        list(database_result.issues)
        if database_result is not None
        else list(reconciliation_result.issues)
        if reconciliation_result is not None
        else list(semantic_result.issues)
    )
    return {"final_result": ValidationResult(
        status=status,
        reason=reason,
        denied_by=denied_by,
        issues=issues,
        semantic_result=semantic_result,
        ingestion=ingestion,
        semantic_critic_result=state.get("semantic_critic_result"),
        reconciliation_result=reconciliation_result,
        reconciliation_critic_result=state.get("reconciliation_critic_result"),
        database_result=database_result,
        database_critic_result=state.get("database_critic_result"),
    )}


def finalize_valid_node(state: ValidationState) -> dict:
    reason = (
        "database_pass" if state.get("database_result") is not None
        else "reconciliation_pass" if state.get("reconciliation_result") is not None
        else "semantic_pass"
    )
    result = _finalize(state, status=ValidationStatus.VALID, reason=reason, denied_by=None)
    logger.info("[finalize] Validation %s", result["final_result"].status.value)
    return result


def finalize_denied_node(state: ValidationState) -> dict:
    stage = (
        ValidationStage.DATABASE if state.get("database_result") is not None
        else ValidationStage.RECONCILIATION if state.get("reconciliation_result") is not None
        else ValidationStage.SEMANTIC
    )
    result = _finalize(state, status=ValidationStatus.DENIED, reason=f"{stage.value}_denied", denied_by=stage)
    logger.info("[finalize] Validation %s", result["final_result"].status.value)
    return result


def finalize_unresolved_node(state: ValidationState) -> dict:
    stage = (
        ValidationStage.DATABASE if state.get("database_result") is not None
        else ValidationStage.RECONCILIATION if state.get("reconciliation_result") is not None
        else ValidationStage.SEMANTIC
    )
    if stage == ValidationStage.DATABASE:
        result = state.get("database_result")
        if result is None:
            raise ValueError("finalize_unresolved requires database_result")
        result = result.model_copy(deep=True)
        result.issues.append(ValidationIssue(code="unresolved_validation", message="The database specialist and critic did not resolve their disagreement within the revision limit."))
        state_copy = dict(state)
        state_copy["database_result"] = result
    elif stage == ValidationStage.RECONCILIATION:
        result = state.get("reconciliation_result")
        if result is None:
            raise ValueError("finalize_unresolved requires reconciliation_result")
        result = result.model_copy(deep=True)
        result.issues.append(ValidationIssue(code="unresolved_validation", message="The reconciliation specialist and critic did not resolve their disagreement within the revision limit."))
        state_copy = dict(state)
        state_copy["reconciliation_result"] = result
    else:
        result = state.get("semantic_result")
        if result is None:
            raise ValueError("finalize_unresolved requires semantic_result")
        result = result.model_copy(deep=True)
        result.issues.append(ValidationIssue(code="unresolved_validation", message="The semantic specialist and critic did not resolve their disagreement within the revision limit."))
        state_copy = dict(state)
        state_copy["semantic_result"] = result
    final = _finalize(state_copy, status=ValidationStatus.DENIED, reason="unresolved_validation", denied_by=stage)
    logger.warning("[finalize] Validation DENIED: unresolved critic disagreement")
    return final


def route_after_semantic_critic(state: ValidationState, *, include_reconciliation: bool) -> str:
    critic_result = state.get("semantic_critic_result") or state.get("critic_result")
    semantic_result = state.get("semantic_result")
    if critic_result is None or semantic_result is None:
        raise ValueError("route_after_semantic_critic requires critic and semantic results")
    if critic_result.decision == CriticDecision.REVISE:
        if state.get("semantic_critic_revision_exhausted", False):
            return "finalize_unresolved"
        return "semantic" if state.get("semantic_critic_revision_count", 0) <= config.MAX_CRITIC_REVISIONS else "finalize_unresolved"
    if semantic_result.status == SemanticStatus.DENY:
        return "finalize_denied"
    return "reconciliation" if include_reconciliation else "finalize_valid"


def route_after_reconciliation_critic(state: ValidationState) -> str:
    critic_result = state.get("reconciliation_critic_result")
    reconciliation_result = state.get("reconciliation_result")
    if critic_result is None or reconciliation_result is None:
        raise ValueError("route_after_reconciliation_critic requires critic and reconciliation results")
    if critic_result.decision == CriticDecision.REVISE:
        if state.get("reconciliation_critic_revision_exhausted", False):
            return "finalize_unresolved"
        return "reconciliation" if state.get("reconciliation_critic_revision_count", 0) <= config.MAX_CRITIC_REVISIONS else "finalize_unresolved"
    if reconciliation_result.status == ReconciliationStatus.DENY:
        return "finalize_denied"
    return "database" if state.get("include_database", False) else "finalize_valid"


def route_after_database_critic(state: ValidationState) -> str:
    critic_result = state.get("database_critic_result")
    database_result = state.get("database_result")
    if critic_result is None or database_result is None:
        raise ValueError("route_after_database_critic requires critic and database results")
    if critic_result.decision == CriticDecision.REVISE:
        if state.get("database_critic_revision_exhausted", False):
            return "finalize_unresolved"
        return "database" if state.get("database_critic_revision_count", 0) <= config.MAX_CRITIC_REVISIONS else "finalize_unresolved"
    if database_result.status == DatabaseStatus.DENY:
        return "finalize_denied"
    return "finalize_valid"


def route_after_critic(state: ValidationState) -> str:
    """Backward-compatible Phase 1 route helper."""
    return route_after_semantic_critic(state, include_reconciliation=False)


def build_graph(*, include_reconciliation: bool = False, include_database: bool = False):
    include_reconciliation = include_reconciliation or include_database
    graph = StateGraph(ValidationState)
    graph.add_node("semantic", semantic_node)
    graph.add_node("semantic_critic", semantic_critic_node)
    graph.add_node("finalize_valid_for_phase_1", finalize_valid_node)
    graph.add_node("finalize_denied", finalize_denied_node)
    graph.add_node("finalize_unresolved", finalize_unresolved_node)
    graph.add_edge(START, "semantic")
    graph.add_edge("semantic", "semantic_critic")
    if include_reconciliation:
        graph.add_node("reconciliation", reconciliation_node)
        graph.add_node("reconciliation_critic", reconciliation_critic_node)
        if include_database:
            graph.add_node("database", database_node)
            graph.add_node("database_critic", database_critic_node)
        graph.add_conditional_edges("semantic_critic", lambda state: route_after_semantic_critic(state, include_reconciliation=True), {"semantic": "semantic", "reconciliation": "reconciliation", "finalize_denied": "finalize_denied", "finalize_unresolved": "finalize_unresolved"})
        graph.add_edge("reconciliation", "reconciliation_critic")
        reconciliation_routes = {"reconciliation": "reconciliation", "finalize_valid": "finalize_valid_for_phase_1", "finalize_denied": "finalize_denied", "finalize_unresolved": "finalize_unresolved"}
        if include_database:
            reconciliation_routes["database"] = "database"
        graph.add_conditional_edges("reconciliation_critic", lambda state: route_after_reconciliation_critic({**state, "include_database": include_database}), reconciliation_routes)
        if include_database:
            graph.add_edge("database", "database_critic")
            graph.add_conditional_edges("database_critic", route_after_database_critic, {"database": "database", "finalize_valid": "finalize_valid_for_phase_1", "finalize_denied": "finalize_denied", "finalize_unresolved": "finalize_unresolved"})
    else:
        graph.add_conditional_edges("semantic_critic", lambda state: route_after_semantic_critic(state, include_reconciliation=False), {"semantic": "semantic", "finalize_valid": "finalize_valid_for_phase_1", "finalize_denied": "finalize_denied", "finalize_unresolved": "finalize_unresolved"})
    graph.add_edge("finalize_valid_for_phase_1", END)
    graph.add_edge("finalize_denied", END)
    graph.add_edge("finalize_unresolved", END)
    return graph.compile()
