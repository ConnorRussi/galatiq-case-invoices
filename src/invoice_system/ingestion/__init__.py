"""The self-contained, evidence-preserving invoice-ingestion agent boundary."""

from .models import BatchResult, IngestionResult
from .workflow import run_pipeline

__all__ = ["BatchResult", "IngestionResult", "run_pipeline"]
