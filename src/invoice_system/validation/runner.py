"""Public execution boundary for semantic validation."""

from __future__ import annotations

from pathlib import Path

from invoice_system.ingestion.models import IngestionResult
from invoice_system.ingestion.run_logging import (
    RunContext,
    append_event,
    create_normal_run_context,
    write_artifact,
)

from .config import MAX_CRITIC_REVISIONS
from .graph import build_graph
from .models import ValidationResult


def run_validation(
    ingestion: IngestionResult,
    *,
    logs_root: Path | None = None,
    artifact_context: RunContext | None = None,
    persist_artifacts: bool = True,
) -> ValidationResult:
    """Run semantic validation from one immutable snapshot of ingestion output."""

    if ingestion.normalization is None:
        raise ValueError("Semantic validation requires an ingestion normalization")

    # Round-trip through JSON to detach validation state from the mutable
    # ingestion object owned by callers. Validation nodes only read this copy.
    snapshot = IngestionResult.model_validate(ingestion.model_dump(mode="json"))
    context = None
    if persist_artifacts:
        if artifact_context is None:
            context = create_normal_run_context(logs_root or Path("logs"), ingestion.source_path)
            context.run_dir.mkdir(parents=True, exist_ok=True)
            write_artifact(
                context.run_dir,
                "validation_run.json",
                {"run_id": context.run_id, "source_path": ingestion.source_path},
            )
        else:
            context = artifact_context
        write_artifact(context.run_dir, "validation_input.json", snapshot)
        append_event(context.run_dir, "validation", "started", stage="semantic")

    state = {
        "original_ingestion": snapshot,
        "current_stage": "semantic",
        "semantic_result": None,
        "critic_result": None,
        "critic_revision_count": 0,
        "critic_revision_exhausted": False,
        "revision_feedback": None,
        "final_result": None,
    }
    final: ValidationResult | None = None
    for update in build_graph().stream(state, stream_mode="updates"):
        if "semantic" in update:
            semantic = update["semantic"]["semantic_result"]
            version = update["semantic"].get("critic_revision_count", 0) + 1
            if context is not None:
                write_artifact(context.run_dir, f"semantic_v{version}.json", semantic)
                append_event(
                    context.run_dir,
                    "semantic",
                    "completed",
                    proposed_status=semantic.status.value,
                    issue_count=len(semantic.issues),
                    version=version,
                )
                append_event(context.run_dir, "semantic_critic", "started", version=version)
        if "semantic_critic" in update:
            critic = update["semantic_critic"]["critic_result"]
            revision_count = update["semantic_critic"].get("critic_revision_count", 0)
            version = revision_count + 1
            if context is not None:
                write_artifact(context.run_dir, f"semantic_critic_v{version}.json", critic)
                append_event(
                    context.run_dir,
                    "semantic_critic",
                    "completed",
                    decision=critic.decision.value,
                    reason=critic.revision_instructions or critic.summary,
                    revision_count=revision_count,
                    version=version,
                )
                if (
                    critic.decision.value == "REVISE"
                    and revision_count <= MAX_CRITIC_REVISIONS
                    and not update["semantic_critic"].get("critic_revision_exhausted", False)
                ):
                    append_event(context.run_dir, "route", "revise", revision_count=revision_count)
                    append_event(context.run_dir, "semantic", "started", version=version + 1)
        for node_name in ("finalize_valid_for_phase_1", "finalize_denied", "finalize_unresolved"):
            if node_name in update:
                final = update[node_name]["final_result"]
                if context is not None:
                    write_artifact(context.run_dir, "validation_result.json", final)
                    append_event(
                        context.run_dir,
                        "validation",
                        "completed",
                        status=final.status.value,
                        reason=final.reason,
                    )
                break

    if final is None:
        raise RuntimeError("Validation graph ended without a final result")
    return final
