# Configuration

`main.py` loads `.env` from the project root.

Grok is the default provider. Add `-tamu` to a `main.py` command to select TAMUS for that run.

| Variable | Required | Meaning |
| --- | --- | --- |
| `XAI_API_KEY` | Model-backed runs | xAI bearer key |
| `XAI_MODEL` | No | Defaults to `grok-3-mini` |
| `XAI_API_ENDPOINT` | No | Defaults to `https://api.x.ai/v1` |
| `TAMUS_AI_CHAT_API_KEY` | With `-tamu` | TAMUS bearer key |
| `TAMUS_AI_CHAT_MODEL` | With `-tamu` | TAMUS model ID |
| `TAMUS_AI_CHAT_API_ENDPOINT` | No | Defaults to `https://chat-api.tamu.ai` |
| `INVENTORY_DATABASE_PATH` | No | Default inventory path |
| `INVOICE_LEDGER_PATH` | No | Default invoice-history path |
| `LANGSMITH_TRACING` | No | Optional tracing |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | No | LangSmith settings |

CLI path options take precedence over environment variables. Grok receives `/chat/completions`; TAMUS receives `/api/chat/completions`. Both use bearer authentication, a JSON schema in the system message, and a non-streaming request. The HTTP timeout is 120 seconds.
