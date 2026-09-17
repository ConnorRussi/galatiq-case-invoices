# Ingestion agent

This directory owns the first agent in the invoice workflow. It receives PDF paths and produces one `BatchResult` containing an `IngestionResult` for each source. The result is the only object the orchestrator needs to hand to the next agent.

The top-level `main.py` deliberately does not parse invoices or import any validation code. It collects CLI paths, calls `invoice_system.ingestion.run_pipeline(paths)`, and prints or hands off the returned `BatchResult`.

## Where to look

| Need | File or folder |
| --- | --- |
| Public entry point and handoff types | `__init__.py` |
| LangGraph nodes, routing, limits, batch isolation | `workflow.py` |
| Typed state, proposal, candidate, issue, and result models | `models.py` |
| PDF size/type/page checks and coordinate extraction | `extraction.py` |
| Accepted money, date, product, and identifier transformations | `normalization.py` |
| Gemini contract and future Grok adapter boundary | `providers.py` |
| Offline model double and scripted failures | `fake.py` |
| Atomic JSON snapshots and append-only events | `artifacts.py` |
| TOML settings and environment overrides | `config.toml`, `config.py` |
| Generated PDF fixture script | `scripts/generate_pdfs.py` |
| Golden corpus and ingestion evaluation helpers | `evals/`, `evaluation.py` |
| Tests for this agent only | `tests/` |
| Dependency lists for this agent only | `requirements.txt`, `requirements-dev.txt` |

Read [architecture.md](architecture.md) for the runtime sequence, [configuration.md](configuration.md) before changing limits or models, [handoff.md](handoff.md) before building the next agent, and [testing.md](testing.md) when modifying behavior.

## Run it

Install only this agent's runtime dependencies from the repository root:

```powershell
python -m pip install -e ".\galatiq-case-invoices[ingestion]"
```

To run the tests too:

```powershell
python -m pip install -e ".\galatiq-case-invoices[ingestion,ingestion-dev]"
python -m pytest galatiq-case-invoices
```

Set `GEMINI_API_KEY` in the workspace `.env` for live calls. Then run either:

```powershell
python main.py --generate-pdfs
python main.py --invoice_path data/invoices/invoice_1011.pdf
```

The normal test suite uses `FakeProvider`, never requires a key, and blocks network access. Live tests use the `live` marker and remain excluded by default.
