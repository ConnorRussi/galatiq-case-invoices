# Data Models

## Source and ingestion

[`ingestion/models.py`](../../src/invoice_system/ingestion/models.py) defines frozen `SourceChunk` and `SourceDocument`, typed `NormalizedInvoice` and `NormalizedLineItem`, `FieldEvidence`, `NormalizationResult`, `CritiqueIssue`, `CritiqueResult`, and `IngestionResult`. Money and quantities use `Decimal`; dates use `date`.

`SourceChunk` carries an ID, text, optional page/row, kind, and extraction method. `FieldEvidence` points from a relative invoice field path to source chunk IDs and optional quoted source text. `additional_fields` preserves meaningful fields outside the primary schema.

## Validation

[`validation/models.py`](../../src/invoice_system/validation/models.py) defines `SemanticResult`, `ReconciliationResult`, `DatabaseValidationResult`, shared `ValidationIssue`, `CriticResult`, and the final `ValidationResult`. Reconciliation exposes `ProductIdentityMapping`, `ConsolidatedItem`, and `ReconciliationCalculation`. Database exposes one `DatabaseResult` per requested product with attempted names, matched item, requested quantity, stock, and sufficiency.

## Approval, payment, workflow

[`approval/models.py`](../../src/invoice_system/approval/models.py) defines `ApprovalRequest`, `BusinessRuleDecision`, `VPDecision`, and `ApprovalResult`. [`payment/models.py`](../../src/invoice_system/payment/models.py) defines `PaymentRequest`, `PaymentResult`, and `PaymentStatus`. [`workflow.py`](../../src/invoice_system/workflow.py) defines `WorkflowStatus` and `WorkflowResult`, which retains completed stage results and the stop point.

## Durable representations

Run loggers serialize models as JSON, rendering dates as ISO dates and Decimal values as strings. `events.jsonl` records ordered stage events. The invoice ledger has an `invoice_versions` table for source hashes, identity, revision, workflow/payment status, transaction ID, amount, and supersession. The inventory database is a separate SQLite store with `inventory(item, stock)` records.
