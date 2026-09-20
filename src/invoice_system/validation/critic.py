"""Reusable validation critic for specialist stage results."""

import json
from collections import Counter
from decimal import Decimal

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult

from .arithmetic import build_arithmetic_evidence
from .models import (
    CriticResult,
    CriticDecision,
    ValidationIssue,
    DatabaseValidationResult,
    ReconciliationResult,
    SemanticResult,
    ValidationStage,
)
from .policy import semantic_scope_prompt
from .reconciliation import reconciliation_scope_prompt


def _semantic_critic_prompt() -> str:
    return f"""You are the Phase 1 Semantic validation critic. Review only the
Semantic specialist's work; do not replace the specialist or independently
return PASS or DENY on its behalf.

{semantic_scope_prompt()}

Independently review all five dimensions:
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

The original ingestion output is immutable source state. Neither specialist nor
critic may rewrite it. Never directly return a stage PASS/DENY decision.
"""


def _reconciliation_critic_prompt() -> str:
    return f"""You are the Phase 2 Reconciliation validation critic. Review only
the Reconciliation specialist's work; do not replace the specialist or
independently return PASS or DENY on its behalf.

{reconciliation_scope_prompt()}

Independently verify every line calculation, subtotal/total relationship,
repeated-product consolidation, source-line coverage, and stage boundary using
the original ingestion output and deterministic arithmetic evidence. Different
unit prices for repeated normalized products are allowed, so they never justify
a Reconciliation issue or denial by themselves. A false PASS or unsupported
arithmetic DENY requires REVISE. Do not turn Semantic, inventory, database, or
business-policy observations into a Reconciliation blocker.

The original ingestion output is immutable source state. Neither specialist nor
critic may rewrite it. Never directly return a stage PASS/DENY decision.
"""


def _database_critic_prompt() -> str:
    return """You are the inventory database validation critic. Review only the
Database specialist's work; do not replace the specialist or independently
return PASS or DENY on its behalf.

The inventory database stores product identifiers without spaces. Components
are joined together and each component begins with a capital letter, forming a
PascalCase-style identifier. This is context for deliberate lookup decisions,
not a deterministic rewrite rule.

Review every consolidated inventory result and its attempted_names history.
Use the supplied reconciliation identity mappings and source_lines as the
authoritative mapping from invoice lines to inventory products. A fulfillment
qualifier such as `(rush order)` may intentionally share an inventory product
with an unqualified line; it does not require a separate SKU lookup when its
source line is covered by that consolidated result. For example, source_lines
[1, 4] represents two individually traceable lines counted once each; it does
not obscure coverage. attempted_names records actual SQL requests, not every
source description. Review identity interpretation against source evidence;
coverage alone does not establish equivalence. Check that every named
source line is covered exactly once across the database results. If the first
spaced, punctuated, or otherwise presentation-level form was not found, check
whether the specialist should have tried a reasonable meaning-preserving
variation before returning PRODUCT_NOT_FOUND. The specialist should use bulk
lookup rounds, retry only unresolved products, and stop at the configured
round limit.

Also challenge unsupported matching. A matched value must preserve apparent
product identity; a materially different known product is not a valid fallback
just because the original lookup failed. Verify requested quantity against the
matched available stock and ensure the authoritative matched database value is
reported. Do not perform the lookup yourself.

Return REVISE for an early give-up, unsupported substitution, missing attempt
history, incorrect stock conclusion, or other material database error. Return
AGREE only when the result is supported and complete. Never directly return a
stage PASS/DENY decision.
"""


def _database_audit(ingestion: IngestionResult, result: DatabaseValidationResult) -> list[ValidationIssue]:
    """Check numeric/coverage claims independently, without interpreting identity."""
    invoice = ingestion.normalization.invoice
    expected = {i for i, item in enumerate(invoice.items, 1) if item.item_name}
    covered = [line for item in result.results for line in item.source_lines]
    findings = []

    def report(code: str, message: str) -> None:
        findings.append(ValidationIssue(code=code, message=message, field="results"))

    if Counter(covered) != Counter(expected):
        report("DATABASE_LINE_COVERAGE", "Each named source line must appear exactly once, with no extra references.")
    matched = {}
    for item in result.results:
        if not item.source_lines or any(line not in expected for line in item.source_lines):
            continue
        quantities = [invoice.items[line - 1].quantity for line in item.source_lines]
        quantity = sum(quantities, Decimal("0")) if all(q is not None for q in quantities) else None
        if quantity != item.requested_quantity:
            report("DATABASE_QUANTITY_MISMATCH", f"{item.requested_name}: requested quantity differs from original source lines.")
        sufficient = (
            quantity <= item.available_stock
            if quantity is not None and item.available_stock is not None and item.product_found
            else None
        )
        if sufficient != item.inventory_sufficient:
            report("DATABASE_STOCK_MISMATCH", f"{item.requested_name}: stock conclusion differs from source quantity and available stock.")
        if result.status.value == "PASS" and (not item.matched_item or not item.product_found or sufficient is not True):
            report("DATABASE_UNSUPPORTED_PASS", f"{item.requested_name}: PASS requires a resolved identity and sufficient stock.")
        if item.product_found and item.matched_item:
            matched.setdefault(item.matched_item, []).append(item)
    for name, items in matched.items():
        if len(items) > 1:
            report("DATABASE_SPLIT_IDENTITY", f"{name}: aggregate all resolved source lines before checking stock.")
    return findings


def _critic_prompt(current_stage: ValidationStage | str = ValidationStage.SEMANTIC) -> str:
    """Return only the contract applicable to the stage under review."""

    stage = ValidationStage(current_stage)
    if stage == ValidationStage.SEMANTIC:
        return _semantic_critic_prompt()
    if stage == ValidationStage.RECONCILIATION:
        return _reconciliation_critic_prompt()
    return _database_critic_prompt()


def review_stage(
    original_ingestion: IngestionResult,
    current_stage: ValidationStage | str,
    stage_result: SemanticResult | ReconciliationResult | DatabaseValidationResult,
    *,
    previous_critic: CriticResult | None = None,
    revision_count: int = 0,
    revision_feedback: str | None = None,
    reconciliation_result: ReconciliationResult | None = None,
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
    if stage == ValidationStage.DATABASE and not isinstance(stage_result, DatabaseValidationResult):
        raise ValueError("Database critic requires a DatabaseValidationResult")
    if stage_result.stage != stage:
        raise ValueError(f"Specialist result stage {stage_result.stage} does not match {stage}")
    audit = _database_audit(original_ingestion, stage_result) if stage == ValidationStage.DATABASE else []
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
            "deterministic_database_findings": [finding.model_dump(mode="json") for finding in audit],
            "reconciliation_result": reconciliation_result.model_dump(mode="json")
            if stage == ValidationStage.DATABASE and reconciliation_result is not None
            else None,
            "arithmetic_tool_output": json.loads(json.dumps(build_arithmetic_evidence(original_ingestion.normalization.invoice), default=str))
            if stage == ValidationStage.RECONCILIATION and original_ingestion.normalization is not None
            else None,
            "critic_result_schema": CriticResult.model_json_schema(),
        },
        ensure_ascii=False,
    )
    result = invoke_structured(
        system_prompt=_critic_prompt(stage) + """
An AGREE response must not request revisions. For a specialist PASS, any
remaining error finding requires REVISE. For a supported specialist DENY,
findings may explain the denial. Deterministic database findings identify
report inconsistencies that must be corrected; an empty list does not prove
product identity equivalence.
""",
        content=content,
        output_model=CriticResult,
    )
    contradictory = result.decision == CriticDecision.AGREE and (
        bool(result.revision_instructions and result.revision_instructions.strip())
        or (stage_result.status.value == "PASS" and any(f.severity.value == "error" for f in result.findings))
    )
    if audit or contradictory:
        findings = [*result.findings, *audit]
        if contradictory:
            findings.append(ValidationIssue(
                code="CRITIC_CONTRADICTION",
                message="AGREE conflicts with outstanding errors or revision instructions.",
            ))
        return result.model_copy(update={
            "decision": CriticDecision.REVISE,
            "findings": findings,
            "revision_instructions": "\n".join(filter(None, [
                result.revision_instructions, *(f.message for f in findings),
            ])),
            "summary": "Revision required: " + "; ".join(f.message for f in findings),
        })
    return result
