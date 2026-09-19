# System architecture

## Purpose

The system reads an invoice document, preserves the extracted source as
immutable chunks, asks a configured chat model for a structured invoice
normalization with field evidence, critiques that result against the source,
and performs at most two targeted revisions before validation. Validation then
reviews Semantic, Reconciliation, and Database concerns. Valid invoices enter
Business Rule/optional VP approval, and approved invoices enter local mock payment.

## Runtime boundaries

| Boundary | Implementation | Responsibility | Handoff |
| --- | --- | --- | --- |
| CLI | [`main.py`](../main.py) | Parse one invoice or evaluation mode; load `.env`; print human progress and final outcome | `run_invoice_workflow` or an isolated evaluator |
| End-to-end workflow | [`workflow.py`](../src/invoice_system/workflow.py) | Fail-closed routing, stage handoffs, terminal result, and shared audit context | `WorkflowResult` |
| Execution | [`runner.py`](../src/invoice_system/ingestion/runner.py) | Stream updates, persist artifacts, convert exceptions | `IngestionResult` |
| Workflow | [`graph.py`](../src/invoice_system/ingestion/graph.py) | Order stages and route critique/revision | graph state |
| Source | [`source_reader.py`](../src/invoice_system/ingestion/source_reader.py) | Read formats without invoice semantics | `SourceDocument` |
| Model | [`normalizer.py`](../src/invoice_system/ingestion/normalizer.py), [`agent_runtime.py`](../src/invoice_system/agent_runtime.py) | Produce normalization and revisions | `NormalizationResult` |
| Review | [`critic.py`](../src/invoice_system/ingestion/critic.py) | Find fidelity issues | `CritiqueResult` |
| Terminal decision | [`gate.py`](../src/invoice_system/ingestion/gate.py) | Map critique or exception to status | `IngestionResult` |
| Observability | [`run_logging.py`](../src/invoice_system/ingestion/run_logging.py) | Write stage artifacts and events | `logs/runs/<run_id>/` |
| Evaluation | [`evaluation.py`](../src/invoice_system/ingestion/evaluation.py) | Compare goldens and run challenges | evaluation report |
| Validation Agent evaluation | [`validation/evaluation.py`](../src/invoice_system/validation/evaluation.py) | Run trusted inputs through Semantic -> Reconciliation -> Database and compare the growing truth set | `logs/evals/<evaluation_id>/` |
| Validation | [`validation/runner.py`](../src/invoice_system/validation/runner.py) | Run the Semantic boundary or full Semantic -> Reconciliation -> Database graph | `ValidationResult` |
| Shared validation critic | [`validation/critic.py`](../src/invoice_system/validation/critic.py) | Review specialist work and route revisions | `CriticResult` |
| Database validation | [`validation/database_runner.py`](../src/invoice_system/validation/database_runner.py) | Run bounded bulk inventory lookup and shared-critic review | `DatabaseExecution` |
| Approval | [`approval/graph.py`](../src/invoice_system/approval/graph.py), [`approval/runner.py`](../src/invoice_system/approval/runner.py) | Apply business policy and route escalations to VP review | `ApprovalResult` |
| Approval evaluation | [`approval/evaluation.py`](../src/invoice_system/approval/evaluation.py) | Score direct decisions, VP routing, and final buckets | `logs/evals/<evaluation_id>/approval/` |
| Payment | [`payment/runner.py`](../src/invoice_system/payment/runner.py) | Execute the local mock payment after approval and persist its result | `PaymentResult` |

## Data flow

`source path -> SourceDocument -> NormalizationResult -> CritiqueResult ->
optional revised NormalizationResult -> IngestionResult -> SemanticResult ->
CriticResult -> ReconciliationResult -> CriticResult -> DatabaseResult ->
CriticResult -> ValidationResult -> ApprovalResult -> PaymentResult -> WorkflowResult`

The approval handoff is `trusted VALID/PASS inputs -> ApprovalRequest ->
Business Rule Agent -> optional VP Agent -> ApprovalResult`. Only `APPROVED`
continues to payment. Validation denial, approval rejection, and technical failure
all stop before payment.

The source is never rewritten by normalization or critique. Evidence points
back to source chunk IDs and optional quoted source text. Financial values use
`Decimal`; JSON-safe model serialization preserves precision.

## Payment boundary

Payment is intentionally local and simulated. It records the vendor, selected
amount (`amount_due`, then `invoice_total`), required source-confirmed currency,
transaction ID, and outcome, but it does not contact a bank or external payment
provider. Missing currency is a fail-closed preflight failure and never reaches
the provider.
