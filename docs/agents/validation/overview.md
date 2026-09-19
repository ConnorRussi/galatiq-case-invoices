# Validation agent

Status: Phase 1 and Phase 2 implemented. The validation graph consumes an
`IngestionResult` and returns a typed `ValidationResult` without mutating the
ingestion invoice.

## Intended boundary

Phase 1 validation consumes an accepted or reviewable
[`IngestionResult`](../../contracts.md), inspects invoice claims against a
semantic invoice contract, and emits a typed validation report. It must not
rewrite the immutable source or silently alter the normalized invoice.

The implementation is [`src/invoice_system/validation/`](../../../src/invoice_system/validation/).
`policy.py` is the shared Phase 1 scope contract, `semantic.py` is the LLM
specialist, `critic.py` is the scope-aware shared critic contract, and
`graph.py` routes `semantic -> semantic_critic` with at most two revisions.

The specialist checks whole-invoice semantics including negative quantities,
relative dates, contradictory dates, invalid values, basic usability, and only
contractually required fields. The current Phase 1 contract does not make
`invoice_total`, `amount_due`, subtotal, tax, payment terms, vendor, or any
other common field universally required. It does not calculate or reconcile
amounts, infer a due date from payment terms, query inventory/SQL, consolidate
products, or apply business approval policy. A critic-confirmed DENY stops this
prototype; unresolved disagreement fails closed as `DENIED` with reason
`unresolved_validation`.

The critic independently checks evidence support, Semantic-stage ownership,
invented requirements, root-cause quality, and the final PASS/DENY conclusion.
`REVISE` is the structured disagreement decision and routes the result back to
the specialist. After a critic-confirmed Semantic PASS, Phase 2 reconciliation
checks Decimal-safe arithmetic and repeated-product consolidation. A
critic-confirmed Semantic DENY never runs Phase 2.

## Reconciliation boundary

`reconciliation.py` owns line arithmetic, subtotal/tax/fee/total relationships
when present, and consolidation source-line coverage. `arithmetic.py` provides
observable Decimal evidence; it does not replace the LLM specialist.

## Database boundary

`database.py` and `database_tool.py` provide an isolated inventory validation
boundary. The SQL tool performs exact bulk lookups after outer-whitespace
trimming only. The specialist may deliberately request meaning-preserving
variations for unresolved products, using at most three lookup rounds, and
`DatabaseResult.attempted_names` preserves the complete lookup history.
`database_runner.py` applies the shared critic to the database result. This
boundary is callable from Python and is not yet part of the default CLI graph.
