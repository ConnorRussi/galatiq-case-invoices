# Invoice History And Idempotency

## Purpose

Invoice history is a deterministic business-identity boundary, not an LLM agent. [`InvoiceLedger`](../../src/invoice_system/invoice_ledger.py) stores source hashes, canonical vendor/invoice-number keys, revisions, workflow status, payment status, and transaction IDs.

## Inputs And Outputs

Input is an ingestion result with normalization. Output is `InvoiceHistoryDecision`, including disposition, source hash, prior version, amounts, payment status, and `requires_human_review`.

## Processing Flow

The ledger hashes file type and source chunks, independent of local filename. It canonicalizes vendor and invoice number into a case key. An exact paid version is `DUPLICATE_SUPPRESSED`; an earlier unpaid version creates `REVISION_BEFORE_PAYMENT`; a changed version after payment creates `REVISION_AFTER_PAYMENT` and requires human review. A previously seen unpaid version is retryable; a pending human-review version remains blocked.

## Payment Handoff

Before payment, `claim_payment` atomically changes the current version to `CLAIMED`. Completion records workflow/payment status and transaction ID and can supersede an unpaid prior version after successful payment. A failed or denied workflow is retained for later audit.

## Explicit Non-Responsibilities

The ledger does not decide whether invoice data is valid, whether stock exists, whether a revision deserves a refund, or whether a human has approved an adjustment.

## Relevant Source Files

[`invoice_ledger.py`](../../src/invoice_system/invoice_ledger.py), [`workflow.py`](../../src/invoice_system/workflow.py), [`policy.md`](../../src/invoice_system/approval/policy.md), and [`test_invoice_ledger.py`](../../tests/test_invoice_ledger.py).
