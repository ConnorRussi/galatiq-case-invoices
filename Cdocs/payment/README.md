# Payment

**State:** planned — no payment tool or ledger currently runs.

## Purpose and contract

Payment will be a controlled simulated side effect, never an autonomous agent. Before recording payment it must independently verify: final decision is approved, `payment_authorized` is true, no blocking/unresolved findings remain, required human approval exists, and the idempotency key has not already been paid.

Its input is a final approved decision plus invoice identity and amount. Its output is a durable simulated payment/rejection record suitable for audit. Reprocessing the same idempotency key must return the existing outcome rather than duplicate a payment.

## Build prerequisites

First define Validation blocking semantics and Approval's typed final decision. Then add a locally reproducible ledger, idempotency test cases, and a test-only/mock transport. Update [Acceptance](../acceptance/README.md) with duplicate-submission and rejected-invoice coverage before composing this into the CLI.
