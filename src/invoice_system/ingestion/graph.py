"""Ingestion workflow with read-only critique and bounded revision."""

import logging

from langgraph.graph import END, START, StateGraph

from .critic import critique
from .gate import build_completed_result
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
    return {"normalization": normalization, "revision_count": 0}


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
    issue_count = len(result.issues)
    if issue_count:
        logger.info("[critic] Found %s fidelity issue%s", issue_count, "" if issue_count == 1 else "s")
    else:
        logger.info("[critic] No fidelity issues")
    return {"critique": result}


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
    if not current_critique.issues:
        return "gate"
    if state["revision_count"] < MAX_REVISIONS:
        return "revise"
    return "gate"


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
