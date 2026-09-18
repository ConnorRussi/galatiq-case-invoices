"""The complete Phase 1 workflow: read_source -> normalize -> END."""

import logging

from langgraph.graph import END, START, StateGraph

from .normalizer import normalize
from .source_reader import read_source
from .state import IngestionState

logger = logging.getLogger(__name__)


def read_source_node(state: IngestionState) -> dict:
    logger.info("[read_source] %s", state["source_path"])
    return {"source_document": read_source(state["source_path"])}


def normalize_node(state: IngestionState) -> dict:
    source = state["source_document"]
    if source is None:
        raise ValueError("normalize requires a SourceDocument")
    logger.info("[normalize] %s (%s chunks)", source.filename, len(source.chunks))
    return {"normalization": normalize(source)}


def build_graph():
    graph = StateGraph(IngestionState)
    graph.add_node("read_source", read_source_node)
    graph.add_node("normalize", normalize_node)
    graph.add_edge(START, "read_source")
    graph.add_edge("read_source", "normalize")
    graph.add_edge("normalize", END)
    return graph.compile()
