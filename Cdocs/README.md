# Cdocs — Developer Context Hub

`Cdocs` is the repository's concise, code-oriented map for people and agents. It answers three questions quickly:

1. What exists and runs now?
2. Which module owns a concern and what does it hand off?
3. Where should a change be documented so the next contributor does not need to rediscover the system?

This is an operational reference, not a replacement for the case brief or detailed implementation notes in `docs/` and `src/invoice_system/ingestion/docs/`. When those documents disagree with executable code, treat code and its tests as current behavior; update the affected Cdocs page as part of the change.

## Start here

| Need | Read |
| --- | --- |
| Orient yourself in the current product | [System map](system-map.md) |
| Run or change the CLI boundary | [Orchestration](orchestration/README.md) |
| Understand extraction, one model call, and artifacts | [Ingestion](ingestion/README.md) |
| Validate candidates against trusted tools and deterministic rules | [Validation](validation/README.md) |
| Define testable completion criteria | [Acceptance](acceptance/README.md) |
| Add a new feature without losing context | [Documentation protocol](documentation-protocol.md) |

## Current implementation boundary

Implemented POC: the CLI and evidence-preserving ingestion pipeline read one PDF/TXT/JSON/CSV/XML source, extract native text, make one structured model extraction request, validate its schema, and persist machine-readable artifacts plus a human-readable run report. It does not normalize business values, retry, critique, revise, or validate the invoice.

Implemented validation slice: `src/invoice_system/validation/` exposes `validate_invoice`, a bounded LangGraph investigation workflow, deterministic rules, read-only SQLite tools, an offline agent/structured-provider adapter, tests, and a persisted-handoff CLI. `main.py` remains ingestion-only; applications can compose the public APIs. Approval/Critic decisions, payment simulation, and human-review UI/workflow are still planned.

## Directory convention

Each system area gets a top-level folder with a `README.md` that begins with its current state, owner/module boundaries, inbound and outbound contracts, operational notes, and related tests. Add deeper documents only when an area has enough detail to need one; keep the entry document short and link outward.

The planned durable areas are:

```text
Cdocs/
├── ingestion/       # Implemented source-to-candidate pipeline
├── validation/      # Implemented candidate-to-findings slice
├── approval/        # Future decision and critique policy
├── payment/         # Future controlled, idempotent side effect
├── acceptance/      # Cross-system behaviors and test evidence
└── orchestration/   # CLI and stage composition
```

See [the documentation protocol](documentation-protocol.md) for the required update loop and the template for future areas.
