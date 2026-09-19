"""Ingestion workflow with read-only critique and bounded revision."""

import logging

from langgraph.graph import END, START, StateGraph

from .critic import critique
from .gate import build_completed_result
from .models import CritiqueIssue, CritiqueResult
from .normalizer import normalize, revise_normalization
from .source_reader import read_source
from .state import IngestionState

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2


def read_source_node(state: IngestionState) -> dict:
    logger.info("[read_source] Reading %s", state["source_path"])
    return {"source_document": read_source(state["source_path"])}


def normalize_node(state: IngestionState) -> dict:
    source = state["source_document"]
    if source is None:
        raise ValueError("normalize requires a SourceDocument")
    logger.info("[normalize] Creating normalized invoice")
    normalization = normalize(source)
    logger.info("[normalize] Complete")
    return {
        "normalization": normalization,
        "revision_count": 0,
        "critique_history": [],
        "critic_instability": None,
    }


def critic_node(state: IngestionState) -> dict:
    source = state["source_document"]
    normalization = state["normalization"]
    if source is None or normalization is None:
        raise ValueError("critic requires a SourceDocument and NormalizationResult")
    revision_count = state["revision_count"]
    if revision_count:
        logger.info("[critic] Reviewing revision %s", revision_count)
    else:
        logger.info("[critic] Reviewing normalization")
    result = critique(source, normalization)
    instability = _find_critique_instability(state["critique_history"], normalization, result)
    if instability:
        result = CritiqueResult(
            issues=[
                *result.issues,
                CritiqueIssue(
                    issue_type="structure_mismatch",
                    field_path=None,
                    message=instability,
                    proposed_value=None,
                ),
            ],
            summary="Critic revision history is internally inconsistent.",
        )
    issue_count = len(result.issues)
    if issue_count:
        logger.info("[critic] Found %s fidelity issue%s", issue_count, "" if issue_count == 1 else "s")
    else:
        logger.info("[critic] No fidelity issues")
    return {
        "critique": result,
        "critique_history": [*state["critique_history"], result],
        "critic_instability": instability,
    }


def revise_node(state: IngestionState) -> dict:
    source = state["source_document"]
    normalization = state["normalization"]
    current_critique = state["critique"]
    if source is None or normalization is None or current_critique is None:
        raise ValueError("revise requires source, normalization, and critique")
    revision_count = state["revision_count"] + 1
    logger.info("[revise] Revision %s/%s", revision_count, MAX_REVISIONS)
    revised = revise_normalization(source, normalization, current_critique)
    logger.info("[revise] Complete")
    return {"normalization": revised, "revision_count": revision_count}


def gate_node(state: IngestionState) -> dict:
    result = build_completed_result(
        source_path=state["source_path"],
        source_document=state["source_document"],
        normalization=state["normalization"],
        critique=state["critique"],
        revision_count=state["revision_count"],
    )
    logger.info("[gate] %s", result.status.name)
    return {"result": result}


def route_critique(state: IngestionState) -> str:
    current_critique = state["critique"]
    if current_critique is None:
        raise ValueError("route_critique requires a CritiqueResult")
    if state["critic_instability"]:
        return "gate"
    if not current_critique.issues:
        return "gate"
    if state["revision_count"] < MAX_REVISIONS:
        return "revise"
    return "gate"


def _find_critique_instability(history, normalization, current):
    """Detect a direct reversal after a requested correction was applied."""
    if not history:
        return None
    for current_issue in current.issues:
        if not current_issue.field_path:
            continue
        current_proposal = current_issue.proposed_value
        for previous_review in history:
            for previous_issue in previous_review.issues:
                if previous_issue.field_path != current_issue.field_path:
                    continue
                previous_proposal = previous_issue.proposed_value
                current_value = _candidate_path_value(normalization, current_issue.field_path)
                if current_value != previous_proposal:
                    continue
                if current_proposal == previous_proposal:
                    continue
                return (
                    f"Critic reversal on {current_issue.field_path}: a prior review requested "
                    f"{previous_proposal!r}, the candidate applied it, and a later review "
                    f"requested {current_proposal!r} without new source evidence."
                )
    return None


def _candidate_path_value(normalization, path):
    value = normalization.model_dump(mode="json") if path.startswith("evidence") else normalization.invoice.model_dump(mode="json")
    return _path_value(value, path)


def _path_value(value, path):
    for part in path.split("."):
        if "[" in part:
            name, index_text = part.rstrip("]").split("[")
            if not isinstance(value, dict) or name not in value:
                return object()
            value = value[name]
            index = int(index_text)
            if not isinstance(value, list) or index >= len(value):
                return object()
            value = value[index]
        else:
            if not isinstance(value, dict) or part not in value:
                return object()
            value = value[part]
    return value


def build_graph():
    graph = StateGraph(IngestionState)
    graph.add_node("read_source", read_source_node)
    graph.add_node("normalize", normalize_node)
    graph.add_node("critic", critic_node)
    graph.add_node("revise", revise_node)
    graph.add_node("gate", gate_node)
    graph.add_edge(START, "read_source")
    graph.add_edge("read_source", "normalize")
    graph.add_edge("normalize", "critic")
    graph.add_conditional_edges("critic", route_critique, {"revise": "revise", "gate": "gate"})
    graph.add_edge("revise", "critic")
    graph.add_edge("gate", END)
    return graph.compile()
