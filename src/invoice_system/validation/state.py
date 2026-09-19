"""LangGraph state for the semantic validation phase."""

from pathlib import Path
from typing import TypedDict

from invoice_system.ingestion.models import IngestionResult

from .models import (
    CriticResult,
    DatabaseValidationResult,
    ReconciliationResult,
    SemanticResult,
    ValidationResult,
    ValidationStage,
)


class ValidationState(TypedDict, total=False):
    # This is a deep Pydantic snapshot made at the public runner boundary. Nodes
    # only read it; source claims and the ingestion normalization are never
    # replaced by validation feedback.
    original_ingestion: IngestionResult
    current_stage: ValidationStage
    semantic_result: SemanticResult | None
    semantic_critic_result: CriticResult | None
    reconciliation_result: ReconciliationResult | None
    reconciliation_critic_result: CriticResult | None
    database_result: DatabaseValidationResult | None
    database_critic_result: CriticResult | None
    critic_result: CriticResult | None
    critic_revision_count: int
    critic_revision_exhausted: bool
    semantic_critic_revision_count: int
    reconciliation_critic_revision_count: int
    database_critic_revision_count: int
    semantic_critic_revision_exhausted: bool
    reconciliation_critic_revision_exhausted: bool
    database_critic_revision_exhausted: bool
    revision_feedback: str | None
    final_result: ValidationResult | None
    database_path: str | Path | None
