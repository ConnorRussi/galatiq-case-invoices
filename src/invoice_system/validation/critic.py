"""Reusable validation critic for specialist stage results."""

import json

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult

from .arithmetic import build_arithmetic_evidence
from .models import CriticResult, ReconciliationResult, SemanticResult, ValidationStage
from .policy import semantic_scope_prompt
from .reconciliation import reconciliation_scope_prompt


def _critic_prompt() -> str:
    return f"""You are the shared, scope-aware validation critic. Review the
specialist's work for the named validation stage; do not replace the specialist
or independently return PASS or DENY on its behalf.

{semantic_scope_prompt()}

{reconciliation_scope_prompt()}

For a Semantic result, independently review all five dimensions:
1. Evidence support: is every claimed issue supported by the immutable original
   ingestion output? Reject hallucinated, altered, or unsupported facts.
2. Stage ownership: is every issue within the Semantic scope above? A factually
   correct arithmetic mismatch, database finding, business rule, or payment-term
   calculation is still invalid at this stage.
3. Invented requirements: did the specialist deny because a field is missing
   even though the Phase 1 contract does not require it? In particular, missing
   invoice_total or amount_due is not a Semantic denial under this contract.
4. Root-cause quality: did the specialist report one underlying issue rather
   than duplicate raw-format and missing-field symptoms?
5. Conclusion: after removing unsupported, out-of-scope, and duplicate issues,
   do the remaining Semantic issues justify PASS or DENY?

The current critic contract uses AGREE or REVISE. REVISE is the structured
equivalent of disagreement: clearly identify each unsupported, out-of-scope,
invented-requirement, or duplicate finding and give exact re-check instructions.
If a specialist DENY contains only reconciliation or payment-term findings,
return REVISE and instruct it to return PASS after removing them. If a specialist
passes an invoice with a real Semantic blocker, return REVISE. Return AGREE only
when the stage work, root issues, and conclusion are all supported and in scope.

For a Reconciliation result, independently verify every line calculation,
subtotal/total relationship, repeated-product consolidation, source-line
coverage, and stage boundary using the original ingestion output and the
deterministic arithmetic evidence. A false PASS or unsupported arithmetic DENY
requires REVISE. Do not turn inventory or business-policy observations into a
reconciliation blocker.

The original ingestion output is immutable source state. Neither specialist nor
critic may rewrite it. Never directly return a stage PASS/DENY decision.
"""


def review_stage(
    original_ingestion: IngestionResult,
    current_stage: ValidationStage | str,
    stage_result: SemanticResult | ReconciliationResult,
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
    if stage == ValidationStage.SEMANTIC and not isinstance(stage_result, SemanticResult):
        raise ValueError("Semantic critic requires a SemanticResult")
    if stage == ValidationStage.RECONCILIATION and not isinstance(stage_result, ReconciliationResult):
        raise ValueError("Reconciliation critic requires a ReconciliationResult")
    if stage_result.stage != stage:
        raise ValueError(f"Specialist result stage {stage_result.stage} does not match {stage}")
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
            "arithmetic_tool_output": json.loads(json.dumps(build_arithmetic_evidence(original_ingestion.normalization.invoice), default=str))
            if stage == ValidationStage.RECONCILIATION and original_ingestion.normalization is not None
            else None,
            "critic_result_schema": CriticResult.model_json_schema(),
        },
        ensure_ascii=False,
    )
    return invoke_structured(
        system_prompt=_critic_prompt(),
        content=content,
        output_model=CriticResult,
    )
