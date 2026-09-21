# Decision Routing

This page describes the deterministic decision surface that combines stage outputs. It is not an additional agent.

## Workflow decision order

1. Ingestion technical failure stops immediately.
2. The invoice ledger suppresses an exact paid version before validation.
3. Validation must finish `VALID`; otherwise the workflow returns `VALIDATION_DENIED` or `TECHNICAL_FAILURE`.
4. Approval must finish `APPROVED`; rejection or human review is terminal.
5. Ledger claim and payment preflight must succeed before the mock provider call.
6. Provider success is the only route to `APPROVED_AND_PAID`.

## Why this matters

Models propose stage decisions, but the orchestrator controls whether later code is reachable. The workflow never sends denied validation to approval, never sends rejected approval to payment, and never converts a human-review stop into payment.

## Relevant Source Files

[`workflow.py`](../../src/invoice_system/workflow.py), [`validation/graph.py`](../../src/invoice_system/validation/graph.py), and [`approval/graph.py`](../../src/invoice_system/approval/graph.py).
