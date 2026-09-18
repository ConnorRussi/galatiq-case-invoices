"""LangGraph state for the semantic validation phase."""

from typing import TypedDict

from invoice_system.ingestion.models import IngestionResult

from .models import CriticResult, SemanticResult, ValidationResult, ValidationStage


class ValidationState(TypedDict, total=False):
    # This is a deep Pydantic snapshot made at the public runner boundary. Nodes
    # only read it; source claims and the ingestion normalization are never
    # replaced by validation feedback.
    original_ingestion: IngestionResult
    current_stage: ValidationStage
    semantic_result: SemanticResult | None
    critic_result: CriticResult | None
    critic_revision_count: int
    critic_revision_exhausted: bool
    revision_feedback: str | None
    final_result: ValidationResult | None
