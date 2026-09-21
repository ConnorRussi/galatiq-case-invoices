# Dashboard Surface

The dashboard is a presentation component, not an agent. [`dashboard.py`](../../dashboard.py) recursively scans `logs/` for valid `workflow_result.json` and workflow `summary.json` files, embeds escaped JSON into [`dashboard_template.html`](../../dashboard_template.html), and writes a standalone HTML snapshot.

It shows source, evidence, validation, inventory, approval, payment, history, and evaluation summary information. It makes no model or network calls. It cannot approve/reject, submit a human decision, resume a workflow, retry payment, or change the ledger.

See [`test_dashboard.py`](../../tests/test_dashboard.py) for dashboard behavior coverage.
