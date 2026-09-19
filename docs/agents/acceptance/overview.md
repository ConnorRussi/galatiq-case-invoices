# Acceptance agent

Status: approval boundary implemented, independently evaluable, and connected to
the human-facing end-to-end workflow. Approved results continue to mock payment.

## Intended boundary

The approval boundary consumes a normalized invoice plus typed upstream
`VALID`/`PASS` status envelopes, applies the policy in
[src/invoice_system/approval/policy.md](../../../src/invoice_system/approval/policy.md),
and returns an auditable `ApprovalResult`. The Business Rule Agent chooses
`ACCEPT`, `REJECT`, or `VP_REVIEW`; only the latter invokes the VP Agent. A
model suggestion authorizes only the local mock payment boundary when the graph's
terminal `ApprovalResult` is `APPROVED`.

The graph is implemented by
[approval/graph.py](../../../src/invoice_system/approval/graph.py), executed
by [approval/runner.py](../../../src/invoice_system/approval/runner.py), and
evaluated independently with `python main.py --eval-approval`.

## Boundary and artifacts

Invoices over `$10,000` or with unusual payment conditions may route to VP
review. `GO` produces `APPROVED`; `NO_GO` produces `REJECTED`. Direct business
rule decisions use `BUSINESS_RULE_AGENT` as the decision source.

Approval runs write `approval_context.json`, `events.jsonl`, and
`approval_result.json`; graph failures write `approval_error.json`. Evaluation cases and expected final buckets live under
[evals/approval/cases/](../../../evals/approval/cases/); generated evaluation
artifacts live under `logs/evals/<evaluation_id>/approval/`.

