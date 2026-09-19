import json

from invoice_system.approval.models import ApprovalResult, BusinessRuleDecision, VPDecision
from invoice_system.ingestion.models import IngestionResult, IngestionStatus, NormalizationResult
from invoice_system.ingestion.run_logging import RunContext
from invoice_system.payment.models import PaymentResult, PaymentStatus
from invoice_system.validation.models import (
    DatabaseStatus,
    DatabaseValidationResult,
    ReconciliationResult,
    ReconciliationStatus,
    SemanticResult,
    SemanticStatus,
    ValidationIssue,
    ValidationResult,
    ValidationStage,
    ValidationStatus,
)
from invoice_system import workflow
from invoice_system.workflow import WorkflowStatus


def _ingestion(*, amount_due="500", invoice_total="600") -> IngestionResult:
    return IngestionResult(
        status=IngestionStatus.ACCEPT,
        source_path="invoice.txt",
        normalization=NormalizationResult(
            invoice={
                "invoice_number": "INV-1",
                "vendor": "Acme Supplies",
                "currency": "USD",
                "amount_due": amount_due,
                "invoice_total": invoice_total,
                "items": [],
            },
            evidence=[],
        ),
    )


def _validation(ingestion: IngestionResult, *, denied: bool = False) -> ValidationResult:
    issue = ValidationIssue(
        code="OUT_OF_STOCK",
        message="Requested quantity exceeds available stock.",
        field="items[0].quantity",
    )
    return ValidationResult(
        status=ValidationStatus.DENIED if denied else ValidationStatus.VALID,
        reason="inventory_denied" if denied else "validation_passed",
        denied_by=ValidationStage.DATABASE if denied else None,
        issues=[issue] if denied else [],
        semantic_result=SemanticResult(
            status=SemanticStatus.PASS,
            summary="Semantic checks passed.",
        ),
        reconciliation_result=ReconciliationResult(
            status=ReconciliationStatus.PASS,
            summary="Reconciliation passed.",
        ),
        database_result=DatabaseValidationResult(
            status=DatabaseStatus.DENY if denied else DatabaseStatus.PASS,
            summary="Inventory denied." if denied else "Inventory passed.",
            issues=[issue] if denied else [],
        ),
        ingestion=ingestion,
    )


def _approval(*, approved: bool = True, vp: bool = False) -> ApprovalResult:
    business = BusinessRuleDecision(
        decision="VP_REVIEW" if vp else ("ACCEPT" if approved else "REJECT"),
        reasoning="Escalate." if vp else ("Policy accepted." if approved else "Policy rejected."),
    )
    vp_decision = None
    if vp:
        vp_decision = VPDecision(
            decision="GO" if approved else "NO_GO",
            reasoning="VP approved." if approved else "VP rejected.",
        )
    return ApprovalResult(
        invoice_id="INV-1",
        final_status="APPROVED" if approved else "REJECTED",
        decision_source="VP_AGENT" if vp else "BUSINESS_RULE_AGENT",
        business_rule_decision=business,
        vp_decision=vp_decision,
        reasoning=(vp_decision.reasoning if vp_decision else business.reasoning),
    )


def _install_upstream(monkeypatch, ingestion, validation):
    monkeypatch.setattr(workflow, "run_ingestion", lambda *args, **kwargs: ingestion)
    monkeypatch.setattr(workflow, "run_validation", lambda *args, **kwargs: validation)


def test_ingestion_technical_failure_stops_all_downstream_work(monkeypatch):
    ingestion = IngestionResult(
        status=IngestionStatus.TECHNICAL_FAILURE,
        source_path="broken.pdf",
        error_message="OCR is required.",
    )
    monkeypatch.setattr(workflow, "run_ingestion", lambda *args, **kwargs: ingestion)
    monkeypatch.setattr(workflow, "run_validation", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("validation ran")))
    monkeypatch.setattr(workflow, "run_approval", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("approval ran")))
    monkeypatch.setattr(workflow, "run_payment", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("payment ran")))

    result = workflow.run_invoice_workflow(
        "broken.pdf",
        database_path="inventory.sqlite",
        persist_artifacts=False,
    )

    assert result.status == WorkflowStatus.TECHNICAL_FAILURE
    assert result.stopped_at == "ingestion"
    assert result.reason == "OCR is required."


def test_validation_denial_stops_before_approval_and_payment(monkeypatch):
    ingestion = _ingestion()
    validation = _validation(ingestion, denied=True)
    _install_upstream(monkeypatch, ingestion, validation)
    monkeypatch.setattr(workflow, "run_approval", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("approval ran")))
    monkeypatch.setattr(workflow, "run_payment", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("payment ran")))
    messages = []

    result = workflow.run_invoice_workflow(
        "invoice.txt",
        database_path="inventory.sqlite",
        persist_artifacts=False,
        progress_callback=messages.append,
    )

    assert result.status == WorkflowStatus.VALIDATION_DENIED
    assert result.stopped_at == "validation"
    assert "Requested quantity exceeds available stock" in result.reason
    assert any("denied during database" in message for message in messages)


def test_direct_approval_pays_amount_due_before_invoice_total(monkeypatch):
    ingestion = _ingestion(amount_due="500", invoice_total="600")
    validation = _validation(ingestion)
    _install_upstream(monkeypatch, ingestion, validation)
    monkeypatch.setattr(workflow, "run_approval", lambda *args, **kwargs: _approval())
    captured = {}

    def fake_payment(request, **kwargs):
        captured["request"] = request
        return PaymentResult(
            status=PaymentStatus.SUCCESS,
            invoice_id=request.invoice_id,
            vendor=request.vendor,
            amount=request.amount,
            currency=request.currency,
            transaction_id="mock-1",
            reason="Mock payment completed successfully.",
        )

    monkeypatch.setattr(workflow, "run_payment", fake_payment)

    result = workflow.run_invoice_workflow(
        "invoice.txt",
        database_path="inventory.sqlite",
        persist_artifacts=False,
    )

    assert result.status == WorkflowStatus.APPROVED_AND_PAID
    assert captured["request"].amount == 500
    assert not result.vp_review_required


def test_vp_rejection_never_runs_payment(monkeypatch):
    ingestion = _ingestion()
    validation = _validation(ingestion)
    _install_upstream(monkeypatch, ingestion, validation)
    monkeypatch.setattr(workflow, "run_approval", lambda *args, **kwargs: _approval(approved=False, vp=True))
    monkeypatch.setattr(workflow, "run_payment", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("payment ran")))

    result = workflow.run_invoice_workflow(
        "invoice.txt",
        database_path="inventory.sqlite",
        persist_artifacts=False,
    )

    assert result.status == WorkflowStatus.APPROVAL_REJECTED
    assert result.stopped_at == "approval"
    assert result.vp_review_required
    assert result.reason == "VP rejected."


def test_payment_failure_has_distinct_terminal_status(monkeypatch):
    ingestion = _ingestion()
    validation = _validation(ingestion)
    _install_upstream(monkeypatch, ingestion, validation)
    monkeypatch.setattr(workflow, "run_approval", lambda *args, **kwargs: _approval(approved=True, vp=True))
    monkeypatch.setattr(
        workflow,
        "run_payment",
        lambda request, **kwargs: PaymentResult(
            status=PaymentStatus.FAILED,
            invoice_id=request.invoice_id,
            vendor=request.vendor,
            amount=request.amount,
            reason="provider unavailable",
        ),
    )

    result = workflow.run_invoice_workflow(
        "invoice.txt",
        database_path="inventory.sqlite",
        persist_artifacts=False,
    )

    assert result.status == WorkflowStatus.PAYMENT_FAILED
    assert result.stopped_at == "payment"
    assert result.reason == "provider unavailable"
    assert result.vp_review_required


def test_terminal_workflow_artifact_is_evaluation_ready(tmp_path, monkeypatch):
    ingestion = _ingestion()
    validation = _validation(ingestion, denied=True)
    _install_upstream(monkeypatch, ingestion, validation)
    context = RunContext("workflow-test", tmp_path / "run")

    result = workflow.run_invoice_workflow(
        "invoice.txt",
        database_path="inventory.sqlite",
        artifact_context=context,
    )

    payload = json.loads((context.run_dir / "workflow_result.json").read_text())
    assert payload["status"] == result.status.value
    assert payload["stopped_at"] == "validation"
    assert payload["validation"]["denied_by"] == "database"
    final_event = json.loads((context.run_dir / "events.jsonl").read_text().splitlines()[-1])
    assert final_event["stage"] == "workflow"
    assert final_event["status"] == "VALIDATION_DENIED"
