# Ingestion POC

`ingest(paths)` accepts PDF, TXT, JSON, CSV, and XML sources. It extracts native text, makes one structured model request, validates the response against `Invoice`, and writes readable diagnostics. Image-only PDFs are deferred.
