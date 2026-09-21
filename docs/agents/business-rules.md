# Business Rule Agent

## Purpose

The Business Rule Agent applies the Acme approval policy after validation and reconciliation have passed. It returns `ACCEPT`, `REJECT`, or `VP_REVIEW` with triggered rules, reasoning, and concerns.

## Explicit Non-Responsibilities

It does not redo OCR, repair normalization, recalculate totals, query inventory, or authorize payment directly. It must not invent policy beyond [`policy.md`](../../src/invoice_system/approval/policy.md).

## Inputs And Outputs

Input is `ApprovalRequest`: invoice ID, original source document, normalization, upstream validation and reconciliation envelopes, and optional `InvoiceHistoryDecision`. Output is `BusinessRuleDecision`.

## Processing Flow

The approval runner first enforces validation `VALID` and reconciliation `PASS`. The graph invokes this agent. A paid prior version adds a deterministic instruction and forces the decision route to VP review. `ACCEPT` or `REJECT` completes approval; `VP_REVIEW` invokes the VP Agent.

## Reasoning Responsibilities

The model interprets the policy: amounts above `$10,000`, unusual payment conditions, unresolved concerns, exact paid duplicates, and paid revisions. It may recognize equivalent upstream field names, but missing or contradictory data is a concern rather than a guess.

## Critic / Revision Loop

There is no business-rule critic or revision loop. Structured output still passes through the shared schema-validation and transport retry boundary.

## Handoff Contract

An `ACCEPT` decision permits approval completion, not payment by itself. `VP_REVIEW` requires a VP decision. `REJECT` becomes `APPROVAL_REJECTED` in the workflow.

## Relevant Source Files

[`agents.py`](../../src/invoice_system/approval/agents.py), [`graph.py`](../../src/invoice_system/approval/graph.py), [`runner.py`](../../src/invoice_system/approval/runner.py), and [`models.py`](../../src/invoice_system/approval/models.py).
