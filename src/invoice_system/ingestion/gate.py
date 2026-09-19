"""Deterministic final ingestion status selection."""

from .models import CritiqueResult, IngestionResult, IngestionStatus, NormalizationResult, SourceDocument


def build_completed_result(
    *,
    source_path: str,
    source_document: SourceDocument | None,
    normalization: NormalizationResult | None,
    critique: CritiqueResult | None,
    revision_count: int,
    revision_errors: list[str] | None = None,
) -> IngestionResult:
    status = (
        IngestionStatus.ACCEPT
        if critique is not None and not critique.issues and not revision_errors
        else IngestionStatus.NEEDS_REVIEW
    )
    return IngestionResult(
        status=status,
        source_path=source_path,
        source_document=source_document,
        normalization=normalization,
        critique=critique,
        revision_count=revision_count,
        error_message=revision_errors[-1] if revision_errors else None,
    )


def build_technical_failure_result(
    *,
    source_path: str,
    error_message: str,
    source_document: SourceDocument | None = None,
    normalization: NormalizationResult | None = None,
    critique: CritiqueResult | None = None,
    revision_count: int = 0,
) -> IngestionResult:
    return IngestionResult(
        status=IngestionStatus.TECHNICAL_FAILURE,
        source_path=source_path,
        source_document=source_document,
        normalization=normalization,
        critique=critique,
        revision_count=revision_count,
        error_message=error_message,
    )
