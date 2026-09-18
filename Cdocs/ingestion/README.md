# Ingestion

**State:** POC — multi-format native-text intake and one schema-validated extraction.

## Purpose and boundary

Ingestion accepts one accessible PDF, TXT, JSON, CSV, or XML invoice and extracts its native text and evidence locators. It makes one TAMU request for a typed `Invoice`; it does not alter the result after schema validation. It does not normalize product names or identifiers, retry, critique, revise, perform business validation, or decide acceptability. Image-only PDF/OCR processing is deferred.

```text
source → safe read + native-text extraction → one model call → Invoice schema gate → artifacts
```

## Input and output

- PDF sources must have usable native text and stay within configured byte/page/character limits.
- TXT must be UTF-8. JSON, CSV, and XML receive syntax checks before their source text is sent to the model.
- `ingest(paths)` returns one `BatchItemResult` per source. `ready_for_validation` means a typed extraction exists, not that an invoice passed business validation.

## Human diagnosis

Each run writes `run-report.md`, `events.jsonl`, `extracted-text.txt`, `extraction.json`, `model-response.json` when valid, and `result.json`. `main.py --review-file <path>` prints their locations.

## POC tests

`tests/test_ingestion_poc.py` proves reader coverage for TXT/JSON/CSV/XML/native-text PDF, one-call behavior, model-value preservation, and readable failure reporting. The legacy golden evaluator remains out of the CLI until its POC pass criteria are redesigned.
