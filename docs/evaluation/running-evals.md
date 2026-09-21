# Running Evaluations

From the project root, install the evaluation dependencies and configure the model environment:

```bash
python -m pip install -e ".[ingestion,ingestion-dev]"
python main.py --eval-ingestion
python main.py --eval-validation
python main.py --eval-approval
python main.py --eval-workflow
```

Only one evaluation mode may be selected per invocation. `--eval-semantic` and `--eval-reconciliation` are aliases for validation. Results use exit code `0` when comparisons pass and `1` when they fail. Inspect `logs/evals/<evaluation_id>/summary.json` and case artifacts before interpreting a failure.

The workflow evaluator requires the manifest in [`evals/workflow/cases.json`](../../evals/workflow/cases.json) to cover every file in `data/invoices/`. It also checks VP invocation and decision events. Synthetic threshold fixtures cover exactly `$10,000`, just above the threshold, and well above it. The quarantined VP-rejection candidate is not part of the live corpus because current policy does not deterministically specify its route.
