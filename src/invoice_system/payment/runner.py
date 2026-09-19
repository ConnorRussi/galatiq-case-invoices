"""Local mock payment execution and audit logging."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..ingestion.run_logging import (
    RunContext,
    append_event,
    make_run_id,
    write_artifact,
)
from .models import PaymentRequest, PaymentResult, PaymentStatus


PaymentProvider = Callable[[str, Decimal, str], Mapping[str, Any]]


def mock_payment(vendor: str, amount: Decimal, currency: str) -> dict[str, str]:
    """Simulate the README payment API without an external side effect."""

    return {
        "status": "success",
        "transaction_id": f"mock-{uuid4().hex[:12]}",
    }


def run_payment(
    request: PaymentRequest,
    *,
    provider: PaymentProvider = mock_payment,
    logs_root: Path | None = None,
    artifact_context: RunContext | None = None,
    persist_artifacts: bool = True,
) -> PaymentResult:
    """Execute a mock payment and always return an auditable result."""

    if not isinstance(request, PaymentRequest):
        request = PaymentRequest.model_validate(request)

    context = None
    if persist_artifacts:
        if artifact_context is None:
            root = logs_root or Path("logs")
            run_id = make_run_id(request.invoice_id, "payment")
            context = RunContext(run_id, root / "payment" / run_id)
            context.run_dir.mkdir(parents=True, exist_ok=False)
            write_artifact(
                context.run_dir,
                "payment_run.json",
                {"run_id": context.run_id, "invoice_id": request.invoice_id},
            )
        else:
            context = artifact_context
            context.run_dir.mkdir(parents=True, exist_ok=True)
        write_artifact(context.run_dir, "payment_input.json", request)
        append_event(
            context.run_dir,
            "payment",
            "started",
            invoice_id=request.invoice_id,
            vendor=request.vendor,
            amount=str(request.amount),
            currency=request.currency,
        )

    try:
        response = provider(request.vendor, request.amount, request.currency)
        provider_status = str(response.get("status", "")).lower()
        if provider_status != "success":
            raise RuntimeError(str(response.get("reason") or "Mock payment was not successful"))
        result = PaymentResult(
            status=PaymentStatus.SUCCESS,
            invoice_id=request.invoice_id,
            vendor=request.vendor,
            amount=request.amount,
            currency=request.currency,
            transaction_id=str(response.get("transaction_id") or f"mock-{uuid4().hex[:12]}"),
            reason="Mock payment completed successfully.",
        )
    except Exception as exc:
        result = PaymentResult(
            status=PaymentStatus.FAILED,
            invoice_id=request.invoice_id,
            vendor=request.vendor,
            amount=request.amount,
            currency=request.currency,
            reason=str(exc),
        )

    if context is not None:
        write_artifact(context.run_dir, "payment_result.json", result)
        append_event(
            context.run_dir,
            "payment",
            "completed" if result.status == PaymentStatus.SUCCESS else "failed",
            status=result.status.value,
            reason=result.reason,
            transaction_id=result.transaction_id,
        )
    return result
