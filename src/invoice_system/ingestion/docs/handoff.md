# Handoff to the next agent

The orchestrator calls:

```python
from invoice_system.ingestion import run_pipeline

batch = run_pipeline(paths)
```

`batch` is a `BatchResult`. It contains one `BatchItemResult` per requested path, in the same order. Each item has an artifact path when persistence succeeded and an `IngestionResult` in all normal failure cases.

The next agent should consume `result.invoice` and `result.issues`, not raw provider output or a PDF. `invoice` is either `None` or a `InvoiceCandidate` whose fields hold:

- `value`: a trusted string, `Decimal`, `date`, or `None`.
- `observed`: original literal, alternatives, confidence, and evidence locators.
- `applied_rule`: the deterministic rule used to create the trusted value.

`result.issues` is intentionally part of the handoff. Validation can report every downstream concern for a partial candidate instead of rejecting it at ingestion time. For example, a missing vendor remains `None` with a `MISSING_FIELD` issue, while valid line items still arrive for inventory checks.

Status handling belongs to the orchestrator that joins agents:

| Ingestion status | Recommended next-agent action |
| --- | --- |
| `ready_for_validation` | Send the candidate and issues to validation. |
| `needs_review` | Route to human review, or let validation inspect any partial candidate if that policy is useful. |
| `invalid_input` | Do not invoke validation; report the source problem. |
| `technical_failure` | Do not treat the result as a business decision; retry through an operational policy or report the failure. |

Do not make validation recalculate, consolidate, or “fix” ingestion values. Validation owns inventory and business-rule findings; ingestion owns evidence, controlled normalization, and extraction uncertainty.
