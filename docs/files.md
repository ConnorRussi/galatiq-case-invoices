# File and directory map

This map covers durable project files. Generated runs, caches, compiled
bytecode, local credentials, and build metadata are intentionally omitted.

## Entry points and configuration

| Path | Role | Connected docs |
| --- | --- | --- |
| [`main.py`](../main.py) | CLI for one run, ingestion/validation evaluations, or the standalone approval evaluation | [architecture](architecture.md), [runtime](runtime.md) |
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
| [`src/invoice_system/validation/`](../src/invoice_system/validation/) | Semantic -> Reconciliation -> Database agents, shared critic, typed contracts, graphs, and runners |
| [`src/invoice_system/validation/evaluation.py`](../src/invoice_system/validation/evaluation.py) | End-to-end Validation Agent scoring, routing checks, artifacts, and terminal output |
| [`src/invoice_system/validation/reconciliation.py`](../src/invoice_system/validation/reconciliation.py) | Phase 2 specialist and scope contract |
| [`src/invoice_system/validation/arithmetic.py`](../src/invoice_system/validation/arithmetic.py) | Decimal-safe arithmetic and consolidation evidence |
| [`src/invoice_system/validation/reconciliation_evaluation.py`](../src/invoice_system/validation/reconciliation_evaluation.py) | Reusable structured Phase 2 scoring helper used by the Validation Agent evaluator |
| [`src/invoice_system/validation/reconciliation_runner.py`](../src/invoice_system/validation/reconciliation_runner.py) | Phase 2 execution boundary used by validation runtime/tests |
| [`src/invoice_system/validation/database.py`](../src/invoice_system/validation/database.py) | Agent-directed, bounded inventory lookup rounds and database scope prompt |
| [`src/invoice_system/validation/database_tool.py`](../src/invoice_system/validation/database_tool.py) | Exact read-only bulk SQLite lookup boundary |
| [`src/invoice_system/validation/database_runner.py`](../src/invoice_system/validation/database_runner.py) | Database specialist and shared-critic execution boundary |
| [`src/invoice_system/approval/`](../src/invoice_system/approval/) | Business-rule and VP approval contracts, graph, runner, policy, and audit logging |
| [`src/invoice_system/approval/evaluation.py`](../src/invoice_system/approval/evaluation.py) | Approval routing and final-bucket evaluator |

## Inputs and verification

| Path | Role |
| --- | --- |
| [`data/invoices/`](../data/invoices/) | Mixed-format invoice fixtures |
| [`evals/ingestion/expected/`](../evals/ingestion/expected/) | Expected normalized outputs |
| [`evals/validation/semantic/`](../evals/validation/semantic/) | Semantic expectations, controlled fixtures, and critic cases; references ingestion goldens without changing them |
| [`evals/validation/reconciliation/`](../evals/validation/reconciliation/) | Controlled Phase 2 fixtures, expected results, and critic cases |
| [`evals/approval/cases/`](../evals/approval/cases/) | Trusted upstream-pass cases for approval routing and final-status evaluation |
| [`tests/`](../tests/) | Runtime, ingestion, validation, reconciliation, database, approval, and policy tests |
| [`inventory.sqlite`](../inventory.sqlite) | Existing case database used by Phase 3 Database validation |
