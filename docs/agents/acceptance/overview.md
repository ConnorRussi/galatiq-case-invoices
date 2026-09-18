# Acceptance agent

Status: planned. No acceptance agent, approval decision, payment action, or
release gate is currently shipped.

## Intended boundary

Acceptance should consume typed outputs from ingestion and future validation,
apply explicit business policy, and return a decision with reasons and
evidence. A model suggestion must not authorize payment by itself. Any future
side effect needs a separate, auditable boundary and deterministic guard.

## When implemented

Document the decision states, policy thresholds, human-review path, tool and
side-effect permissions, retry/turn bounds, audit artifacts, and acceptance
tests in this folder. Link the new graph edges from [architecture](../../architecture.md)
and [LangGraph](../../langgraph.md).

