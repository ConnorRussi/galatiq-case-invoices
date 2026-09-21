# Running The System

Live run:

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
```

Useful options are `--database-path PATH` and `--ledger-path PATH`. Evaluation modes are `--eval-ingestion`, `--eval-validation`, `--eval-approval`, and `--eval-workflow`; the semantic/reconciliation flags are compatibility aliases. `--validate` is deprecated because normal runs already perform full validation.

Build the read-only dashboard:

```bash
python dashboard.py
python dashboard.py --logs-root PATH --output PATH
```

Normal runs create `logs/runs/<run_id>/` and print progress, terminal status, reason, and artifact location. Only `APPROVED_AND_PAID` exits zero.
