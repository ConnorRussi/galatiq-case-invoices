# Data contracts

The canonical runtime contracts are Pydantic models in
[`src/invoice_system/ingestion/models.py`](../src/invoice_system/ingestion/models.py).

## Source and normalization contracts

`SourceDocument` contains a filename, detected file type, and a tuple of
`SourceChunk` objects. Each chunk has an ID, text, optional page/row location,
kind, and extraction method. `SourceDocument` and `SourceChunk` are frozen.

`NormalizationResult` contains a typed `NormalizedInvoice` and a separate list
of `FieldEvidence`. Evidence uses invoice-relative paths such as
`items[0].quantity`, source chunk IDs, and optional source text. A leading
`invoice.` wrapper is normalized away as syntax only.

## Review and terminal contracts

`CritiqueResult` contains typed `CritiqueIssue` values. Issue types are
`incorrect_value`, `missing_information`, `unsupported_inference`,
`structure_mismatch`, and `evidence_problem`.

`IngestionResult` combines the source path, source document, latest
normalization, latest critique, revision count, and optional error message.
Its status is one of `accept`, `needs_review`, or `technical_failure`.

## Semantic validation contracts

Phase 1 validation consumes the complete [`IngestionResult`](../src/invoice_system/ingestion/models.py)
and emits typed models in [`validation/models.py`](../src/invoice_system/validation/models.py):

- `ValidationIssue` contains a code, concise message, optional invoice field,
  severity, and supporting evidence.
- `SemanticResult` contains the `semantic` stage, `PASS` or `DENY`, all issues,
  and a summary.
- `CriticResult` contains `AGREE` or `REVISE`, findings, and revision
  instructions. It never returns a specialist PASS/DENY decision.
- `ValidationResult` contains `VALID` or `DENIED`, a reason, denial stage,
  issues, the semantic/critic records, and the immutable ingestion snapshot.

The semantic agent treats negative quantities, relative dates, contradictory
dates, and materially missing required information as semantic concerns. It does
not perform inventory, database, arithmetic reconciliation, or business-policy
validation. Validation feedback never rewrites the source or normalized invoice.

## Contract changes

Changing a field can affect model prompts, JSON artifacts, evaluator comparisons,
and tests. Update this page, prompt/policy documentation, relevant goldens, and
regression tests together. Preserve backward-readable artifact semantics unless
the change explicitly includes a migration plan.
