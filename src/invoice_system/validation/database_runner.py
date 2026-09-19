"""Critiqued execution boundary for inventory/database validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from invoice_system.ingestion.models import IngestionResult

from .config import MAX_CRITIC_REVISIONS
from .critic import review_stage
from .database import DEFAULT_DATABASE_PATH, RetryProposer, resolve_inventory
from .models import (
    CriticDecision,
    CriticResult,
    DatabaseValidationResult,
    ValidationStage,
)


ProgressCallback = Callable[[str], None]


@dataclass
class DatabaseExecution:
    result: DatabaseValidationResult
    critic_result: CriticResult
    critic_revision_count: int
    critic_confirmed: bool


def run_database_validation(
    ingestion: IngestionResult,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
    retry_proposer: RetryProposer | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DatabaseExecution:
    """Run bounded database-specialist and shared-critic revisions."""

    snapshot = IngestionResult.model_validate(ingestion.model_dump(mode="json"))
    revision_count = 0
    feedback = None
    previous_critic = None
    for attempt in range(MAX_CRITIC_REVISIONS + 1):
        if progress_callback is not None:
            progress_callback(
                f"database specialist attempt {attempt + 1}/{MAX_CRITIC_REVISIONS + 1} started"
            )
        result = resolve_inventory(
            snapshot,
            db_path=db_path,
            retry_proposer=retry_proposer,
            revision_feedback=feedback,
        )
        critic = review_stage(
            snapshot,
            ValidationStage.DATABASE,
            result,
            previous_critic=previous_critic,
            revision_count=revision_count,
            revision_feedback=feedback,
        )
        if progress_callback is not None:
            progress_callback(
                f"database critic: {critic.decision.value} "
                f"(revision count {revision_count})"
            )
        if critic.decision == CriticDecision.AGREE:
            return DatabaseExecution(result, critic, revision_count, True)
        if attempt == MAX_CRITIC_REVISIONS:
            break
        revision_count += 1
        feedback = critic.revision_instructions or critic.summary
        previous_critic = critic
        if progress_callback is not None:
            progress_callback("database critic requested a specialist revision")

    return DatabaseExecution(result, critic, revision_count, False)
