# Repository knowledge graph

This is the navigational hub for the invoice-processing repository. It is
written as a graph: each page describes a system node, names the files that
implement it, and links to the nodes it depends on or feeds. Humans can read it
top-to-bottom; agents should use it to locate the smallest relevant context
before changing code.

## Current system

```text
CLI (main.py)
  -> ingestion runner -> IngestionResult
  -> optional validation runner -> ValidationResult
  -> standalone approval runner -> ApprovalResult
  -> shared run artifacts (ingestion/run_logging.py)
```

The implemented boundaries include evidence-preserving ingestion, the
Validation Agent pipeline, and an isolated Approval Agent boundary. Approval is
not yet wired into the validation runner, and payment remains out of scope.

## Start here

- [Architecture](architecture.md) — boundaries, data flow, and implemented vs planned.
- [File map](files.md) — what each durable file and directory is for.
- [Ingestion](ingestion.md) — reading, normalization, critique, revision, and statuses.
- [Validation](agents/validation/overview.md) — semantic validation, shared critic, and bounded routing.
- [LangGraph workflow](langgraph.md) — nodes, state, routes, and invariants.
- [Contracts](contracts.md) — Pydantic models and evidence relationships.
- [Runtime](runtime.md) — model calls, configuration, retries, and artifacts.
- [Evaluation](evaluation.md) — goldens, challenge checks, commands, and outputs.

## Agent-domain extensions

Each later workflow domain gets its own folder so its purpose, contracts,
tools, policies, and acceptance checks can grow without making this hub a
single long document.

- [Validation agent](agents/validation/overview.md) — Semantic, Reconciliation, and Database stages; business rules are planned.
- [Acceptance agent](agents/acceptance/overview.md) — isolated approval decision boundary and evaluation.
- [Agent documentation maintenance](agent-maintenance.md) — page template and checklist.

## Graph vocabulary

- **Node**: a runtime component, contract, artifact, test suite, or future agent domain.
- **Edge**: a dependency, handoff, route, or ownership relationship expressed with a link or `->`.
- **Source of truth**: current Python code and tests for behavior; these docs explain and connect it.
- **Planned**: an intentional extension point with no shipped implementation.
