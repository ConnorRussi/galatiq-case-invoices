# Evaluation and verification

Evaluation mode is implemented by
[`src/invoice_system/ingestion/evaluation.py`](../src/invoice_system/ingestion/evaluation.py)
and invoked with `python main.py --eval-ingestion`.

## What is checked

The evaluator runs expected fixtures under
[`evals/ingestion/expected/`](../evals/ingestion/expected/) and compares status,
typed scalar fields, line items, additional fields, and source evidence. It
also runs challenge checks for arithmetic/date fidelity, missing values,
negative quantities, optional components, and critic behavior.

The test suite complements this with focused regression tests:

- [`test_agent_runtime.py`](../tests/test_agent_runtime.py) checks structured
  output correction and error reporting.
- [`test_ingestion_regressions.py`](../tests/test_ingestion_regressions.py)
  checks evidence, no-op critique filtering, goldens, and terminal behavior.
- [`test_normalization_policy.py`](../tests/test_normalization_policy.py)
  checks that policy changes reach normalize, critique, and revise prompts.
- [`test_validation.py`](../tests/test_validation.py) checks semantic pass/deny
  contracts, relative dates, negative quantities, contradictory dates, critic
  revisions, and fail-closed unresolved routing.

Validation tests stub the shared structured model boundary; they exercise the
actual Phase 1 LangGraph and do not require live provider credentials.

## Adding a new feature

Add a representative fixture, expected output, focused regression test, and an
evaluation artifact description. For a new agent domain, add its checks under
that domain's folder in [`docs/agents/`](agents/) and link the results here.
Do not treat a green model call as acceptance; acceptance requires a deterministic
check or an explicitly documented human-review boundary.
