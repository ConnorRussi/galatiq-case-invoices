# Debugging

Start with the run directory printed by the CLI. Read `workflow_result.json` for terminal status, stop stage, reason, and completed stage data. Then inspect `events.jsonl` for ordered routes and `source.json`, normalized/critique versions, validation artifacts, approval context/result, and payment input/result.

Common checks:

- `TECHNICAL_FAILURE` at ingestion: inspect source format, UTF-8, PDF text, and model configuration.
- `VALIDATION_DENIED`: inspect `validation_result.json`, the stage named by `denied_by`, issue codes, calculations, and inventory attempts.
- `HUMAN_REVIEW_REQUIRED`: inspect invoice history, business-rule triggers, VP decision, and adjustment amount.
- `DUPLICATE_SUPPRESSED`: inspect the ledger path and source hash; the exact paid version is intentionally not retried.
- `PAYMENT_FAILED`: inspect payment preflight/provider result and ledger claim state.

Run focused tests such as `python -m pytest tests/test_workflow.py tests/test_invoice_ledger.py -q` before the full suite. The dashboard is useful for presentation, but raw JSON artifacts are the diagnostic source of truth.
