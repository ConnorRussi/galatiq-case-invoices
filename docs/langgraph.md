# LangGraph workflow

The ingestion workflow is defined in
[`src/invoice_system/ingestion/graph.py`](../src/invoice_system/ingestion/graph.py).

```text
START -> read_source -> normalize -> critic -> revise (max 2) -> gate -> END
```

Phase 1 validation is a separate graph in
[`src/invoice_system/validation/graph.py`](../src/invoice_system/validation/graph.py):

```text
START -> semantic -> semantic_critic
                    ├─ REVISE within bound -> semantic
                    ├─ confirmed DENY -> finalize_denied -> END
                    └─ confirmed PASS -> finalize_valid_for_phase_1 -> END
```

The critic disagreement limit is `MAX_CRITIC_REVISIONS = 2`. A further
unresolved `REVISE` routes to `finalize_unresolved`, which fails closed as
`DENIED` with reason `unresolved_validation`. A critic-confirmed denial
short-circuits this prototype before any future downstream stages.

## Nodes

| Node | Reads | Writes | Notes |
| --- | --- | --- | --- |
| `read_source` | `source_path` | `source_document` | Format-aware, source-only extraction |
| `normalize` | `source_document` | `normalization`, `revision_count=0` | First structured model call |
| `critic` | source, normalization, revision count | `critique` | Read-only fidelity review |
| `revise` | source, normalization, critique | new normalization, incremented count | Maximum two revisions |
| `gate` | all state | `result` | Builds terminal result |
| `semantic` | immutable `IngestionResult`, revision feedback | `semantic_result` | Whole-invoice semantic specialist |
| `semantic_critic` | ingestion snapshot, semantic result | `critic_result`, revision routing | Shared critic; never decides PASS/DENY itself |
| `finalize_valid_for_phase_1` | confirmed semantic PASS | `final_result` | Phase 1 PASS endpoint |
| `finalize_denied` / `finalize_unresolved` | confirmed DENY or exhausted revisions | `final_result` | Fail closed; unresolved reason is `unresolved_validation` |

State is declared in [`state.py`](../src/invoice_system/ingestion/state.py).
It includes the source path, optional source document, normalization, critique,
revision count, and final result. Node functions return partial updates; the
runner consumes graph stream updates to persist artifacts.

Validation state is declared in
[`validation/state.py`](../src/invoice_system/validation/state.py). It retains a
deep snapshot of the original `IngestionResult`, semantic and critic results,
revision feedback/count, current stage, and final result. The validation graph
does not mutate the ingestion invoice.

## Change rules

When adding a node, document its input/output contract, route, revision or
retry bound, artifact behavior, and tests. Update this page and
[`architecture.md`](architecture.md) in the same change. Keep routes explicit;
an agent must not infer an acceptance transition from a model response without
a typed state update and a test.
