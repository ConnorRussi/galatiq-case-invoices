# Evaluation and verification

Evaluation mode is implemented by
[`src/invoice_system/ingestion/evaluation.py`](../src/invoice_system/ingestion/evaluation.py)
and invoked with `python main.py --eval-ingestion`.

The Validation Agent evaluation is implemented by
[`src/invoice_system/validation/evaluation.py`](../src/invoice_system/validation/evaluation.py)
and invoked with `python main.py --eval-validation`.

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
- [`test_arithmetic.py`](../tests/test_arithmetic.py) checks Decimal-safe sums,
  subtraction, multiplication, and repeated-product evidence.
- [`test_reconciliation.py`](../tests/test_reconciliation.py) checks Phase 2
  critic input, Semantic short-circuiting, and full-stage routing.

Validation tests stub the shared structured model boundary; they exercise the
actual Semantic -> Reconciliation LangGraph and do not require live provider
credentials.

## Validation Agent evaluation

The authoritative Validation suite is isolated from live ingestion. Cases under
[`evals/validation/semantic/expected/`](../evals/validation/semantic/expected/)
reference the trusted normalized invoice goldens under
[`evals/ingestion/expected/`](../evals/ingestion/expected/). The evaluator
reconstructs an `IngestionResult` from each golden and sends that immutable
structured input through the Validation Agent graph. It never reruns ingestion
and never edits the ingestion goldens. The date-order case in
[`evals/validation/semantic/fixtures/`](../evals/validation/semantic/fixtures/)
is a controlled Semantic input because the ingestion corpus does not contain
that failure. Controlled Phase 2 inputs live under
[`evals/validation/reconciliation/`](../evals/validation/reconciliation/).

Every case runs Semantic first. A confirmed Semantic DENY is expected to stop
there; Reconciliation must not run. A confirmed Semantic PASS must have a
Reconciliation expectation and continue through the real Reconciliation stage.
The same case truth set will later gain Database and Validation Gate blocks;
Business Rules and Final Agent behavior are outside this evaluator.

Each case reports status match, expected issue-code coverage, expected
field/location coverage, unexpected blocking issues, critic completion, critic
revision count, denial-stage match, and an overall semantic match. Natural
language summaries and explanations are not scored. Focused critic probes under
[`critic_expected/`](../evals/validation/semantic/critic_expected/) remain
contract-test fixtures; they are not a second end-to-end evaluation flow.

The current expected root field for the relative-date case is `due_date`; the
raw `additional_fields.due_date_raw` value is evidence, not a second missing
field failure. Reconciliation-only observations such as missing
`invoice_total`/`amount_due` or payment-term date arithmetic are intentionally
not Semantic expectations.

Each run writes JSON artifacts under `logs/evals/<evaluation_id>/`. Normal
validation artifacts remain the same (`validation_input.json`, versioned
`semantic_vN.json`, `semantic_critic_vN.json`, `reconciliation_vN.json`,
`reconciliation_critic_vN.json`, and `validation_result.json`), with
`expected.json`, `evaluation.json`, and a suite `summary.json` added by the
evaluator. Terminal output reports actual stage work, expected stop, final
state comparison, and `EVAL: PASS` or `EVAL: FAIL` per case.

## Adding a new feature

Add a representative fixture, expected output, focused regression test, and an
evaluation artifact description. For a new agent domain, add its checks under
that domain's folder in [`docs/agents/`](agents/) and link the results here.
Do not treat a green model call as acceptance; acceptance requires a deterministic
check or an explicitly documented human-review boundary.

## Reconciliation scoring contract

The reusable Phase 2 scorer checks status, issue-code and field coverage,
consolidation accuracy, arithmetic accuracy, unexpected blocking issues, critic
completion, critic revisions, and structured final-state match. It is called by
the Validation Agent evaluator rather than run as a standalone Phase 2 suite.
Artifacts preserve the input reference, expected Semantic/Reconciliation
blocks, actual full validation result, consolidated items, calculations, critic
records, revision counts, routing, and metric comparison. They contain no
hidden chain-of-thought.
