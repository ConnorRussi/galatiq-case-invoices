"""Reusable validation critic for specialist stage results."""

import json

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult

from .models import CriticResult, SemanticResult, ValidationStage


def _critic_prompt() -> str:
    return """You are the shared validation critic. Review the specialist's work
for the named validation stage; do not replace the specialist or independently
return PASS or DENY on its behalf.

Check whether the specialist performed its assigned job correctly and whether
its proposed conclusion is supported by the original ingestion output. For the
semantic stage, check for obvious omissions such as a relative date (for example
"yesterday"), a negative or non-numeric quantity, contradictory dates,
unsupported invented facts, silently altered source data, and an incorrect PASS
or DENY conclusion.
Also reject findings outside semantic responsibility, such as inventory lookup,
SQL/database checks, full arithmetic reconciliation, or business approval policy.

The original ingestion output is immutable source state. A revision may correct
the specialist's reasoning, but neither the specialist nor critic may rewrite
source facts. Collect concise findings and, when the specialist is wrong or
incomplete, return REVISE with exact re-check instructions. Return AGREE only
when the specialist's stage work and conclusion are supported. Never directly
return a stage PASS/DENY decision.
"""


def review_stage(
    original_ingestion: IngestionResult,
    current_stage: ValidationStage | str,
    stage_result: SemanticResult,
    *,
    previous_critic: CriticResult | None = None,
    revision_count: int = 0,
    revision_feedback: str | None = None,
) -> CriticResult:
    """Review a specialist result using the shared critic contract.

    The signature is intentionally stage-oriented so later reconciliation and
    database agents can reuse this function without creating new critics.
    """

    stage = ValidationStage(current_stage)
    if stage != ValidationStage.SEMANTIC:
        raise ValueError(f"Unsupported validation stage in Phase 1: {stage}")
    content = json.dumps(
        {
            "original_ingestion": original_ingestion.model_dump(mode="json"),
            "current_stage": stage.value,
            "specialist_stage_result": stage_result.model_dump(mode="json"),
            "previous_critic_result": previous_critic.model_dump(mode="json")
            if previous_critic is not None
            else None,
            "revision_count": revision_count,
            "revision_feedback": revision_feedback,
            "critic_result_schema": CriticResult.model_json_schema(),
        },
        ensure_ascii=False,
    )
    return invoke_structured(
        system_prompt=_critic_prompt(),
        content=content,
        output_model=CriticResult,
    )
