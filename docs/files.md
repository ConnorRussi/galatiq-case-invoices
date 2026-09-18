# File and directory map

This map covers durable project files. Generated runs, caches, compiled
bytecode, local credentials, and build metadata are intentionally omitted.

## Entry points and configuration

| Path | Role | Connected docs |
| --- | --- | --- |
| [`main.py`](../main.py) | CLI for one run or `--eval-ingestion` | [architecture](architecture.md), [runtime](runtime.md) |
| [`pyproject.toml`](../pyproject.toml) | Python metadata and optional dependencies | [runtime](runtime.md) |
| [`.env.example`](../.env.example) | Credential-free configuration template | [runtime](runtime.md) |
| [`README.md`](../README.md) | Existing project overview and case context | [architecture](architecture.md) |
| [`PHASE1_HANDOFF.md`](../PHASE1_HANDOFF.md) | Historical handoff, schemas, decisions, and verification | [contracts](contracts.md) |

## Application package

| Path | Role |
| --- | --- |
| [`src/invoice_system/agent_runtime.py`](../src/invoice_system/agent_runtime.py) | Shared model invocation, schema correction, retries, and tracing |
| [`src/invoice_system/ingestion/models.py`](../src/invoice_system/ingestion/models.py) | Source, invoice, evidence, critique, and result contracts |
| [`src/invoice_system/ingestion/state.py`](../src/invoice_system/ingestion/state.py) | Typed LangGraph state |
| [`src/invoice_system/ingestion/source_reader.py`](../src/invoice_system/ingestion/source_reader.py) | Format-aware source extraction |
| [`src/invoice_system/ingestion/normalizer.py`](../src/invoice_system/ingestion/normalizer.py) | Normalization and revision prompts |
| [`src/invoice_system/ingestion/normalization_policy.md`](../src/invoice_system/ingestion/normalization_policy.md) | Shared prompt policy |
| [`src/invoice_system/ingestion/critic.py`](../src/invoice_system/ingestion/critic.py) | Read-only fidelity review and issue filtering |
| [`src/invoice_system/ingestion/graph.py`](../src/invoice_system/ingestion/graph.py) | Workflow, routes, and revision bound |
| [`src/invoice_system/ingestion/gate.py`](../src/invoice_system/ingestion/gate.py) | Completed and technical-failure results |
| [`src/invoice_system/ingestion/runner.py`](../src/invoice_system/ingestion/runner.py) | Official execution and persistence boundary |
| [`src/invoice_system/ingestion/run_logging.py`](../src/invoice_system/ingestion/run_logging.py) | Run IDs, events, and JSON artifacts |
| [`src/invoice_system/ingestion/evaluation.py`](../src/invoice_system/ingestion/evaluation.py) | Golden comparison and adversarial checks |
| [`src/invoice_system/validation/`](../src/invoice_system/validation/) | Phase 1 semantic agent, shared critic, typed state/contracts, graph, and runner |

## Inputs and verification

| Path | Role |
| --- | --- |
| [`data/invoices/`](../data/invoices/) | Mixed-format invoice fixtures |
| [`evals/ingestion/expected/`](../evals/ingestion/expected/) | Expected normalized outputs |
| [`tests/`](../tests/) | Runtime, ingestion, and policy tests |
| [`inventory.sqlite`](../inventory.sqlite) | Existing case database; not read by ingestion or Phase 1 semantic validation |
