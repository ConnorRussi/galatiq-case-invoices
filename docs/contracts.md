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
Its status is one of `accept`, `needs_review`, or `technical_failure`. Only
`accept` and `needs_review` may enter validation.

## Semantic validation contracts

Phase 1 validation consumes the complete [`IngestionResult`](../src/invoice_system/ingestion/models.py)
and emits typed models in [`validation/models.py`](../src/invoice_system/validation/models.py):

- `ValidationIssue` contains a code, concise message, optional invoice field,
  severity, and supporting evidence.
- `SemanticResult` contains the `semantic` stage, `PASS` or `DENY`, all issues,
  and a summary.
- `CriticResult` contains `AGREE` or `REVISE`, findings, and revision
  instructions. It never returns a specialist PASS/DENY decision.
- `ValidationResult` contains `VALID`, `DENIED`, or `TECHNICAL_FAILURE`, a reason, denial stage,
  issues, the immutable ingestion snapshot, and stage-specific specialist and
  critic records. It deliberately has no generic `critic_result`: that name
  would change meaning depending on which stage ran last. A provider or graph
  error produces `TECHNICAL_FAILURE` with an error message and any completed
  stage results; it is never treated as valid.

The shared Phase 1 scope contract is defined in
[`validation/policy.py`](../src/invoice_system/validation/policy.py) and is used
by both the specialist and critic. Semantic validation treats negative
quantities, relative dates, contradictory dates, invalid values, basic
usability, and explicitly required fields as semantic concerns. Different unit
prices on repeated normalized products are not a semantic contradiction; they
remain line-level arithmetic for Reconciliation. The current
contract does not universally require `invoice_total` or `amount_due`, and does
not infer due dates from payment terms. It never compares an invoice date with
today, the system date, or a model knowledge cutoff; only date relationships
contained within the invoice itself are in scope. It does not perform inventory,
database, arithmetic reconciliation, or business-policy validation. A relative
raw date is reported as one canonical root issue on the normalized field (for
example `due_date`), with the raw value retained as evidence. Validation
feedback never rewrites the source or normalized invoice.

## Contract changes

Changing a field can affect model prompts, JSON artifacts, evaluator comparisons,
and tests. Update this page, prompt/policy documentation, relevant goldens, and
regression tests together. Preserve backward-readable artifact semantics unless
the change explicitly includes a migration plan.

## Reconciliation contracts

Phase 2 adds `ReconciliationResult`, `ConsolidatedItem`, and
`ReconciliationCalculation` in [`validation/models.py`](../src/invoice_system/validation/models.py).
The result contains a `PASS`/`DENY` status, structured issue codes and fields,
consolidated product identity/quantity/source lines, and Decimal-safe
calculation records. It owns invoice arithmetic and duplicate consolidation;
inventory, database lookup, approval thresholds, and payment policy remain
later-stage concerns.

## Database contracts

`DatabaseValidationResult` contains a `PASS`/`DENY` status, structured issue
codes, and one `DatabaseResult` per consolidated product. Each result records
the requested and attempted product names, normalized consolidated product,
source lines, matched database identity, requested quantity, and available
stock. Database validation owns product existence, identity association, and
inventory sufficiency; it does not redo Semantic checks, arithmetic, or
consolidation.

## Approval contracts

`ApprovalRequest` is the isolated handoff into approval. It contains the
normalized invoice, optional source document, and trusted upstream validation
and reconciliation results. `BusinessRuleDecision` is one of `ACCEPT`,
`REJECT`, or `VP_REVIEW`; `VPDecision` is `GO` or `NO_GO`.

The upstream validation and reconciliation inputs are typed status envelopes;
arbitrary `Any` payloads are not accepted at this boundary.

`ApprovalResult` is the terminal approval contract. It records `APPROVED` or
`REJECTED`, the decision source, both structured decisions when applicable, and
the final reasoning. It does not perform or authorize a payment side effect.
