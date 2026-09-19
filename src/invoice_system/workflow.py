"""End-to-end invoice orchestration for the human-facing CLI."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from .approval.models import ApprovalRequest, ApprovalResult
from .approval.runner import run_approval
from .ingestion.models import IngestionResult, IngestionStatus
from .ingestion.run_logging import (
    RunContext,
    append_event,
    create_normal_run_context,
    write_artifact,
)
from .ingestion.runner import run_ingestion
from .payment.models import PaymentRequest, PaymentResult, PaymentStatus
from .payment.runner import run_payment
from .validation.models import ValidationResult, ValidationStatus
from .validation.runner import run_validation


ProgressCallback = Callable[[str], None]


class WorkflowStatus(str, Enum):
    APPROVED_AND_PAID = "APPROVED_AND_PAID"
    VALIDATION_DENIED = "VALIDATION_DENIED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class WorkflowResult(BaseModel):
    status: WorkflowStatus
    source_path: str
    invoice_id: str | None = None
    stopped_at: Literal["ingestion", "validation", "approval", "payment", "completed"]
    reason: str
    vp_review_required: bool = False
    ingestion: IngestionResult
    validation: ValidationResult | None = None
    approval: ApprovalResult | None = None
    payment: PaymentResult | None = None


def run_invoice_workflow(
    source_path: str | Path,
    *,
    database_path: str | Path | None,
    logs_root: Path | None = None,
    artifact_context: RunContext | None = None,
    persist_artifacts: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> WorkflowResult:
    """Run ingestion, validation, approval, and payment with fail-closed routing."""

    source_path_str = str(source_path)
    context = artifact_context
    if persist_artifacts and context is None:
        context = create_normal_run_context(logs_root or Path("logs"), source_path)

    _progress(progress_callback, f"[1/4] Starting ingestion: {Path(source_path).name}")
    ingestion = run_ingestion(
        source_path,
        artifact_context=context,
        persist_artifacts=persist_artifacts,
    )
    _progress(progress_callback, f"[1/4] Ingestion complete: {ingestion.status.value.upper()}")

    if ingestion.status == IngestionStatus.TECHNICAL_FAILURE:
        result = WorkflowResult(
            status=WorkflowStatus.TECHNICAL_FAILURE,
            source_path=source_path_str,
            stopped_at="ingestion",
            reason=ingestion.error_message or "Ingestion failed.",
            ingestion=ingestion,
        )
        _progress(progress_callback, f"Stopped during ingestion: {result.reason}")
        return _finish(result, context)

    _progress(progress_callback, "[2/4] Starting semantic, reconciliation, and inventory validation")
    try:
        validation = run_validation(
            ingestion,
            artifact_context=context,
            persist_artifacts=persist_artifacts,
            run_reconciliation=True,
            run_database=True,
            database_path=database_path,
        )
    except Exception as exc:
        result = WorkflowResult(
            status=WorkflowStatus.TECHNICAL_FAILURE,
            source_path=source_path_str,
            invoice_id=_invoice_id(ingestion),
            stopped_at="validation",
            reason=str(exc),
            ingestion=ingestion,
        )
        _progress(progress_callback, f"[2/4] Validation failed: {result.reason}")
        return _finish(result, context)

    _progress(progress_callback, f"[2/4] Validation complete: {validation.status.value}")
    if validation.status != ValidationStatus.VALID:
        status = (
            WorkflowStatus.VALIDATION_DENIED
            if validation.status == ValidationStatus.DENIED
            else WorkflowStatus.TECHNICAL_FAILURE
        )
        result = WorkflowResult(
            status=status,
            source_path=source_path_str,
            invoice_id=_invoice_id(ingestion),
            stopped_at="validation",
            reason=_validation_reason(validation),
            ingestion=ingestion,
            validation=validation,
        )
        label = "denied" if status == WorkflowStatus.VALIDATION_DENIED else "failed"
        stage = validation.denied_by.value if validation.denied_by is not None else "validation"
        _progress(progress_callback, f"Invoice {label} during {stage}: {result.reason}")
        return _finish(result, context)

    try:
        approval_request = _build_approval_request(ingestion, validation)
        _progress(progress_callback, "[3/4] Starting approval review")
        approval = run_approval(
            approval_request,
            artifact_context=context,
            persist_artifacts=persist_artifacts,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        result = WorkflowResult(
            status=WorkflowStatus.TECHNICAL_FAILURE,
            source_path=source_path_str,
            invoice_id=_invoice_id(ingestion),
            stopped_at="approval",
            reason=str(exc),
            ingestion=ingestion,
            validation=validation,
        )
        _progress(progress_callback, f"[3/4] Approval failed: {result.reason}")
        return _finish(result, context)

    vp_required = approval.decision_source == "VP_AGENT"
    _progress(progress_callback, f"[3/4] Approval complete: {approval.final_status}")
    if approval.final_status == "REJECTED":
        result = WorkflowResult(
            status=WorkflowStatus.APPROVAL_REJECTED,
            source_path=source_path_str,
            invoice_id=approval.invoice_id,
            stopped_at="approval",
            reason=approval.reasoning,
            vp_review_required=vp_required,
            ingestion=ingestion,
            validation=validation,
            approval=approval,
        )
        _progress(progress_callback, f"Invoice rejected during approval: {result.reason}")
        return _finish(result, context)

    _progress(progress_callback, "[4/4] Starting mock payment")
    try:
        payment_request = _build_payment_request(ingestion, approval.invoice_id)
        payment = run_payment(
            payment_request,
            artifact_context=context,
            persist_artifacts=persist_artifacts,
        )
    except (ValueError, ValidationError) as exc:
        payment = PaymentResult(
            status=PaymentStatus.FAILED,
            invoice_id=approval.invoice_id,
            reason=str(exc),
        )
        if context is not None:
            write_artifact(context.run_dir, "payment_result.json", payment)
            append_event(
                context.run_dir,
                "payment",
                "failed",
                status=payment.status.value,
                reason=payment.reason,
            )

    if payment.status != PaymentStatus.SUCCESS:
        result = WorkflowResult(
            status=WorkflowStatus.PAYMENT_FAILED,
            source_path=source_path_str,
            invoice_id=approval.invoice_id,
            stopped_at="payment",
            reason=payment.reason,
            vp_review_required=vp_required,
            ingestion=ingestion,
            validation=validation,
            approval=approval,
            payment=payment,
        )
        _progress(progress_callback, f"[4/4] Payment failed: {result.reason}")
        return _finish(result, context)

    result = WorkflowResult(
        status=WorkflowStatus.APPROVED_AND_PAID,
        source_path=source_path_str,
        invoice_id=approval.invoice_id,
        stopped_at="completed",
        reason=f"Approved: {approval.reasoning} Payment: {payment.reason}",
        vp_review_required=vp_required,
        ingestion=ingestion,
        validation=validation,
        approval=approval,
        payment=payment,
    )
    _progress(
        progress_callback,
        f"[4/4] Payment successful: {payment.amount} {payment.currency or ''} paid to {payment.vendor}",
    )
    return _finish(result, context)


def _build_approval_request(
    ingestion: IngestionResult,
    validation: ValidationResult,
) -> ApprovalRequest:
    if ingestion.normalization is None:
        raise ValueError("Approval requires a normalized invoice")
    if validation.reconciliation_result is None:
        raise ValueError("Approval requires a completed reconciliation result")
    return ApprovalRequest(
        invoice_id=_invoice_id(ingestion),
        source_document=ingestion.source_document,
        normalization=ingestion.normalization,
        validation_result=validation.model_dump(mode="json"),
        reconciliation_result=validation.reconciliation_result.model_dump(mode="json"),
    )


def _build_payment_request(ingestion: IngestionResult, invoice_id: str) -> PaymentRequest:
    if ingestion.normalization is None:
        raise ValueError("Payment requires a normalized invoice")
    invoice = ingestion.normalization.invoice
    amount = invoice.amount_due if invoice.amount_due is not None else invoice.invoice_total
    if not invoice.vendor:
        raise ValueError("Payment requires a vendor")
    if amount is None:
        raise ValueError("Payment requires amount_due or invoice_total")
    return PaymentRequest(
        invoice_id=invoice_id,
        vendor=invoice.vendor,
        amount=amount,
        currency=invoice.currency,
    )


def _invoice_id(ingestion: IngestionResult) -> str:
    if ingestion.normalization is not None:
        number = ingestion.normalization.invoice.invoice_number
        if number:
            return number
    return Path(ingestion.source_path).stem


def _validation_reason(validation: ValidationResult) -> str:
    messages = [issue.message for issue in validation.issues]
    if messages:
        return f"{validation.reason}: {'; '.join(messages)}"
    return validation.error_message or validation.reason


def _finish(result: WorkflowResult, context: RunContext | None) -> WorkflowResult:
    if context is not None:
        context.run_dir.mkdir(parents=True, exist_ok=True)
        write_artifact(context.run_dir, "workflow_result.json", result)
        append_event(
            context.run_dir,
            "workflow",
            "completed",
            status=result.status.value,
            stopped_at=result.stopped_at,
            reason=result.reason,
            invoice_id=result.invoice_id,
            vp_review_required=result.vp_review_required,
        )
    return result


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
