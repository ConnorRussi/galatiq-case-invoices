# Configuration

`main.py` loads `.env` from the project root.

| Variable | Required | Meaning |
| --- | --- | --- |
| `TAMUS_AI_CHAT_API_KEY` | Model-backed runs | Bearer key |
| `TAMUS_AI_CHAT_MODEL` | Model-backed runs | Default exact model ID |
| `TAMUS_AI_CHAT_API_ENDPOINT` | No | Defaults to `https://chat-api.tamu.ai` |
| `INVENTORY_DATABASE_PATH` | No | Default inventory path |
| `INVOICE_LEDGER_PATH` | No | Default invoice-history path |
| `BUSINESS_RULE_MODEL` | No | Business Rule model override |
| `VP_REASONING_MODEL` / `VP_MODEL` | No | VP model choices |
| `LANGSMITH_TRACING` | No | Optional tracing |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | No | LangSmith settings |

CLI path options take precedence over environment variables. The model endpoint receives `/api/chat/completions`, bearer authentication, a JSON schema in the system message, and a non-streaming request. The HTTP timeout is 120 seconds.
