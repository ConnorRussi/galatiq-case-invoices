# Evaluation and verification

Evaluation mode is implemented by
[`src/invoice_system/ingestion/evaluation.py`](../src/invoice_system/ingestion/evaluation.py)
and invoked with `python main.py --eval-ingestion`.

Phase 1 Semantic evaluation is implemented by
[`src/invoice_system/validation/evaluation.py`](../src/invoice_system/validation/evaluation.py)
and invoked with `python main.py --eval-semantic`.

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

- [`test_semantic_evaluation.py`](../tests/test_semantic_evaluation.py) checks
  structured scoring, critic revision reporting, per-case isolation, and
  ingestion-golden immutability.

Validation tests stub the shared structured model boundary; they exercise the
actual Phase 1 LangGraph and do not require live provider credentials.

## Isolated Semantic evaluation

The authoritative Semantic suite is isolated from live ingestion. Cases under
[`evals/validation/semantic/expected/`](../evals/validation/semantic/expected/)
reference the trusted normalized invoice goldens under
[`evals/ingestion/expected/`](../evals/ingestion/expected/). The evaluator
reconstructs an `IngestionResult` from each golden and sends that immutable
structured input directly to the Semantic graph. It never reruns ingestion and
never edits the ingestion goldens. The date-order case in
[`evals/validation/semantic/fixtures/`](../evals/validation/semantic/fixtures/)
is a controlled Semantic-only input because the ingestion corpus does not
contain that failure.

Each case reports status match, expected issue-code coverage, expected
field/location coverage, unexpected blocking issues, critic completion, critic
revision count, denial-stage match, and an overall semantic match. Natural
language summaries and explanations are not scored. Focused critic probes live
under [`critic_expected/`](../evals/validation/semantic/critic_expected/) and
cover false PASS, false DENY, correct DENY, and correct PASS independently of
the normal invoice cases.

The current expected root field for the relative-date case is `due_date`; the
raw `additional_fields.due_date_raw` value is evidence, not a second missing
field failure. Reconciliation-only observations such as missing
`invoice_total`/`amount_due` or payment-term date arithmetic are intentionally
not Semantic expectations.

Each run writes JSON artifacts under `logs/evals/<evaluation_id>/`. Normal
validation artifacts remain the same (`validation_input.json`, versioned
`semantic_vN.json`, `semantic_critic_vN.json`, and `validation_result.json`),
with `expected.json`, `evaluation.json`, and a suite `summary.json` added by
the evaluator. There is deliberately no separate end-to-end Semantic smoke
mode yet; `--validate` remains the existing normal ingestion-to-validation
path and is not mixed into the isolated score.

## Adding a new feature

Add a representative fixture, expected output, focused regression test, and an
evaluation artifact description. For a new agent domain, add its checks under
that domain's folder in [`docs/agents/`](agents/) and link the results here.
Do not treat a green model call as acceptance; acceptance requires a deterministic
check or an explicitly documented human-review boundary.
