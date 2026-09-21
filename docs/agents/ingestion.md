# Ingestion Agent

## Purpose

Ingestion owns source representation, normalization, evidence, critique, and the bounded correction loop. Its public boundary is [`run_ingestion`](../../src/invoice_system/ingestion/runner.py).

## Explicit Non-Responsibilities

It does not decide whether an invoice is valid, calculate missing totals, check inventory, apply approval policy, or pay. The source reader must not interpret invoice fields.

## Inputs And Outputs

Input is a path to PDF, TXT, Markdown, CSV, JSON, or XML. Output is [`IngestionResult`](../../src/invoice_system/ingestion/models.py): status, source path, frozen `SourceDocument`, `NormalizationResult`, final `CritiqueResult`, revision count, and optional technical error.

`NormalizationResult` contains `NormalizedInvoice` and `FieldEvidence`. Critique issues identify incorrect values, missing information, unsupported inference, structure mismatch, or evidence problems.

## Tools And Dependencies

- `pdfplumber` extracts native PDF text; OCR is unavailable.
- Python CSV, JSON, XML, and UTF-8 readers represent non-PDF formats.
- `invoke_structured` calls the configured xAI Grok model.
- `normalization_policy.md` constrains field mapping, evidence, ambiguity, and preservation.
- `run_logging.py` writes source, normalized, critique, and result artifacts.

## Processing Flow

1. Read and syntax-check the source into immutable chunks.
2. Ask the normalizer for structured claims and evidence.
3. Ask the critic to review fidelity and evidence.
4. Sanitize critique paths/proposals deterministically.
5. If issues remain and the budget permits, revise normalization using feedback.
6. Gate the result as `accept`, `needs_review`, or `technical_failure`.

## Prompt And Deterministic Logic

The model maps explicit labels such as `Amount Due` and preserves ambiguous claims in `additional_fields`. It must not derive business values or silently correct semantic mistakes. Deterministic code validates paths, drops no-op or schema-incompatible proposals, preserves source chunks, and records events.

## Critic / Revision Loop

`MAX_REVISIONS` is 2. Critique issues can cause revision; instability can bypass another revision and reach the gate. A technical exception becomes a structured technical failure. There is no promise that `accept` means business-valid.

## Handoff Contract

Validation may assume an accepted/reviewable result has a readable source, normalized invoice, and evidence. It must still perform all semantic, arithmetic, and database checks.

## Relevant Source Files

[`source_reader.py`](../../src/invoice_system/ingestion/source_reader.py), [`normalizer.py`](../../src/invoice_system/ingestion/normalizer.py), [`critic.py`](../../src/invoice_system/ingestion/critic.py), [`graph.py`](../../src/invoice_system/ingestion/graph.py), [`models.py`](../../src/invoice_system/ingestion/models.py), and [`normalization_policy.md`](../../src/invoice_system/ingestion/normalization_policy.md).
