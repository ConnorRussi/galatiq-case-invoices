from decimal import Decimal

from invoice_system.ingestion.models import (
    IngestionResult,
    IngestionStatus,
    NormalizationResult,
    SourceChunk,
    SourceDocument,
)
from invoice_system.invoice_ledger import InvoiceLedger
from invoice_system.approval.models import ApprovalRequest, BusinessRuleDecision, VPDecision
from invoice_system.payment.models import PaymentResult, PaymentStatus
from invoice_system.validation.models import (
    DatabaseStatus,
    DatabaseValidationResult,
    ReconciliationResult,
    ReconciliationStatus,
    SemanticResult,
    SemanticStatus,
    ValidationResult,
    ValidationStatus,
)


def _ingestion(text: str, *, revision: str | None = None, amount: str = "1890.00") -> IngestionResult:
    additional = {"revision": revision} if revision else {}
    return IngestionResult(
        status=IngestionStatus.ACCEPT,
        source_path=f"{revision or 'original'}.txt",
        source_document=SourceDocument(
            filename=f"{revision or 'original'}.txt",
            file_type="txt",
            chunks=(SourceChunk(id="text_1", text=text, kind="text", extraction_method="text"),),
        ),
        normalization=NormalizationResult(
            invoice={
                "invoice_number": "INV-1004",
                "vendor": "Precision Parts Ltd.",
                "currency": "USD",
                "invoice_total": amount,
                "additional_fields": additional,
            },
            evidence=[],
        ),
    )


def test_paid_invoice_is_suppressed_and_revision_exposes_adjustment(tmp_path):
    original = _ingestion("INV-1004 original")
    revised = _ingestion("INV-1004 revision R1 with GadgetX", revision="R1", amount="5940.00")

    with InvoiceLedger(tmp_path / "ledger.sqlite") as ledger:
        first = ledger.register(original)
        assert first.disposition == "NEW"
        assert ledger.claim_payment(first)
        ledger.complete(
            first,
            workflow_status="APPROVED_AND_PAID",
            payment_status="SUCCESS",
            transaction_id="mock-original",
        )

        duplicate = ledger.register(original)
        assert duplicate.disposition == "DUPLICATE_SUPPRESSED"
        assert duplicate.prior_payment_transaction_id == "mock-original"

        revision = ledger.register(revised)
        assert revision.disposition == "REVISION_AFTER_PAYMENT"
        assert revision.requires_human_review
        assert revision.prior_amount == Decimal("1890.00")
        assert revision.current_amount == Decimal("5940.00")
        assert revision.adjustment_amount == Decimal("4050.00")
        assert revision.prior_payment_transaction_id == "mock-original"

        ledger.complete(revision, workflow_status="HUMAN_REVIEW_REQUIRED")
        pending = ledger.register(revised)
        assert pending.disposition == "HUMAN_REVIEW_PENDING"
        assert pending.requires_human_review


def test_paid_revision_forces_human_review_in_approval(monkeypatch, tmp_path):
    from invoice_system.approval import agents

    original = _ingestion("INV-1004 original")
    revised = _ingestion("INV-1004 revision R1", revision="R1", amount="5940.00")
    with InvoiceLedger(tmp_path / "ledger.sqlite") as ledger:
        first = ledger.register(original)
        ledger.claim_payment(first)
        ledger.complete(first, workflow_status="APPROVED_AND_PAID", payment_status="SUCCESS", transaction_id="mock-original")
        history = ledger.register(revised)

    request = ApprovalRequest(
        invoice_id="INV-1004",
        normalization=revised.normalization,
        validation_result={"status": "VALID"},
        reconciliation_result={"status": "PASS"},
        invoice_history=history,
    )

    def fake_invoke(**kwargs):
        if kwargs["output_model"] is BusinessRuleDecision:
            return BusinessRuleDecision(decision="ACCEPT", reasoning="Model incorrectly accepted.")
        return VPDecision(decision="GO", reasoning="Model incorrectly authorized.")

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    from invoice_system.approval.runner import run_approval

    result = run_approval(request, persist_artifacts=False)
    assert result.final_status == "HUMAN_REVIEW_REQUIRED"
    assert result.vp_decision is not None
    assert result.vp_decision.decision == "HUMAN_REVIEW_REQUIRED"


def _valid(ingestion: IngestionResult) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.VALID,
        reason="validation_passed",
        semantic_result=SemanticResult(status=SemanticStatus.PASS, summary="Pass."),
        reconciliation_result=ReconciliationResult(status=ReconciliationStatus.PASS, summary="Pass."),
        database_result=DatabaseValidationResult(status=DatabaseStatus.PASS, summary="Pass."),
        ingestion=ingestion,
    )


def test_workflow_pays_original_once_and_routes_paid_revision_to_review(monkeypatch, tmp_path):
    from invoice_system import workflow
    from invoice_system.approval.models import ApprovalResult
    from invoice_system.ingestion.run_logging import RunContext

    original = _ingestion("INV-1004 original")
    revised = _ingestion("INV-1004 revision R1", revision="R1", amount="5940.00")
    inputs = iter([original, revised])
    payments = []

    monkeypatch.setattr(workflow, "run_ingestion", lambda *args, **kwargs: next(inputs))
    monkeypatch.setattr(workflow, "run_validation", lambda ingestion, **kwargs: _valid(ingestion))

    def fake_approval(request, **kwargs):
        if request.invoice_history is not None and request.invoice_history.requires_human_review:
            decision = BusinessRuleDecision(decision="VP_REVIEW", reasoning="History requires review.")
            vp = VPDecision(decision="HUMAN_REVIEW_REQUIRED", reasoning="Review adjustment.")
            return ApprovalResult(
                invoice_id=request.invoice_id,
                final_status="HUMAN_REVIEW_REQUIRED",
                decision_source="VP_AGENT",
                business_rule_decision=decision,
                vp_decision=vp,
                reasoning=vp.reasoning,
            )
        decision = BusinessRuleDecision(decision="ACCEPT", reasoning="Accept.")
        return ApprovalResult(
            invoice_id=request.invoice_id,
            final_status="APPROVED",
            decision_source="BUSINESS_RULE_AGENT",
            business_rule_decision=decision,
            reasoning=decision.reasoning,
        )

    monkeypatch.setattr(workflow, "run_approval", fake_approval)

    def fake_payment(request, **kwargs):
        payments.append(request.amount)
        return PaymentResult(
            status=PaymentStatus.SUCCESS,
            invoice_id=request.invoice_id,
            vendor=request.vendor,
            amount=request.amount,
            currency=request.currency,
            transaction_id="mock-original",
            reason="Paid.",
        )

    monkeypatch.setattr(workflow, "run_payment", fake_payment)
    ledger_path = tmp_path / "ledger.sqlite"

    first = workflow.run_invoice_workflow(
        "invoice_1004.json",
        database_path="inventory.sqlite",
        ledger_path=ledger_path,
        artifact_context=RunContext("original", tmp_path / "original"),
    )
    second = workflow.run_invoice_workflow(
        "invoice_1004_revised.json",
        database_path="inventory.sqlite",
        ledger_path=ledger_path,
        artifact_context=RunContext("revised", tmp_path / "revised"),
    )

    assert first.status.value == "APPROVED_AND_PAID"
    assert second.status.value == "HUMAN_REVIEW_REQUIRED"
    assert second.invoice_history is not None
    assert second.invoice_history.adjustment_amount == Decimal("4050.00")
    assert payments == [Decimal("1890.00")]
