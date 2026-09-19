"""Isolated Phase 2 execution boundary used by reconciliation evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from invoice_system.ingestion.models import IngestionResult
from invoice_system.ingestion.run_logging import RunContext, append_event, write_artifact

from .config import MAX_CRITIC_REVISIONS
from .critic import review_stage
from .models import CriticDecision, CriticResult, ReconciliationResult, ValidationStage
from .reconciliation import validate_reconciliation


ProgressCallback = Callable[[str], None]


def _execution_payload(execution: ReconciliationExecution) -> dict:
    return {
        "result": execution.result,
        "critic_result": execution.critic_result,
        "critic_revision_count": execution.critic_revision_count,
        "critic_confirmed": execution.critic_confirmed,
    }


@dataclass
class ReconciliationExecution:
    result: ReconciliationResult
    critic_result: CriticResult
    critic_revision_count: int
    critic_confirmed: bool


def run_reconciliation(
    ingestion: IngestionResult,
    *,
    artifact_context: RunContext | None = None,
    persist_artifacts: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> ReconciliationExecution:
    """Run only Phase 2 with a caller-supplied Semantic PASS context."""

    if ingestion.normalization is None:
        raise ValueError("Reconciliation requires an ingestion normalization")
    snapshot = IngestionResult.model_validate(ingestion.model_dump(mode="json"))
    revision_count = 0
    feedback = None
    previous_result = None
    previous_critic = None
    for attempt in range(MAX_CRITIC_REVISIONS + 1):
        attempt_number = attempt + 1
        if progress_callback is not None:
            progress_callback(
                f"specialist attempt {attempt_number}/{MAX_CRITIC_REVISIONS + 1} started"
            )
        result = validate_reconciliation(snapshot, revision_feedback=feedback, previous_result=previous_result)
        if progress_callback is not None:
            progress_callback(
                f"specialist attempt {attempt_number} proposed {result.status.value} "
                f"with {len(result.issues)} issue(s)"
            )
        if artifact_context is not None and persist_artifacts:
            write_artifact(artifact_context.run_dir, f"reconciliation_v{attempt + 1}.json", result)
            append_event(artifact_context.run_dir, "reconciliation", "completed", proposed_status=result.status.value, issue_count=len(result.issues), version=attempt + 1)
        critic = review_stage(snapshot, ValidationStage.RECONCILIATION, result, previous_critic=previous_critic, revision_count=revision_count, revision_feedback=feedback)
        if progress_callback is not None:
            progress_callback(
                f"critic attempt {attempt_number}: {critic.decision.value} "
                f"(revision count {revision_count})"
            )
        if artifact_context is not None and persist_artifacts:
            write_artifact(artifact_context.run_dir, f"reconciliation_critic_v{attempt + 1}.json", critic)
            append_event(artifact_context.run_dir, "reconciliation_critic", "completed", decision=critic.decision.value, revision_count=revision_count, version=attempt + 1)
        if critic.decision == CriticDecision.AGREE:
            execution = ReconciliationExecution(result, critic, revision_count, True)
            if artifact_context is not None and persist_artifacts:
                write_artifact(artifact_context.run_dir, "reconciliation_result.json", _execution_payload(execution))
            return execution
        if attempt == MAX_CRITIC_REVISIONS:
            if progress_callback is not None:
                progress_callback("critic revision limit reached; finalizing unresolved")
            break
        revision_count += 1
        feedback = critic.revision_instructions or critic.summary
        previous_result = result
        previous_critic = critic
        if progress_callback is not None:
            progress_callback("critic requested a specialist revision")
    execution = ReconciliationExecution(result, critic, revision_count, False)
    if artifact_context is not None and persist_artifacts:
        write_artifact(artifact_context.run_dir, "reconciliation_result.json", _execution_payload(execution))
    return execution
