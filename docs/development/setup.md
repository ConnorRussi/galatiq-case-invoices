# Development Setup

Requirements: Python 3.13 or later. From `galatiq-case-invoices/`:

```bash
python -m pip install -e ".[ingestion,ingestion-dev]"
```

Copy `.env.example` to `.env` and set `XAI_API_KEY`. The default model is `grok-3-mini`; set `XAI_MODEL` only when you need a different xAI model. To use TAMUS, configure its `TAMUS_AI_CHAT_*` variables and add `-tamu` to the command. The pytest suite replaces model calls where tests need controlled behavior. The project includes `inventory.sqlite`; use `--database-path` for another SQLite inventory.

Do not commit `.env`, credentials, generated `logs/runs/`, or temporary test output. The base package has no mandatory dependencies; the `ingestion` extra supplies runtime packages and `ingestion-dev` supplies pytest tooling.
