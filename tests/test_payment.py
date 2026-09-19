import json
from decimal import Decimal

from invoice_system.ingestion.run_logging import RunContext
from invoice_system.payment import PaymentRequest, PaymentStatus, run_payment


def test_mock_payment_succeeds_and_writes_shared_run_artifacts(tmp_path):
    context = RunContext("workflow-test", tmp_path / "run")
    request = PaymentRequest(
        invoice_id="INV-1",
        vendor="Acme Supplies",
        amount="125.50",
        currency="USD",
    )

    result = run_payment(request, artifact_context=context)

    assert result.status == PaymentStatus.SUCCESS
    assert result.transaction_id is not None
    assert (context.run_dir / "payment_input.json").exists()
    assert (context.run_dir / "payment_result.json").exists()
    events = [json.loads(line) for line in (context.run_dir / "events.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["started", "completed"]


def test_payment_provider_failure_is_returned_not_raised():
    request = PaymentRequest(invoice_id="INV-2", vendor="Vendor", amount=Decimal("10"))

    result = run_payment(
        request,
        provider=lambda vendor, amount: {"status": "failed", "reason": "provider unavailable"},
        persist_artifacts=False,
    )

    assert result.status == PaymentStatus.FAILED
    assert result.reason == "provider unavailable"
    assert result.transaction_id is None
