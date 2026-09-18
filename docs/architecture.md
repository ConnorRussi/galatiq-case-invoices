# System architecture

## Purpose

The system reads an invoice document, preserves the extracted source as
immutable chunks, asks a configured chat model for a structured invoice
normalization with field evidence, critiques that result against the source,
and performs at most two targeted revisions before producing a terminal result.

## Runtime boundaries

| Boundary | Implementation | Responsibility | Handoff |
| --- | --- | --- | --- |
| CLI | [`main.py`](../main.py) | Parse one invoice or evaluation mode; load `.env`; print status | `run_ingestion` or `run_evaluation` |
| Execution | [`runner.py`](../src/invoice_system/ingestion/runner.py) | Stream updates, persist artifacts, convert exceptions | `IngestionResult` |
| Workflow | [`graph.py`](../src/invoice_system/ingestion/graph.py) | Order stages and route critique/revision | graph state |
| Source | [`source_reader.py`](../src/invoice_system/ingestion/source_reader.py) | Read formats without invoice semantics | `SourceDocument` |
| Model | [`normalizer.py`](../src/invoice_system/ingestion/normalizer.py), [`agent_runtime.py`](../src/invoice_system/agent_runtime.py) | Produce normalization and revisions | `NormalizationResult` |
| Review | [`critic.py`](../src/invoice_system/ingestion/critic.py) | Find fidelity issues | `CritiqueResult` |
| Terminal decision | [`gate.py`](../src/invoice_system/ingestion/gate.py) | Map critique or exception to status | `IngestionResult` |
| Observability | [`run_logging.py`](../src/invoice_system/ingestion/run_logging.py) | Write stage artifacts and events | `logs/runs/<run_id>/` |
| Evaluation | [`evaluation.py`](../src/invoice_system/ingestion/evaluation.py) | Compare goldens and run challenges | evaluation report |
| Semantic validation | [`validation/runner.py`](../src/invoice_system/validation/runner.py) | Review an ingestion result for semantic invoice validity | `ValidationResult` |
| Shared validation critic | [`validation/critic.py`](../src/invoice_system/validation/critic.py) | Review specialist work and route revisions | `CriticResult` |

## Data flow

`source path -> SourceDocument -> NormalizationResult -> CritiqueResult ->
optional revised NormalizationResult -> IngestionResult -> SemanticResult ->
CriticResult -> ValidationResult`

The source is never rewritten by normalization or critique. Evidence points
back to source chunk IDs and optional quoted source text. Financial values use
`Decimal`; JSON-safe model serialization preserves precision.

## Explicit non-goals today

The original case narrative mentions inventory validation, approval, banking,
and payment. Reconciliation, database, business/acceptance, and payment agents
are not implemented in the current package. Their documentation extension points
live under
[`docs/agents/`](agents/), and new code must add a real boundary, contract,
tests, and documentation before calling a domain implemented.
