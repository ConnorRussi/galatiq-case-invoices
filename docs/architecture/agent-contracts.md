# Agent Contracts

These boundaries describe what the next stage may rely on and what remains its responsibility. The contracts are represented by Pydantic models in the linked source files.

## Ingestion -> invoice history and validation

**Input:** a supported source path. **Output:** [`IngestionResult`](../../src/invoice_system/ingestion/models.py) containing immutable `SourceDocument`, optional `NormalizationResult`, optional `CritiqueResult`, status, and revision count.

Guaranteed for `ACCEPT` or `NEEDS_REVIEW`: source chunks exist, normalized output exists, populated claims have evidence paths, and the source itself was readable. Not guaranteed: arithmetic correctness, semantic validity, inventory identity, approval eligibility, or payment readiness. Validation must not treat normalization as truth merely because it is typed.

## Invoice history -> workflow and approval

**Input:** accepted/reviewable ingestion. **Output:** [`InvoiceHistoryDecision`](../../src/invoice_system/invoice_ledger.py) with canonical case key, source hash, disposition, prior payment data, and review flag.

The receiver may rely on deterministic version identity for the ledger record. A duplicate paid version must stop before validation. A new version after payment must not be treated as an ordinary payable invoice. History does not validate the invoice or decide whether a revision deserves a credit/refund.

## Ingestion -> Semantic

Validation round-trips the ingestion result through JSON, creating a detached snapshot. Semantic receives normalized fields and source evidence. It owns semantic usability, invalid values, date contradictions, negative quantities/prices, and basic line structure. It does not own arithmetic, inventory, approval, or payment.

## Semantic -> Reconciliation

Reconciliation runs only after Semantic is accepted by its critic and the status is `PASS`. It receives the original detached snapshot, not a rewritten source document. It may reason about product identity and declared arithmetic, but deterministic Decimal evidence is authoritative for calculations. It must preserve source lines and cannot invent missing claims.

## Reconciliation -> Database

Database receives consolidated items and identity mappings when available. It may assume reconciliation completed its stage, but it must still handle missing quantity, unresolved product identity, and insufficient stock. It records all attempted names and authoritative matched values. A retry candidate is not a product substitution.

## Validation -> Approval

Approval is admitted only when validation is `VALID` and the reconciliation result is `PASS`; [`run_approval`](../../src/invoice_system/approval/runner.py) enforces both. Approval receives the original source, normalization, validation/reconciliation status envelopes, and optional history. Approval applies policy and escalation. It does not repair data or redo validation.

## Approval -> Payment

The workflow proceeds only from approval `APPROVED`. It builds a `PaymentRequest` from vendor, `amount_due` or `invoice_total`, confirmed currency, invoice ID, and an idempotency key. Payment preflight rejects missing vendor, amount, currency, or invalid request data before the provider call. The provider result is local and simulated.

## Workflow -> dashboard

The dashboard accepts only saved `workflow_result.json` objects containing a status and ingestion object, plus workflow evaluation `summary.json` files. It displays facts and escaped source content. It has no contract for changing decisions, resuming runs, or submitting human review.
