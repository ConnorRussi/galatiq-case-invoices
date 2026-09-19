# Runtime, configuration, and artifacts

## Invocation

`main.py` loads `.env`, creates a run context under `logs/runs/`, and calls
[`run_ingestion`](../src/invoice_system/ingestion/runner.py). Evaluation modes
write under `logs/evals/`. The runtime calls
the configured TAMUS-compatible `/api/chat/completions` endpoint through
[`agent_runtime.py`](../src/invoice_system/agent_runtime.py).

Required settings are `TAMUS_AI_CHAT_API_KEY` and `TAMUS_AI_CHAT_MODEL`.
`TAMUS_AI_CHAT_API_ENDPOINT` defaults to `https://chat-api.tamu.ai`.
LangSmith tracing is optional.
`INVENTORY_DATABASE_PATH` optionally selects the SQLite database; the
`--database-path` CLI option takes precedence.

Approval model selection uses `BUSINESS_RULE_MODEL` for the Business Rule Agent.
The VP Agent uses `VP_REASONING_MODEL`, then `VP_MODEL`, then
`BUSINESS_RULE_MODEL`, then `TAMUS_AI_CHAT_MODEL`.

## Failure and retry behavior

- Transport failures are retried up to three attempts.
- Invalid structured output gets one schema-correction attempt, then becomes a
  `ModelInvocationError`.
- Ingestion and validation return structured `technical_failure` results with
  partial completed-stage context; approval records an error artifact and raises
  because it must never manufacture an approval decision.
- Critique revisions are a workflow bound of two, separate from HTTP retries.

## Run artifacts

Each run directory can contain `run.json`, `events.jsonl`, `source.json`,
versioned normalization and critique files, `normalized.json`, and `result.json`.
Artifacts are written as stages complete, preserving partial evidence for failed
runs. `run_logging.py` serializes models, dates, decimals, and paths into JSON.
When validation is requested, the same run directory also contains
`validation_input.json`, versioned `semantic_vN.json` and
`semantic_critic_vN.json` artifacts, and, for full validation,
`reconciliation_vN.json`, `reconciliation_critic_vN.json`, `database_vN.json`,
`database_critic_vN.json`, and `validation_result.json`; technical validation
failures write `validation_error.json`. Approval failures write
`approval_error.json`. Validation events use the existing `events.jsonl` schema.

## Commands

```bash
python -m pip install -e ".[ingestion,ingestion-dev]"
python main.py --invoice_path=data/invoices/invoice_1001.txt
python main.py --invoice_path=data/invoices/invoice_1001.txt --validate
python main.py --invoice_path=data/invoices/invoice_1001.txt --validate --database-path=inventory.sqlite
python main.py --eval-ingestion
python main.py --eval-validation
python main.py --eval-approval
python -m pytest
```

`--validate` runs ingestion first and then the Semantic -> Reconciliation ->
Database validation graph against the resulting `IngestionResult`. A confirmed
Semantic DENY short-circuits Reconciliation and Database; a confirmed
Reconciliation DENY short-circuits Database. Validation uses the same TAMUS provider
abstraction and its critic revision bound is configured by `validation/config.py`.

`--eval-validation` runs the one growing Validation Agent evaluation. It loads
trusted normalized goldens and controlled structured fixtures, executes the
Semantic stage first, stops at a confirmed Semantic DENY, routes confirmed
Semantic PASS cases through Reconciliation, and routes confirmed Reconciliation
PASS cases through Database when expected. It does not rerun ingestion. The
older `--eval-semantic` and `--eval-reconciliation` flags remain compatibility
aliases for this same end-to-end evaluation; they are not separate stage
evaluators.

`--eval-approval` runs only the final approval boundary against trusted cases
whose supplied upstream statuses are `VALID` and `PASS`. It checks the direct
business-rule bucket, whether the VP branch was invoked, the VP decision, and
the final `APPROVED`/`REJECTED` bucket. It does not run ingestion, validation,
or payment.
