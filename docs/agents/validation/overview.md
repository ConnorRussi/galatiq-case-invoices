# Validation agent

Status: Phase 1, Phase 2, and Phase 3 implemented. The validation graph consumes an
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

Product identity interpretation is a separate deterministic concern in
[`validation/identity.py`](../../../src/invoice_system/validation/identity.py).
It emits an auditable mapping for each named source line. Only recognized
fulfillment qualifiers, currently `rush order`, may resolve to an unqualified
product already present in the invoice; unknown or ambiguous qualifiers stay
unresolved. Arithmetic consumes that mapping but still calculates every line
from its original quantity and unit price.

## Database boundary

`database.py` and `database_tool.py` provide the Phase 3 inventory validation
boundary. The SQL tool performs exact bulk lookups after outer-whitespace
trimming only. The specialist may deliberately request meaning-preserving
variations for unresolved products, using at most three lookup rounds, and
`DatabaseResult.attempted_names` preserves the complete lookup history.
Database receives Reconciliation's consolidated items, so quantity and source
line mapping are checked once per consolidated product. All source lines mapped
to one inventory item are therefore aggregated before the stock comparison.
Database completeness is measured by exact one-time coverage of named source
lines, not by requiring a separate lookup for every raw description. An unknown requested
quantity remains unknown and produces `MISSING_QUANTITY` rather than passing
inventory sufficiency. `database_runner.py`
remains the reusable critiqued execution boundary; the main graph uses the same
specialist and shared critic in the growing Semantic -> Reconciliation ->
Database flow. Semantic or Reconciliation DENY short-circuits Database.

Both execution paths pass the accepted Reconciliation result into the shared
critic. The critic reviews identity using source descriptions, qualifiers,
resolved products, and source lines; attempted names describe actual SQL
requests. Independent checks in `critic.py` verify exact coverage, quantities
from original lines, and stock conclusions. They never discard identity
findings or force agreement. Contradictory AGREE responses require revision
and fail closed after the existing bound. Offline graph regressions live in
[`test_database_handoff.py`](../../../tests/test_database_handoff.py).
