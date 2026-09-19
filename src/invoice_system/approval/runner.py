"""Official execution boundary for final approval."""

from pathlib import Path
from typing import Any

from ..ingestion.run_logging import RunContext, make_run_id
from .graph import build_graph
from .models import ApprovalRequest, ApprovalResult
from .run_logging import ApprovalRunLogger


def run_approval(
    request: ApprovalRequest,
    *,
    logs_root: Path | None = None,
    artifact_context: RunContext | None = None,
    persist_artifacts: bool = True,
) -> ApprovalResult:
    """Run approval for an invoice that has already passed upstream gates."""
    if not isinstance(request, ApprovalRequest):
        request = ApprovalRequest.model_validate(request)
    _require_upstream_pass(request)
    logger = None
    if persist_artifacts:
        root = logs_root or Path("logs")
        run_id = make_run_id(request.invoice_id, "approval")
        context = artifact_context or RunContext(run_id, root / "approval" / run_id)
        logger = ApprovalRunLogger(context)
        logger.save_context(request)
        logger.event("approval", "started", invoice_id=request.invoice_id)
    state = {"request": request, "business_rule_decision": None, "vp_decision": None, "result": None}
    final = None
    for update in build_graph().stream(state, stream_mode="updates"):
        if logger is not None and "business_rule_agent" in update:
            decision = update["business_rule_agent"]["business_rule_decision"]
            logger.event("business_rule_agent", "decision", decision=decision.decision, triggered_rules=decision.triggered_rules, reasoning=decision.reasoning, concerns=decision.concerns)
        if logger is not None and "vp_agent" in update:
            decision = update["vp_agent"]["vp_decision"]
            logger.event("vp_agent", "decision", decision=decision.decision, reasoning=decision.reasoning, addressed_concerns=decision.addressed_concerns)
        if "approval_complete" in update:
            final = update["approval_complete"]["result"]
    if final is None:
        raise RuntimeError("Approval graph ended without a result")
    if logger is not None:
        logger.event("approval", "completed", final_status=final.final_status, decision_source=final.decision_source)
        logger.save_result(final)
    return final


def _require_upstream_pass(request: ApprovalRequest) -> None:
    """Keep validation failures outside the approval graph."""
    validation_status = _status_value(request.validation_result)
    reconciliation_status = _status_value(request.reconciliation_result)
    if validation_status != "VALID":
        raise ValueError(
            f"approval requires validation status VALID, got {validation_status!r}"
        )
    if reconciliation_status != "PASS":
        raise ValueError(
            f"approval requires reconciliation status PASS, got {reconciliation_status!r}"
        )


def _status_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "status"):
        value = value.status
    if isinstance(value, dict):
        value = value.get("status")
    if hasattr(value, "value"):
        value = value.value
    return str(value).upper() if value is not None else None
