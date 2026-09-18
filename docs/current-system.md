# Current system

The active ingestion POC accepts PDF, TXT, JSON, CSV, and XML invoices. It extracts native text and locators, makes one TAMU structured-extraction call, validates the returned `Invoice` shape, and writes a result plus readable diagnostics.

```text
source → native-text extraction → one model extraction → schema gate → result.json + run-report.md
```

It does not support image-only PDF/OCR, business normalization, retries, critic/revision loops, automatic validation, approval, or payment. See [`Cdocs/ingestion`](../Cdocs/ingestion/README.md) for the current contract.
