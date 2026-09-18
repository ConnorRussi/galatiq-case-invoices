# Acceptance

**State:** POC ingestion coverage exists; model-quality evaluation remains intentionally deferred.

## Current verification

| Scope | Command | What it establishes |
| --- | --- | --- |
| Offline POC ingestion | `python -m pytest tests/test_ingestion_poc.py` | PDF/TXT/JSON/CSV/XML reader coverage, one model call, no post-model normalization, and readable run artifacts. |
| Validation suite | `python -m pytest tests/test_validation.py` | Existing downstream deterministic validation behavior. |
| Manual inspection | `python main.py --review-file data/invoices/invoice_1011.txt` | JSON result plus paths to `run-report.md` and `events.jsonl`. |

The POC accepts PDF/TXT/JSON/CSV/XML sources; PDFs require usable native text. A live model is required for the manual command; unit tests inject a provider and require no credentials. The old golden evaluation remains in the tree but is not current POC acceptance evidence and must be redesigned before it is used as a pass/fail signal.
