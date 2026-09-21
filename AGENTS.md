# Agent instructions

These instructions apply to every change in this repository.

## Repository orientation

Read [`docs/index.md`](docs/index.md) first. It is the documentation graph for
humans and coding agents. Follow links from there to the relevant architecture
and feature node before editing code. The normal CLI currently implements the
full workflow: ingestion, invoice-history checks, Semantic/Reconciliation/
Database validation, Business Rule/optional VP approval, and local mock payment.
The individual domains also have isolated runners and evaluation suites.

## Documentation is part of the implementation

Keep the documentation graph synchronized with the code. When a change affects
execution flow, graph nodes, routes, state, or stage ownership, update
[`docs/architecture/pipeline.md`](docs/architecture/pipeline.md),
[`docs/architecture/state-and-data-flow.md`](docs/architecture/state-and-data-flow.md),
and [`docs/architecture/agent-contracts.md`](docs/architecture/agent-contracts.md).
When it affects source formats, normalization, evidence, critique, revision, or
statuses, update [`docs/agents/ingestion.md`](docs/agents/ingestion.md) and
[`docs/reference/normalization-policy.md`](docs/reference/normalization-policy.md).
Update [`docs/development/configuration.md`](docs/development/configuration.md)
for API/configuration/retry behavior and [`docs/evaluation/overview.md`](docs/evaluation/overview.md)
for fixtures or checks. Update [`docs/development/repository-structure.md`](docs/development/repository-structure.md)
for durable files and directories added, removed, renamed, or repurposed.

When adding a new domain agent, create or update its page under
[`docs/agents/`](docs/agents/), then link it from [`docs/index.md`](docs/index.md)
and [`docs/README.md`](docs/README.md).

Keep the canonical reviewer guide at [`docs/README.md`](docs/README.md). Use
descriptive pages under the existing architecture, agents, evaluation,
development, and reference directories.

## Required change notes

When adding a feature, document its owner, inputs, outputs, downstream
consumers, failure behavior, and test/evaluation coverage. Add links to source
files and tests using repository-relative Markdown links. If behavior is
planned but not implemented, label it as planned rather than describing it as
available.

When changing a graph or contract, update the graph and contract docs before
running final verification. Keep the top-level `README.md` and any retained
historical handoff as user-facing context; do not silently use them as the only
source of truth when they disagree with current code.

## Verification

Run focused tests for the area changed, then the full suite when practical:

```bash
python -m pytest
```

Do not commit credentials, generated `runs/`, `.pytest_cache/`, or temporary
test output. Document durable artifact schemas and locations, not individual
generated run directories.

