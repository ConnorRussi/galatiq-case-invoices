# Validation Agents

## Purpose

Validation is the full `Semantic -> Reconciliation -> Database` graph. [`run_validation`](../../src/invoice_system/validation/runner.py) can run isolated Semantic evaluation or enable the complete graph used by the live workflow.

## Explicit Non-Responsibilities

Validation does not extract fields, approve payment, submit human review, or invoke a bank. It consumes ingestion output and returns evidence for approval; it does not apply approval policy.

## Inputs And Outputs

Input is an accepted/reviewable `IngestionResult`, detached by JSON round-trip. Output is `ValidationResult` with overall status, denial stage, issue list, ingestion snapshot, stage results, critic results, and optional technical error.

Semantic returns `PASS` or `DENY`. Reconciliation returns `PASS` or `DENY` plus identity mappings, consolidated items, and calculations. Database returns `PASS` or `DENY` plus one auditable inventory result per requested product.

## Processing Flow

Semantic checks semantic usability and structure. Its critic can revise or deny. Reconciliation interprets product identity and arithmetic, while deterministic Decimal helpers materialize line, subtotal, and total checks. Its critic can revise or deny. Database performs bulk SQLite lookup, bounded retry planning for unresolved names, stock comparison, and its critic's deterministic audit. Any denied stage stops the graph.

## Deterministic Logic

`Decimal` avoids binary-float money errors. Reconciliation preserves source lines and repeated products. Database uses `SELECT item, stock FROM inventory WHERE item = ?`, checks requested quantity against stock, and records attempted names. Database audit rejects unsupported PASS results, uncovered lines, split identities, and inconsistent stock facts.

## Critic / Revision Loop

The shared `review_stage` returns `AGREE` or `REVISE`. Semantic, Reconciliation, and Database each have `MAX_CRITIC_REVISIONS = 2`. Exhaustion becomes `DENIED` with `unresolved_validation`; graph exceptions become `TECHNICAL_FAILURE`.

## Handoff Contract

Approval is admitted only when overall validation is `VALID` and reconciliation is `PASS`. Approval may trust that the configured validation stages completed, but it must still apply policy and inspect supplied concerns.

## Relevant Source Files

[`graph.py`](../../src/invoice_system/validation/graph.py), [`runner.py`](../../src/invoice_system/validation/runner.py), [`semantic.py`](../../src/invoice_system/validation/semantic.py), [`reconciliation.py`](../../src/invoice_system/validation/reconciliation.py), [`arithmetic.py`](../../src/invoice_system/validation/arithmetic.py), [`database.py`](../../src/invoice_system/validation/database.py), [`database_tool.py`](../../src/invoice_system/validation/database_tool.py), and [`critic.py`](../../src/invoice_system/validation/critic.py).
