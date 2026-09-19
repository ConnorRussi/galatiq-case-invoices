from decimal import Decimal

from invoice_system.ingestion.models import NormalizedInvoice
from invoice_system.validation.arithmetic import (
    build_arithmetic_evidence,
    decimal_multiply,
    decimal_subtract,
    decimal_sum,
)


def test_decimal_sum_and_subtraction_are_exact():
    assert decimal_sum([Decimal("5"), Decimal("3"), Decimal("4")]) == Decimal("12")
    assert decimal_subtract(Decimal("10.10"), Decimal("0.10")) == Decimal("10.00")


def test_decimal_multiplication_preserves_money_value():
    assert decimal_multiply(Decimal("8"), Decimal("10.25")) == Decimal("82.00")


def test_arithmetic_evidence_consolidates_repeated_products():
    invoice = NormalizedInvoice.model_validate({
        "items": [
            {"item_name": "Gadget A", "quantity": "5", "unit_price": "10", "line_amount": "50"},
            {"item_name": "Gadget A", "quantity": "3", "unit_price": "10", "line_amount": "30"},
            {"item_name": "Gadget B", "quantity": "2", "unit_price": "10.25", "line_amount": "20.50"},
        ],
        "subtotal": "100.50",
    })
    evidence = build_arithmetic_evidence(invoice)
    assert evidence["calculated_subtotal"] == Decimal("100.50")
    assert evidence["consolidated_items"][0]["combined_quantity"] == Decimal("8")
    assert evidence["consolidated_items"][0]["source_lines"] == [1, 2]
    assert evidence["consolidated_items"][1]["derived_line_total"] == Decimal("20.50")
