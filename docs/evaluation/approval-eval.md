# Approval Evaluation

Run with `python main.py --eval-approval`. Cases in [`evals/approval/cases/`](../../evals/approval/cases/) begin with trusted normalized invoices and upstream statuses already set to `VALID` and `PASS`.

This isolates Business Rule and VP behavior. Cases cover direct acceptance, policy rejection, over-threshold VP approval, VP rejection, and unusual payment terms. The evaluator scores final status, decision source, Business Rule route, and VP route. It does not score model prose.
