# Configuration and dependencies

`config.toml` is the checked-in default. `config.py` validates it with Pydantic and applies environment overrides. The override name is `INGESTION_<SECTION>_<FIELD>` in uppercase. For example:

```powershell
$env:INGESTION_LIMITS_MAX_TOTAL_MODEL_REQUESTS = "5"
$env:INGESTION_MODELS_FLASH_MODEL = "gemini-3.8-flash"
```

`GEMINI_API_KEY` is the only live-provider secret read by this agent. It belongs in the workspace `.env`, never in TOML, artifacts, or source control. `XAI_API_KEY` is reserved for the future Grok adapter; the adapter currently returns a clear unavailable error rather than silently falling back.

## Settings that change behavior

| Section | Setting | Effect |
| --- | --- | --- |
| `models` | `provider`, `flash_model`, `pro_model` | Provider choice and model IDs. |
| `limits` | `max_total_model_requests` | Global cap; every HTTP attempt, including a retry, consumes one. |
| `limits` | `max_interpret_attempts`, `max_flash_critic_runs`, `max_flash_revisions`, `max_pro_escalations` | Per-stage bounds enforced by LangGraph. |
| `limits` | `max_graph_steps` | Final guard against unexpected routing cycles. |
| `limits` | `max_transport_retries_per_call`, `request_timeout_seconds` | Single-call transport behavior. |
| `documents` | `max_file_bytes`, `max_pdf_pages`, `max_extracted_characters`, `minimum_alphanumeric_characters` | Input safety and text-versus-vision routing. |

Keep configured bounds small and test any change that allows another transition. The model prompt is not a control mechanism.

## Dependency ownership

`requirements.txt` and `requirements-dev.txt` list exactly what this agent needs. The same separation appears in `pyproject.toml` as the `ingestion` and `ingestion-dev` optional dependency groups. The base project declares no runtime dependencies, so a future validation, approval, or payment agent can define and install its own group without taking on Gemini, LangGraph, or PDF dependencies.
