# Acceptance agent

Status: approval boundary implemented in isolation; upstream integration and
payment are not connected.

## Intended boundary

The approval boundary consumes a normalized invoice plus trusted upstream
`VALID`/`PASS` results, applies the policy in
[src/invoice_system/approval/policy.md](../../../src/invoice_system/approval/policy.md),
and returns an auditable `ApprovalResult`. The Business Rule Agent chooses
`ACCEPT`, `REJECT`, or `VP_REVIEW`; only the latter invokes the VP Agent. A
model suggestion does not authorize a payment side effect.

The graph is implemented by
[approval/graph.py](../../../src/invoice_system/approval/graph.py), executed
by [approval/runner.py](../../../src/invoice_system/approval/runner.py), and
evaluated independently with `python main.py --eval-approval`.

## Boundary and artifacts

Invoices over `$10,000` or with unusual payment conditions may route to VP
review. `GO` produces `APPROVED`; `NO_GO` produces `REJECTED`. Direct business
rule decisions use `BUSINESS_RULE_AGENT` as the decision source.

Approval runs write `approval_context.json`, `events.jsonl`, and
`approval_result.json`. Evaluation cases and expected final buckets live under
[evals/approval/cases/](../../../evals/approval/cases/); generated evaluation
artifacts live under `logs/evals/<evaluation_id>/approval/`.

