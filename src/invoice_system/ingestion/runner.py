"""Official execution boundary for invoice ingestion."""

from __future__ import annotations

from pathlib import Path

from .gate import build_technical_failure_result
from .graph import MAX_REVISIONS, build_graph
from .models import CritiqueResult, IngestionResult, NormalizationResult, SourceDocument
from .run_logging import IngestionRunLogger, RunContext, create_normal_run_context


def run_ingestion(
    source_path: str | Path,
    *,
    logs_root: Path | None = None,
    artifact_context: RunContext | None = None,
    persist_artifacts: bool = True,
) -> IngestionResult:
    """Run ingestion once, persisting artifacts by default."""

    source_path_str = str(source_path)
    logger = _build_logger(source_path, logs_root, artifact_context, persist_artifacts)
    source_document: SourceDocument | None = None
    normalization: NormalizationResult | None = None
    critique_result: CritiqueResult | None = None
    revision_count = 0

    if logger is not None:
        logger.log_event("run", "started")
        logger.log_event("read_source", "started")

    try:
        final: IngestionResult | None = None
        state = {
            "source_path": source_path_str,
            "source_document": None,
            "normalization": None,
            "critique": None,
            "revision_count": 0,
            "critique_history": [],
            "critic_instability": None,
            "revision_errors": [],
            "result": None,
        }
        for update in build_graph().stream(state, stream_mode="updates"):
            if "read_source" in update:
                source_document = update["read_source"]["source_document"]
                if logger is not None:
                    logger.save_source(source_document)
                    logger.log_event(
                        "read_source",
                        "completed",
                        detail=f"Extracted {len(source_document.chunks)} source chunk(s)",
                    )
                    logger.log_event("normalize", "started", version=1)
            if "normalize" in update:
                normalization = update["normalize"]["normalization"]
                revision_count = update["normalize"]["revision_count"]
                if logger is not None:
                    logger.save_normalization(normalization, version=1)
                    logger.log_event("normalize", "completed", version=1)
                    logger.log_event("critic", "started", version=1)
            if "revise" in update:
                normalization = update["revise"]["normalization"]
                revision_count = update["revise"]["revision_count"]
                version = revision_count + 1
                if logger is not None:
                    logger.save_normalization(normalization, version=version)
                    logger.log_event("revise", "completed", version=version)
                    logger.log_event("critic", "started", version=version)
            if "critic" in update:
                critique_result = update["critic"]["critique"]
                version = revision_count + 1
                issue_count = len(critique_result.issues)
                if logger is not None:
                    logger.save_critique(critique_result, version=version)
                    logger.log_event("critic", "completed", version=version, issue_count=issue_count)
                    if issue_count and revision_count < MAX_REVISIONS:
                        logger.log_event(
                            "route",
                            "revise",
                            reason=f"{issue_count} critic issue(s) and revision budget remains",
                        )
                        logger.log_event("revise", "started", version=version + 1)
                    else:
                        reason = (
                            "Critic revision instability detected"
                            if update["critic"].get("critic_instability")
                            else "Final critique contains no issues"
                            if issue_count == 0
                            else "Revision budget exhausted"
                        )
                        logger.log_event("route", "gate", reason=reason)
            if "gate" in update:
                final = update["gate"]["result"]
                if logger is not None:
                    gate_reason = (
                        "Final critique contains no issues"
                        if final.critique is not None and not final.critique.issues
                        else "Final critique still contains issues"
                    )
                    logger.log_event("gate", "decision", status=final.status.value, reason=gate_reason)
                    logger.save_result(final)
                    logger.finish(final)
        if final is None:
            raise RuntimeError("Graph ended without an ingestion result")
        return final
    except Exception as exc:
        result = build_technical_failure_result(
            source_path=source_path_str,
            error_message=str(exc),
            source_document=source_document,
            normalization=normalization,
            critique=critique_result,
            revision_count=revision_count,
        )
        if logger is not None:
            try:
                logger.log_event(
                    "error",
                    "technical_failure",
                    stage_failed=_failure_stage(source_document, normalization, critique_result),
                    error=str(exc),
                )
                logger.save_result(result)
                logger.finish_failure(revision_count)
            except Exception as logging_exc:
                result.error_message = f"{result.error_message}; additionally failed to write artifacts: {logging_exc}"
        return result


def _build_logger(
    source_path: str | Path,
    logs_root: Path | None,
    artifact_context: RunContext | None,
    persist_artifacts: bool,
) -> IngestionRunLogger | None:
    if not persist_artifacts:
        return None
    if artifact_context is None:
        if logs_root is None:
            logs_root = Path("logs")
        artifact_context = create_normal_run_context(logs_root, source_path)
    return IngestionRunLogger(artifact_context, source_path)


def _failure_stage(
    source_document: SourceDocument | None,
    normalization: NormalizationResult | None,
    critique_result: CritiqueResult | None,
) -> str:
    if source_document is None:
        return "read_source"
    if normalization is None:
        return "normalize"
    if critique_result is None:
        return "critic"
    return "gate"
