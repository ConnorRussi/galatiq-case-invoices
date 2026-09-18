from typing import TypedDict

from .models import NormalizationResult, SourceDocument


class IngestionState(TypedDict):
    source_path: str
    source_document: SourceDocument | None
    normalization: NormalizationResult | None
