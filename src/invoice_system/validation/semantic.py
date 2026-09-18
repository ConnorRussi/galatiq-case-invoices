"""LLM semantic validation specialist."""

import json

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult

from .models import SemanticResult, ValidationStage


def _semantic_prompt() -> str:
    return """You are the semantic validation agent for an invoice-processing system.

Inspect the complete structured ingestion output as one invoice. Your job is to
decide whether the extracted information makes semantic sense as invoice data,
not merely whether each isolated field has a valid Python type.

Rules for this stage:
- Negative quantities are always invalid in this system. Do not make credit-memo
  or return exceptions.
- Non-numeric normalized quantities (for example, "a bunch") are invalid even
  if ingestion somehow preserved them outside the normal Decimal contract.
- Relative or non-real dates such as "yesterday", "tomorrow", and "next Friday"
  are invalid normalized invoice dates and due dates. Do not convert them into a
  calendar date.
- Catch contradictory dates, including an invoice date after its due date when
  that violates invoice semantics.
- Identify required information that is missing when the invoice cannot be
  meaningfully processed.
- Use the full invoice context to find contradictions and related problems.
- Collect every semantic issue found during the complete pass before proposing
  PASS or DENY. Do not stop at the first issue.
- Do not silently repair, normalize, or rewrite source facts. Distinguish facts
  in the ingestion output from your own reasoning.
- Only validate semantic concerns assigned to this stage. Do not query
  inventory or SQL, consolidate duplicate products, perform full arithmetic
  reconciliation, apply purchase approval policies, or decide human approval.

Return DENY when one or more material semantic issues make the invoice invalid;
otherwise return PASS. Explain concise findings with field paths and supporting
evidence where available. The stage must be exactly "semantic".
"""


def validate_semantics(
    ingestion: IngestionResult,
    *,
    revision_feedback: str | None = None,
    previous_result: SemanticResult | None = None,
) -> SemanticResult:
    """Run the semantic specialist against an immutable ingestion snapshot."""

    content = json.dumps(
        {
            "original_ingestion": ingestion.model_dump(mode="json"),
            "previous_semantic_result": previous_result.model_dump(mode="json")
            if previous_result is not None
            else None,
            "critic_revision_feedback": revision_feedback,
            "semantic_result_schema": SemanticResult.model_json_schema(),
        },
        ensure_ascii=False,
    )
    result = invoke_structured(
        system_prompt=_semantic_prompt(),
        content=content,
        output_model=SemanticResult,
    )
    if result.stage != ValidationStage.SEMANTIC:
        raise ValueError(f"Semantic agent returned unexpected stage: {result.stage}")
    return result


semantic_validate = validate_semantics
