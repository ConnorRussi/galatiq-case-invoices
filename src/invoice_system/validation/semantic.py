"""LLM semantic validation specialist."""

import json

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult

from .models import SemanticResult, ValidationStage
from .policy import semantic_scope_prompt


def _semantic_prompt() -> str:
    return f"""You are the Phase 1 semantic validation agent for an invoice-processing system.

Inspect the complete structured ingestion output as one invoice. Your job is to
decide whether the extracted information makes semantic sense as invoice data,
not merely whether each isolated field has a valid Python type.

{semantic_scope_prompt()}

Execution rules:
- Use the full invoice context to find contradictions and related problems.
- Collect every independent root semantic issue before proposing PASS or DENY.
- Do not silently repair, normalize, or rewrite source facts. Distinguish facts
  in the ingestion output from your own reasoning.
- Treat observations belonging to later stages as non-blocking and do not turn
  them into Semantic issues.

Return DENY when one or more material semantic issues make the invoice invalid;
otherwise return PASS. Explain concise findings with canonical field paths and
supporting evidence where available. The stage must be exactly "semantic".
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
