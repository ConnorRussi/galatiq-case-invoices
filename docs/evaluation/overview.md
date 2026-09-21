# Evaluation Overview

The repository has two verification layers. `pytest` checks deterministic behavior, contracts, graph routing, artifacts, and model boundaries with controlled responses. The `main.py --eval-*` suites run fixture-driven comparisons through selected live stage boundaries.

| Suite | Inputs | What it catches |
| --- | --- | --- |
| Ingestion | Source corpus and `evals/ingestion/expected/` | Extraction fidelity, evidence coverage, critic challenges, revision behavior |
| Validation | Trusted ingestion goldens and validation fixtures | Semantic scope, arithmetic, identity, inventory, critics, and routes |
| Approval | `evals/approval/cases/` with trusted `VALID`/`PASS` inputs | Policy routes, threshold escalation, VP outcomes |
| Workflow | Every `data/invoices/` file and synthetic VP cases | End-to-end terminal status, stop stage, fields, and audit events |

Evaluators compare stable structured fields rather than free-form reasoning. A passing expected denial means the system denied the right case; it does not mean payment occurred. Evaluation is regression and general-situation coverage, not proof of every nondeterministic live response.

Artifacts are written under `logs/evals/<evaluation_id>/`. The dashboard displays completed workflow summaries but does not rescore them. See [running evaluations](running-evals.md) and the stage-specific pages in this directory for fixture and artifact details.
