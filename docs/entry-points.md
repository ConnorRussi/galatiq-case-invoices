# Entry points

| Entry point | Result |
| --- | --- |
| `python main.py --invoice-path <pdf|txt|json|csv|xml>` | One-pass ingestion and JSON batch result. |
| `python main.py --review-file <pdf|txt|json|csv|xml>` | One source plus paths to human report and event log. |
| `invoice_system.ingestion.ingest(paths)` | Public API returning `BatchResult`. |
| `python -m invoice_system.validation <result.json> --inventory-db inventory.sqlite` | Separate validation command. |

PDFs require usable native text. Golden/smoke evaluation is kept out of the POC CLI until its pass criterion is redesigned.
