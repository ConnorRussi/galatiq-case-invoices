# Ingestion domain

## Responsibility

Ingestion turns one supported document into an evidence-preserving
`IngestionResult`. The reader owns extraction only; the model owns semantic
normalization; the critic checks fidelity; the gate decides the ingestion
terminal status. The separate Phase 1 validation graph consumes this result.

## Stage behavior

1. `read_source` accepts PDF, TXT/Markdown, CSV, JSON, or XML. It uses strict
   UTF-8 for text-like inputs, preserves source text, and emits immutable
   [`SourceDocument`](contracts.md#source-and-normalization-contracts) chunks.
2. `normalize` sends the source and schema to the configured model. It does not
   derive values that the source does not support. Explicit source labels such as
   `Total Amount`, `Grand Total`, `Invoice Total`, `Amount Due`, `Balance Due`,
   and `Total Due` are mechanically mapped to typed monetary fields after the
   model response; this is source extraction, not calculation. Currency is
   copied from an explicit source code or supported symbol (`$` means USD).
   When no currency claim exists, the authorized policy default is USD and is
   marked `additional_fields.currency_source=policy_default` without fabricated
   source evidence. Conflicting claims are preserved in
   `additional_fields.currency_conflict`, leave typed currency unresolved, and
   require review. Field evidence is separate from invoice claims.
3. `critic` reviews the candidate against the same source and policy. It can
   identify incorrect values, missing information, unsupported inference,
   structure mismatches, and evidence problems.
4. `revise` may run twice. A revision receives the original source, current
   candidate, and critique; it does not mutate the source.
5. `gate` returns `accept` when the final critique is clean, `needs_review`
   when issues remain after the revision budget, or `technical_failure` when
   execution fails.

## Important invariants

- Source chunks are immutable and remain available in the final result.
- JSON/XML are syntax-checked and retained as source text rather than reserialized.
- CSV header and row structure is preserved.
- Blank or textless PDF pages fail conservatively because OCR is not installed.
- A technical failure never fabricates an invoice.
- Currency defaults to USD only when the source provides no currency claim;
  explicit currency claims carry source evidence, and conflicting claims
  require review.
- An explicit source total cannot remain only in `additional_fields.amount_raw`;
  it must be represented as `invoice_total` or `amount_due` with source evidence.
- PO extraction is model-owned. The postprocessor does not extract identifiers or
  fabricate PO evidence; complete notes are preserved, and generic phrases such
  as `PO amendment` are not identifiers.
- Critique must not turn formatting-equivalent or policy-permitted values into
  false corrections; regression tests enforce this.
- Validation receives a detached snapshot of the result and never rewrites the
  ingestion invoice.

## Main files and tests

- Implementation: [`src/invoice_system/ingestion/`](../src/invoice_system/ingestion/)
- Policy: [`normalization_policy.md`](../src/invoice_system/ingestion/normalization_policy.md)
- Tests: [`test_ingestion_regressions.py`](../tests/test_ingestion_regressions.py),
  [`test_normalization_policy.py`](../tests/test_normalization_policy.py)
- Workflow: [LangGraph](langgraph.md)
- Shapes: [Contracts](contracts.md)
