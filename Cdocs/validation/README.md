# Validation

**State:** implemented first vertical slice — public API, bounded LangGraph investigation, deterministic tools/rules, and persisted-handoff CLI. Approval/Critic/payment remain future stages.

## Purpose

Turn ingestion's source claims into complete validation findings. Validation owns investigation and derived representations; tools establish facts; deterministic rules evaluate those facts. It never repairs invoice claims or decides payment.

## Entry points and ownership

All modules live in [src/invoice_system/validation/](../../src/invoice_system/validation/).

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Public `validate_invoice`, tools, settings, and agent contracts |
| `workflow.py` | Graph, state isolation, hard budgets, single recheck, report assembly |
| `agent.py` | Offline observation/action policy, agent protocol, structured-model transport adapter |
| `models.py` | Typed state, facts, findings, report, mechanically derived outcome |
| `policy.py` | Mandatory checks, evidence-based recheck eligibility, targeted-result guard |
| `tools.py` | Decimal consolidation/recalculation and read-only SQLite queries |
| `rules.py` | Factual checks followed by deterministic business policy |
| `__main__.py` | Read ingestion `result.json`, emit validation report JSON |

Install the `validation` dependency extra for LangGraph; the ingestion POC does not depend on it. No credentials or network calls are required for validation's default offline agent.

```python
from invoice_system.ingestion import ingest
from invoice_system.validation import validate_invoice

batch = ingest(paths)  # Existing ingestion provider/configuration applies here.
reports = [
    validate_invoice(item.result, inventory_path="inventory.sqlite")
    for item in batch.results
    if item.result.status == "ready_for_validation"
]
```

Or validate a persisted handoff independently:

```powershell
python -m invoice_system.validation path/to/result.json --inventory-db inventory.sqlite
```

Use an editable installation (`python -m pip install -e ".[ingestion,ingestion-dev]"`) or put `src` on `PYTHONPATH`. The CLI prints JSON without writing source files or inventory. Exit zero means the invocation completed; inspect report disposition for validation results. `main.py` retains its ingestion-only behavior.

## Current behavior

```text
inspect handoff -> optional targeted re-ingestion (once)
               -> observe findings <-> request/run bounded tools
               -> deterministic business rules -> ValidationReport
```

The baseline requires handoff/input availability, line arithmetic, subtotal/total reconciliation, consolidation, inventory, and date checks. Configured high-value policy runs after factual validation. Missing prerequisites become unresolved; absent optional comparisons are skipped with an explicit reason. All independent checks run after a mismatch. Agent finish requests cannot remove mandatory work. Unknown additional check codes stay unresolved until a deterministic validator exists.

`OfflineValidationAgent` selects consolidation, arithmetic, inventory, then retries an inventory tool error once. A replacement `ValidationAgent.decide(AgentView)` receives copied observations and returns only `AgentDecision`: tool request, added checks, or an extraction recheck. `StructuredValidationAgent(transport)` calls `transport(instructions, observation_json, AgentDecision)`; the application supplies the model transport and timeout. Agents cannot supply amounts, SQL, stock, findings, or disposition. Tool arguments come from the complete candidate and consolidated identities.

## Contracts

### Receives

- Existing `IngestionResult` or direct `Invoice`; typed `ExtractedField.normalized` values, `original` source text, evidence, and issues are reused from the current ingestion contract.
- Inventory path/tool, optional reasoning provider, optional targeted re-ingestion callback.
- A partial/non-ready handoff may be inspected explicitly, but its unresolved status/issues prevent a clear result. No candidate terminates unresolved without tools.

### Produces

`ValidationReport` contains checks/statuses/reasons, structured findings and evidence, unresolved questions, facts, consolidated groups with zero-based source row indices, tool call IDs/errors, original and validated invoice snapshots, and any recheck request/result/count.

- `validation_complete=true` means every required check reached a terminal state, including `UNRESOLVED`; it does not mean validation passed.
- Blocking findings yield `blocked`; otherwise unresolved required checks yield `unresolved`; otherwise `clear`.
- Tool-budget exhaustion is the explicit exception: always `validation_complete=false`, `disposition="unresolved"`, even with blocking findings. Those findings remain in the report.
- High-value review is a warning requiring downstream scrutiny. It does not itself block validation or authorize payment; `clear` can include this warning.

Stable findings: `LINE_ITEM_TOTAL_MISMATCH`, `LINE_ITEMS_SUBTOTAL_MISMATCH`, `TOTAL_MISMATCH`, `INSUFFICIENT_INVENTORY`, `UNKNOWN_INVENTORY_ITEM`, `INVALID_LINE_ITEM_VALUE`, `INVALID_DATE_ORDER`, `HIGH_VALUE_REVIEW_REQUIRED`, `INGESTION_ISSUE_UNRESOLVED`, `VALIDATION_DATA_UNAVAILABLE`. Operational failures are unresolved checks, never invented business failures.

### Must not

Mutate source claims, discard original rows, generate SQL, invent policy/data, re-ingest because inventory/arithmetic failed, or approve/reject/execute payment. Deep copies isolate callers, agent observations, and re-ingestion callbacks.

## Configuration and model limitations

| Setting | Default / behavior |
| --- | --- |
| `money_tolerance` | `Decimal("0.01")`, inclusive absolute tolerance; unrounded line products |
| `high_value_threshold` | `Decimal("10000")`; strict greater-than on either declared or computed total; `None` disables |
| `policy_currency` | `USD`; other/missing currencies leave high-value policy unresolved, without invented FX |
| `max_tool_calls` | 6, including failures/retries; CLI supports `--max-tool-calls` |
| `max_agent_turns` | 8; mandatory tools continue within their budget after agent exhaustion, with inspection unresolved |
| Re-ingestion | Hard maximum one callback, only during initial handoff inspection |

Identity is the exact normalized name because ingestion has no separate SKU or inventory-backed flag. All rows are assumed inventory-backed. Invalid/missing quantities make their group unavailable instead of summing a subset or subtracting invalid negative rows.

Arithmetic supports quantity, unit price, declared line amounts/subtotal/total, tax, shipping, and fees. Absent optional additions remain `None`, listed in `absent_components`; they are not source zeroes. Present but unnormalized additions prevent total calculation. The schema has no tax rate or invoice-level discount; neither is invented. A fixed 64-digit Decimal context traps precision loss: excessive precision becomes unavailable tool facts rather than silent rounding. All monetary comparisons are computed in the arithmetic tool.

SQLite uses the existing `inventory(item TEXT PRIMARY KEY, stock INTEGER)` schema, parameterized exact-name queries, a read-only connection, and a read transaction. Missing/corrupt databases, malformed stock, incomplete/conflicting responses, and tool exceptions are unresolved. Validation never initializes/seeds stock; see the setup snippet in the root README. Relative database paths resolve against the caller's working directory.

`IngestionRecheckRequest` targets exact paths such as `line_items[0].quantity`. Qualifying ingestion issues (`AMBIGUOUS_EXTRACTION`, `SOURCE_CONTRADICTION`, `MISSING_EXPECTED_EVIDENCE`, or `UNSUPPORTED_EVIDENCE`) authorize a request; the current shared field model has no alternatives list. The callback receives copied `(IngestionResult, request)` and returns an `IngestionResult` for the same source/row structure, preserving untargeted fields and unrelated issues. Original claims remain in the report. Ingestion has no targeted recheck API, so the callback is application-supplied; absence/failure is unresolved, with no broad re-ingestion fallback.

## Tests and acceptance evidence

[tests/test_validation.py](../../tests/test_validation.py) covers direct candidates, SQLite, the graph and structured-provider doubles, persisted handoff CLI, arithmetic/inventory/recheck/budget cases, source isolation, partial/malformed data, high-value currency handling, and completeness. No real LLM calls.

INV-1013's eight fixture rows produce WidgetA=22, WidgetB=18, GadgetX=9, computed total 22512.80, declared total 22562.80, variance 50.00, three inventory findings, total mismatch, and high-value warning. Required work terminates; disposition is blocked, with no payment decision.

## Related documents

[Ingestion](../ingestion/README.md), [Orchestration](../orchestration/README.md), [Acceptance](../acceptance/README.md), [System map](../system-map.md). Vendor/PO/duplicate tools, provider-specific live transports, Approval/Critic, human review, and payment are deferred.
