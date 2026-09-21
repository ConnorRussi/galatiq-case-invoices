# Ingestion Evaluation

Run with `python main.py --eval-ingestion`. The implementation is [`ingestion/evaluation.py`](../../src/invoice_system/ingestion/evaluation.py).

Expected normalized outputs are in [`evals/ingestion/expected/`](../../evals/ingestion/expected/). The evaluator checks ingestion status, common typed fields, line items, additional fields, and evidence coverage. It also applies targeted critic probes for wrong values, missing information, canonical item names, negative quantities, date/arithmetic fidelity, and optional components.

The source corpus is not rewritten by evaluation. Results and case artifacts are saved under `logs/evals/`.
