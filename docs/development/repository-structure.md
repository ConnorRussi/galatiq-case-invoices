# Repository Structure

- `main.py`: live CLI and evaluation dispatch.
- `dashboard.py`, `dashboard_template.html`: generated read-only reviewer UI.
- `src/invoice_system/`: installable package and stage implementations.
- `data/invoices/`: mixed-format source corpus.
- `evals/`: expected ingestion outputs, validation/approval fixtures, and workflow manifest.
- `tests/`: offline regression tests by stage and concern.
- `logs/`: generated normal-run and evaluation artifacts.
- `docs/`: human and reviewer documentation, including retained implementation guides.
- `inventory.sqlite`: local inventory database used by default.

Within `src/invoice_system`, `ingestion`, `validation`, `approval`, and `payment` own their domains. `workflow.py`, `invoice_ledger.py`, and `agent_runtime.py` are shared boundaries.
