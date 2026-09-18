# Runtime, configuration, and artifacts

## Invocation

`main.py` loads `.env`, creates a run context under `logs/runs/`, and calls
[`run_ingestion`](../src/invoice_system/ingestion/runner.py). The runtime calls
the configured TAMUS-compatible `/api/chat/completions` endpoint through
[`agent_runtime.py`](../src/invoice_system/agent_runtime.py).

Required settings are `TAMUS_AI_CHAT_API_KEY` and `TAMUS_AI_CHAT_MODEL`.
`TAMUS_AI_CHAT_API_ENDPOINT` defaults to `https://chat-api.tamu.ai`.
LangSmith tracing is optional.

## Failure and retry behavior

- Transport failures are retried up to three attempts.
- Invalid structured output gets one schema-correction attempt, then becomes a
  `ModelInvocationError`.
- The runner catches stage exceptions and returns `technical_failure` with the
  failure context; it does not invent a normalized invoice.
- Critique revisions are a workflow bound of two, separate from HTTP retries.

## Run artifacts

Each run directory can contain `run.json`, `events.jsonl`, `source.json`,
versioned normalization and critique files, `normalized.json`, and `result.json`.
Artifacts are written as stages complete, preserving partial evidence for failed
runs. `run_logging.py` serializes models, dates, decimals, and paths into JSON.
When validation is requested, the same run directory also contains
`validation_input.json`, versioned `semantic_vN.json` and
`semantic_critic_vN.json` artifacts, and `validation_result.json`; validation
events use the existing `events.jsonl` schema.

## Commands

```bash
python -m pip install -e ".[ingestion,ingestion-dev]"
python main.py --invoice_path=data/invoices/invoice_1001.txt
python main.py --invoice_path=data/invoices/invoice_1001.txt --validate
python main.py --eval-ingestion
python -m pytest
```

`--validate` runs ingestion first and then Phase 1 semantic validation against
the resulting `IngestionResult`. It preserves ingestion-only behavior when the
flag is absent. Validation uses the same TAMUS provider abstraction and its
critic revision bound is configured by `validation/config.py`.
