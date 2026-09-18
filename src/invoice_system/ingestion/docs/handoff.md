# Handoff

`ingest(paths)` returns a `BatchResult`. Each source produces an `IngestionResult` with source metadata, an optional typed `Invoice`, and issues. `ready_for_validation` only means a schema-valid extraction is available; it is not a business decision.
