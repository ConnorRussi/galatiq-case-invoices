import json
from pathlib import Path

from invoice_system.approval.models import ApprovalResult, BusinessRuleDecision, VPDecision
from invoice_system.ingestion.models import IngestionResult, IngestionStatus, NormalizationResult
from invoice_system.validation.models import ValidationResult, ValidationStatus
from invoice_system.workflow import WorkflowResult, WorkflowStatus
from invoice_system.workflow_evaluation import _score_result


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_manifest_covers_every_invoice_file():
    manifest = json.loads((ROOT / "evals" / "workflow" / "cases.json").read_text(encoding="utf-8"))
    expected_sources = {case["invoice_path"] for case in manifest["cases"]}
    actual_sources = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "data" / "invoices").iterdir()
        if path.is_file()
    }

    assert expected_sources == actual_sources


def test_workflow_evaluation_scores_vp_invocation_from_audit_event():
    ingestion = IngestionResult(
        status=IngestionStatus.ACCEPT,
        source_path="invoice.txt",
        normalization=NormalizationResult(invoice={"invoice_number": "INV-1", "items": []}, evidence=[]),
    )
    result = WorkflowResult(
        status=WorkflowStatus.APPROVAL_REJECTED,
        source_path="invoice.txt",
        invoice_id="INV-1",
        stopped_at="approval",
        reason="VP rejected.",
        vp_review_required=True,
        ingestion=ingestion,
        validation=ValidationResult(
            status=ValidationStatus.VALID,
            reason="validation_passed",
            ingestion=ingestion,
            semantic_result=None,
        ),
        approval=ApprovalResult(
            invoice_id="INV-1",
            final_status="REJECTED",
            decision_source="VP_AGENT",
            business_rule_decision=BusinessRuleDecision(
                decision="VP_REVIEW",
                reasoning="Escalate.",
            ),
            vp_decision=VPDecision(decision="NO_GO", reasoning="Reject."),
            reasoning="Reject.",
        ),
    )

    sections = _score_result(
        result,
        [{"stage": "vp_agent", "event": "invoked"}],
        {
            "workflow_status": "APPROVAL_REJECTED",
            "stopped_at": "approval",
            "validation_status": "VALID",
            "validation_denial_stage": None,
            "approval_status": "REJECTED",
            "approval_decision_source": "VP_AGENT",
            "payment_status": None,
            "vp_invoked": True,
            "vp_decision": "NO_GO",
        },
    )

    assert all(section.passed for section in sections)
