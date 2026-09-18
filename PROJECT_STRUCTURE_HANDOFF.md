# Project Structure Handoff

This document is a map of the active invoice-ingestion project for handing to a web implementation or another engineer. It focuses on where the executable scripts live, what each one does, and how data moves through the system.

## Project type

- Python 3.13+ application
- Package source lives under `src/`
- CLI entry point is `main.py`
- LangGraph orchestrates ingestion
- Pydantic defines the input/output contracts
- TAMUS AI Chat API provides structured LLM output
- Supported input formats: PDF, TXT, Markdown, CSV, JSON, XML

## Important file tree

```text
galatiq-case-invoices/
├── main.py                                  # CLI entry point
├── pyproject.toml                           # Python package metadata/dependencies
├── README.md                                # Project description and setup notes
├── PHASE1_HANDOFF.md                        # Phase 1 implementation decisions/schemas
├── PROJECT_STRUCTURE_HANDOFF.md              # This handoff document
├── .env.example                              # Safe environment-variable template
├── inventory.sqlite                          # Present SQLite file; not used by active Phase 1 flow
│
├── src/
│   └── invoice_system/
│       ├── __init__.py
│       ├── agent_runtime.py                  # Shared TAMUS LLM/API invocation
│       └── ingestion/
│           ├── __init__.py
│           ├── models.py                     # Pydantic data contracts
│           ├── state.py                      # LangGraph state shape
│           ├── source_reader.py              # Reads files into immutable source chunks
│           ├── normalizer.py                 # LLM prompt + invoice normalization
│           ├── critic.py                     # LLM fidelity/evidence review
│           ├── normalization_policy.py       # Loads shared normalization rules
│           ├── normalization_policy.md      # Human-readable normalization rules
│           ├── graph.py                      # LangGraph nodes, routing, revision limit
│           ├── gate.py                       # Builds final success/failure result
│           ├── runner.py                     # Official execution boundary
│           ├── run_logging.py                # Run directories, events, JSON artifacts
│           └── evaluation.py                 # Golden-fixture regression evaluation
│
├── data/
│   └── invoices/                             # Sample input invoices in multiple formats
│
├── evals/
│   └── ingestion/
│       └── expected/                         # Expected normalized outputs/statuses
│
└── tests/
    ├── test_agent_runtime.py                 # Structured API retry/error behavior
    ├── test_ingestion_regressions.py         # Evidence, critic, and regression behavior
    └── test_normalization_policy.py          # Shared policy/prompt consistency
```

`logs/`, `runs/`, `.pytest_cache/`, `__pycache__/`, build metadata, and generated evaluation artifacts are runtime/development output rather than source code. They should normally be excluded from a web rewrite or source handoff.

## Runtime flow

The code currently implements this flow:

```text
main.py
  └── run_ingestion()
        └── LangGraph
              START
                ↓
          read_source
                ↓
           normalize
                ↓
            critic
             ↙   ↘
        revise     gate
          └──→ critic  ↓
                    END
```

`critic → revise` is conditional. If issues are found and the revision budget remains, the normalized invoice is revised and reviewed again. The current maximum is `MAX_REVISIONS = 2` in `graph.py`. If no issues remain, or the budget is exhausted, the workflow goes to `gate`.

## Script responsibilities

### `main.py`

Command-line interface. It:

1. Loads `.env`.
2. Accepts `--invoice_path` for a single invoice run.
3. Accepts `--eval-ingestion` for the fixture evaluation suite.
4. Creates a run context under `logs/runs/`.
5. Calls `run_ingestion()`.
6. Prints the final status, normalized invoice, and artifact directory.

Example commands:

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
python main.py --eval-ingestion
```

### `src/invoice_system/agent_runtime.py`

The only shared LLM transport layer. `invoke_structured()`:

- Reads `TAMUS_AI_CHAT_API_KEY`, `TAMUS_AI_CHAT_MODEL`, and optional endpoint settings.
- Sends a bearer-authenticated request to `/api/chat/completions`.
- Includes the Pydantic JSON schema in the system prompt.
- Parses the response as JSON and validates it with the requested Pydantic model.
- Retries transient HTTP/transport failures.
- Gives one schema-correction attempt when structured output validation fails.
- Raises `ModelInvocationError` for configuration, API, or invalid-output failures.

### `source_reader.py`

`read_source(path)` is format-aware but does not interpret invoice fields. It preserves source material as `SourceDocument` and immutable `SourceChunk` objects.

- PDF: extracts one chunk per page with `pdfplumber`; textless pages fail with an OCR-required error.
- TXT/Markdown: one text chunk.
- CSV: header and rows are preserved as JSON-array text; row numbers are tracked.
- JSON: syntax-checks and preserves the original text.
- XML: syntax-checks, rejects DTD/entity declarations, and preserves the original text.
- Text decoding is strict UTF-8 with optional BOM support.

### `models.py`

Defines the typed contracts shared by every stage:

- Source: `SourceChunk`, `SourceDocument`
- Normalization: `NormalizedLineItem`, `NormalizedInvoice`, `FieldEvidence`, `NormalizationResult`
- Critique: `CritiqueIssueType`, `CritiqueIssue`, `CritiqueResult`
- Final run: `IngestionStatus`, `IngestionResult`

Monetary and quantity values use `Decimal`; dates use `date`; source models are frozen to protect source immutability.

### `normalizer.py`

Builds the normalization prompt, injects the shared policy and source document, invokes the LLM for a `NormalizationResult`, and supports `revise_normalization()` when the critic finds issues.

The normalizer must preserve source meaning, avoid deriving missing business values, keep ambiguous claims in `additional_fields`, and attach evidence to populated fields.

### `critic.py`

Builds the fidelity-review prompt and asks the LLM to check a candidate normalization against the immutable source. It also applies local safeguards to reject malformed or self-contradictory critique output and checks evidence references.

The critic can report incorrect values, missing information, unsupported inference, structure mismatch, or evidence problems.

### `normalization_policy.py` and `normalization_policy.md`

`load_normalization_policy()` loads the policy text used by the normalizer, critic, and revision prompt. The Markdown file is the single editable policy source for normalization behavior.

### `graph.py`

Defines LangGraph nodes and routing:

- `read_source_node`
- `normalize_node`
- `critic_node`
- `revise_node`
- `gate_node`
- `route_critique`
- `build_graph`

### `runner.py`

The public application boundary: `run_ingestion()`.

It streams graph updates, tracks the current source/normalization/critique state, persists artifacts after each stage, converts unexpected exceptions into a `technical_failure` result, and returns the final `IngestionResult`.

### `gate.py`

Converts completed graph state into the final result. A clean final critique produces `accept`; unresolved critique issues produce `needs_review`; unexpected execution errors produce `technical_failure`.

### `run_logging.py`

Creates run IDs and writes JSON artifacts and event logs. A normal run typically contains:

```text
logs/runs/<run_id>/
├── run.json
├── events.jsonl
├── source.json
├── normalized_v1.json
├── critique_v1.json
├── normalized_v2.json       # only if revised
├── critique_v2.json         # only if revised
├── normalized.json          # final normalization, on completion
└── result.json
```

### `evaluation.py`

Runs every JSON file in `evals/ingestion/expected/` against its matching fixture in `data/invoices/`. It compares status, scalar fields, line items, additional fields, and evidence. It also runs critic mutation challenges such as wrong values, missing fields, canonicalized item names, and corrected source mistakes.

## Configuration

Copy `.env.example` to `.env` and provide:

```text
TAMUS_AI_CHAT_API_KEY=...
TAMUS_AI_CHAT_MODEL=...
TAMUS_AI_CHAT_API_ENDPOINT=https://chat-api.tamu.ai   # optional override
LANGSMITH_TRACING=true                                # optional
LANGSMITH_API_KEY=...                                 # optional
```

Never include the real `.env` or API credentials in a web handoff.

## Current scope boundaries

The active implementation is Phase 1 ingestion. The following background-case features are not part of the current executable flow even though they are described in the original README: inventory validation, approval, payment, arithmetic validation, and a full end-to-end multi-agent workflow.

Also note that portions of `README.md` and `PHASE1_HANDOFF.md` describe an older two-node flow. For current behavior, treat `graph.py`, `runner.py`, and the tests as the implementation source of truth.

