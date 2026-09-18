from typing import TypedDict

from .models import CritiqueResult, IngestionResult, NormalizationResult, SourceDocument


class IngestionState(TypedDict):
    source_path: str
    source_document: SourceDocument | None
    normalization: NormalizationResult | None
    critique: CritiqueResult | None
    revision_count: int
    result: IngestionResult | None
