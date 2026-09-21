# Design Decisions

## Preserve source before interpretation

The reader stores raw chunks and does not parse invoice fields. This keeps extraction errors attributable to normalization and lets critics quote the original claim. It also makes PDF pages, CSV rows, JSON, XML, and text comparable to downstream code.

## Separate normalization from validation

Normalization standardizes representation and attaches evidence. It does not calculate totals, fix suspicious business values, or decide whether a product exists. Validation can therefore challenge a typed claim without losing the original source.

## Combine model interpretation with deterministic evidence

LLMs are useful for ambiguous field mapping, semantic concerns, product identity interpretation, and policy reasoning. Decimal arithmetic, SQL results, status admission, ledger identity, and payment preflight are deterministic so model prose cannot relabel hard evidence.

## Use bounded correction

Critics make disagreement visible and can request a revision, but each loop has a small fixed budget. Exhaustion becomes denial rather than an unbounded call cycle or a silent acceptance. The transport's one schema correction is kept separate from business-level revision.

## Use bulk inventory lookups

The Database specialist sends unresolved product names in rounds and preserves every attempt. This reduces repeated SQL calls while keeping retry decisions auditable. A retry candidate must be meaning-preserving; a failed lookup is not permission to substitute another product.

## Separate approval from VP escalation

Business Rule applies policy first. VP reasoning is an escalation branch, not a second validation pass. Paid revisions are routed through the same branch but forced to human review, because the prototype has no credit/refund or adjustment service.

## Fail closed at payment

The workflow claims the ledger version before payment and validates vendor, amount, and currency before invoking the provider. The only provider is a local mock, so a successful result demonstrates orchestration and audit behavior rather than bank settlement.

## Keep the dashboard read-only

The dashboard is a low-risk artifact viewer. It does not become an implicit approval API, and its HTML payload is escaped before embedding. Future human decision submission would require a separate controlled service boundary.
