# Agent instructions

These instructions apply to every change in this repository.

## Repository orientation

Read [`docs/index.md`](docs/index.md) first. It is the documentation graph for
humans and coding agents. Follow links from there to the relevant architecture
and feature node before editing code. The current implementation is an invoice
ingestion pipeline; validation, approval, and payment are not implemented
production stages yet.

## Documentation is part of the implementation

Keep the documentation graph synchronized with the code. When a change affects
execution flow, graph nodes, routes, state, or stage ownership, update
[`docs/langgraph.md`](docs/langgraph.md) and [`docs/architecture.md`](docs/architecture.md).
When it affects source formats, normalization, evidence, critique, revision, or
statuses, update [`docs/ingestion.md`](docs/ingestion.md) and, when contracts
change, [`docs/contracts.md`](docs/contracts.md). Update
[`docs/runtime.md`](docs/runtime.md) for API/configuration/retry behavior and
[`docs/evaluation.md`](docs/evaluation.md) for fixtures or checks. Update
[`docs/files.md`](docs/files.md) for durable files and directories added,
removed, renamed, or repurposed.

When adding a new domain agent, create or update its own folder under
[`docs/agents/`](docs/agents/), then link it from [`docs/index.md`](docs/index.md).

Do not create a generic `README.md` for a new feature area. Use a descriptive
name such as `ingestion.md`, `langgraph.md`, `validation/overview.md`, or
`acceptance/checks.md`.

## Required change notes

When adding a feature, document its owner, inputs, outputs, downstream
consumers, failure behavior, and test/evaluation coverage. Add links to source
files and tests using repository-relative Markdown links. If behavior is
planned but not implemented, label it as planned rather than describing it as
available.

When changing a graph or contract, update the graph and contract docs before
running final verification. Keep the top-level `README.md` and
`PHASE1_HANDOFF.md` as historical/user-facing references; do not silently use
them as the only source of truth when they disagree with current code.

## Verification

Run focused tests for the area changed, then the full suite when practical:

```bash
python -m pytest
```

Do not commit credentials, generated `runs/`, `.pytest_cache/`, or temporary
test output. Document durable artifact schemas and locations, not individual
generated run directories.

