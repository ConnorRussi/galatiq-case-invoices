# Validation agent

Status: Phase 1 implemented. The semantic validation graph consumes an
`IngestionResult` and returns a typed `ValidationResult` without mutating the
ingestion invoice.

## Intended boundary

Phase 1 validation consumes an accepted or reviewable
[`IngestionResult`](../../contracts.md), inspects invoice claims against a
semantic invoice contract, and emits a typed validation report. It must not
rewrite the immutable source or silently alter the normalized invoice.

The implementation is [`src/invoice_system/validation/`](../../../src/invoice_system/validation/).
`semantic.py` is the LLM specialist, `critic.py` is the shared critic contract,
and `graph.py` routes `semantic -> semantic_critic` with at most two revisions.

The specialist checks whole-invoice semantics including negative quantities,
relative dates, contradictory dates, and materially missing required data. It
does not query inventory/SQL, reconcile arithmetic, consolidate products, or
apply business approval policy. A critic-confirmed DENY stops this prototype;
unresolved disagreement fails closed as `DENIED` with reason
`unresolved_validation`.

## Future phases

Future phases will add reconciliation, database tools, and business acceptance
after the Phase 1 PASS endpoint. Those agents and their critics are not yet
implemented.
