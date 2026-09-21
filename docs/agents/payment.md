# Payment Agent

## Purpose

Payment is the final local execution boundary. [`run_payment`](../../src/invoice_system/payment/runner.py) calls an injectable provider and returns an auditable `PaymentResult`.

## Explicit Non-Responsibilities

It does not validate invoice semantics, inventory, approval policy, or human review. It does not contact a bank. The built-in `mock_payment` returns success and a generated `mock-...` transaction ID.

## Inputs And Outputs

The workflow builds `PaymentRequest` only after `ApprovalResult.final_status` is `APPROVED`. It requires invoice ID, vendor, positive amount, three-letter currency, and optional idempotency key. Output is `PaymentResult` with status, amount, currency, transaction ID, idempotency key, and reason.

## Processing Flow

The workflow claims the ledger version, derives amount from `amount_due` or `invoice_total`, checks vendor and currency, writes a blocked result if preflight fails, or calls the provider. Provider non-success or exceptions become `PaymentStatus.FAILED`; success is recorded with a transaction ID.

## Critic / Revision Loop

None. Payment failure is terminal for the live workflow; it is not retried by the payment runner.

## Handoff Contract

Success becomes `APPROVED_AND_PAID`. Failure becomes `PAYMENT_FAILED`. Both the payment result and events are written to the shared run directory.

## Relevant Source Files

[`payment/models.py`](../../src/invoice_system/payment/models.py), [`runner.py`](../../src/invoice_system/payment/runner.py), [`workflow.py`](../../src/invoice_system/workflow.py), and [`test_payment.py`](../../tests/test_payment.py).
