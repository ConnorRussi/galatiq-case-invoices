import json
import re
import sqlite3
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


def test_synthetic_vp_cases_cover_threshold_and_payment_invariants():
    manifest = json.loads((ROOT / "evals" / "workflow" / "cases.json").read_text(encoding="utf-8"))
    cases = {
        case["case_id"]: case
        for case in manifest["cases"]
        if case["case_id"].startswith("synthetic_vp_")
    }

    assert set(cases) == {
        "synthetic_vp_approved_txt",
        "synthetic_vp_boundary_txt",
        "synthetic_vp_just_above_txt",
    }
    assert cases["synthetic_vp_approved_txt"]["expected"]["vp_invoked"] is True
    assert cases["synthetic_vp_boundary_txt"]["expected"]["vp_invoked"] is False
    assert cases["synthetic_vp_just_above_txt"]["expected"]["vp_invoked"] is True
    for case in cases.values():
        expected = case["expected"]
        assert expected["approval_decision_source"] in {"BUSINESS_RULE_AGENT", "VP_AGENT"}
        assert expected["payment_status"] == "SUCCESS"
        assert expected["workflow_status"] == "APPROVED_AND_PAID"


def test_synthetic_vp_fixture_lines_fit_inventory_and_reconcile():
    expected = {
        "synthetic_vp_approved.txt": ("WidgetA", 10, "12000.00"),
        "synthetic_vp_boundary.txt": ("WidgetB", 10, "10000.00"),
        "synthetic_vp_just_above.txt": ("WidgetB", 10, "10000.10"),
    }
    with sqlite3.connect(ROOT / "inventory.sqlite") as connection:
        stock = dict(connection.execute("SELECT item, stock FROM inventory"))

    for filename, (item, quantity, total) in expected.items():
        text = (ROOT / "data" / "invoices" / filename).read_text(encoding="utf-8")
        match = re.search(
            rf"{item}\s+Quantity:\s+(\d+)\s+Unit Price:\s+\$([\d,]+\.\d{{2}})\s+Line Amount:\s+\$([\d,]+\.\d{{2}})",
            text,
        )
        assert match, filename
        actual_quantity = int(match.group(1))
        unit_price = match.group(2).replace(",", "")
        line_amount = match.group(3).replace(",", "")
        assert actual_quantity == quantity <= stock[item]
        assert f"{float(unit_price) * actual_quantity:.2f}" == line_amount == total
        assert f"Total Amount: ${float(total):,.2f}" in text
        assert f"Amount Due: ${float(total):,.2f}" in text


def test_vp_rejection_candidate_is_quarantined_until_policy_is_clarified():
    candidate = ROOT / "evals" / "workflow" / "fixtures" / "vp_rejection_candidate.txt"
    assert candidate.exists()
    assert "NOT IN LIVE WORKFLOW CORPUS" in candidate.read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "evals" / "workflow" / "cases.json").read_text(encoding="utf-8"))
    assert all(case["invoice_path"] != candidate.relative_to(ROOT).as_posix() for case in manifest["cases"])


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
