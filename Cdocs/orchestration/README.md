# Orchestration

**State:** POC — CLI path selection and one-stage ingestion only.

`main.py` accepts PDF, TXT, JSON, CSV, or XML sources and calls `invoice_system.ingestion.ingest`.

```powershell
python main.py --invoice-path data/invoices/invoice_1011.pdf
python main.py --review-file data/invoices/invoice_1001.txt
```

The regular command prints `BatchResult`. Review mode also prints paths to `run-report.md`, `events.jsonl`, `extraction.json`, and `result.json`. It does not run automatic validation, approval, payment, retries, or evaluation.
