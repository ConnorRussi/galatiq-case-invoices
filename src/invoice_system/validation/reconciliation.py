"""Phase 2 reconciliation specialist."""

from __future__ import annotations

import json

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult

from .arithmetic import build_arithmetic_evidence
from .models import ReconciliationResult, ValidationStage


RECONCILIATION_SCOPE_CONTRACT = """
PHASE 2 RECONCILIATION SCOPE CONTRACT

Reconciliation answers: "Does this semantically valid invoice reconcile
structurally and mathematically?"

Reconciliation owns:
- quantity multiplied by unit price versus each declared line amount;
- line amounts versus the declared subtotal;
- subtotal, tax, shipping, discount, and invoice total relationships when the
  corresponding values are present;
- consolidation of repeated normalized products, including combined quantity,
  derived amount, and every source line;
- conflicting prices for repeated normalized products when they make the
  invoice internally inconsistent; and
- contradictory arithmetic or omitted source lines in the specialist result.

Reconciliation must not deny because of inventory, SQL/product lookup,
vendor approval, purchase or amount thresholds, payment policy, or future
Business Agent concerns. Those belong to later stages.

Missing optional financial claims are not automatically errors. Only report a
missing value when the supplied invoice makes a comparison impossible and the
contract or an explicit expected relationship requires it. Never rewrite the
ingestion output. Return stable issue codes and invoice-relative field paths.
""".strip()


def reconciliation_scope_prompt() -> str:
    return RECONCILIATION_SCOPE_CONTRACT


def _reconciliation_prompt() -> str:
    return f"""You are the Phase 2 reconciliation validation agent.

Inspect the immutable structured ingestion output and the deterministic
arithmetic-tool evidence. Produce a structured result for the reconciliation
stage only.

{reconciliation_scope_prompt()}

Execution rules:
- Treat the arithmetic tool output as checkable evidence, not as a prose
  explanation to copy.
- Preserve every source line in consolidated_items using one-based source line
  references. Do not merge different normalized products.
- Use Decimal-safe values and stable issue codes such as
  LINE_TOTAL_MISMATCH, SUBTOTAL_MISMATCH, TOTAL_MISMATCH,
  CONFLICTING_DUPLICATE_PRICE, or CONSOLIDATION_MISMATCH as appropriate.
- A mathematically valid invoice remains PASS even if a later database or
  business stage could deny it.
- The stage must be exactly "reconciliation".
"""


def validate_reconciliation(
    ingestion: IngestionResult,
    *,
    revision_feedback: str | None = None,
    previous_result: ReconciliationResult | None = None,
) -> ReconciliationResult:
    """Run the Phase 2 specialist against one immutable ingestion snapshot."""

    if ingestion.normalization is None:
        raise ValueError("Reconciliation requires an ingestion normalization")
    content = json.dumps(
        {
            "original_ingestion": ingestion.model_dump(mode="json"),
            "arithmetic_tool_output": json.loads(json.dumps(build_arithmetic_evidence(ingestion.normalization.invoice), default=str)),
            "previous_reconciliation_result": previous_result.model_dump(mode="json")
            if previous_result is not None
            else None,
            "critic_revision_feedback": revision_feedback,
            "reconciliation_result_schema": ReconciliationResult.model_json_schema(),
        },
        ensure_ascii=False,
    )
    result = invoke_structured(
        system_prompt=_reconciliation_prompt(),
        content=content,
        output_model=ReconciliationResult,
    )
    if result.stage != ValidationStage.RECONCILIATION:
        raise ValueError(f"Reconciliation agent returned unexpected stage: {result.stage}")
    return result
