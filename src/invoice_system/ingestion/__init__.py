"""Public boundary for the evidence-preserving invoice-ingestion agent."""

from .models import BatchResult, IngestionResult
from .ingest import ingest, run_pipeline

# ``run_pipeline`` remains as a compatibility alias for downstream callers;
# new application code should use the clearer ``ingest`` entry point.
__all__ = ["BatchResult", "IngestionResult", "ingest", "run_pipeline"]
