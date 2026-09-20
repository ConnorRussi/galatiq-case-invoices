from decimal import Decimal

from invoice_system.ingestion.models import IngestionResult, NormalizationResult, NormalizedInvoice
from invoice_system.validation.arithmetic import (
    build_arithmetic_evidence,
    build_reconciliation_checks,
    decimal_multiply,
    decimal_subtract,
    decimal_sum,
)
from invoice_system.validation.database import resolve_inventory
from invoice_system.validation.database_tool import InventoryLookup
from invoice_system.validation.models import ReconciliationCheckOutcome, ReconciliationCheckType


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


def test_consolidation_preserves_multiple_prices_without_a_conflict_signal():
    invoice = NormalizedInvoice.model_validate({
        "items": [
            {"item_name": "Gadget A", "quantity": "5", "unit_price": "10", "line_amount": "50"},
            {"item_name": "Gadget A", "quantity": "3", "unit_price": "20", "line_amount": "60"},
        ],
        "subtotal": "110",
        "tax_amount": "0",
        "invoice_total": "110",
    })

    consolidated = build_arithmetic_evidence(invoice)["consolidated_items"][0]

    assert consolidated["unit_prices"] == [Decimal("10"), Decimal("20")]
    assert consolidated["unit_price"] is None
    assert "conflicting_prices" not in consolidated
    assert consolidated["derived_line_total"] == Decimal("110")


def test_missing_quantity_is_not_consolidated_as_zero():
    invoice = NormalizedInvoice.model_validate({
        "items": [{"item_name": "Gadget A", "unit_price": "10"}],
    })

    consolidated = build_arithmetic_evidence(invoice)["consolidated_items"][0]

    assert consolidated["combined_quantity"] is None


def test_database_denies_inventory_sufficiency_without_quantity():
    ingestion = IngestionResult(
        status="accept",
        source_path="controlled.json",
        normalization=NormalizationResult(
            invoice={"items": [{"item_name": "WidgetA"}]},
            evidence=[],
        ),
    )

    result = resolve_inventory(ingestion, db_path="inventory.sqlite")

    assert result.status.value == "DENY"
    assert result.issues[0].code == "MISSING_QUANTITY"


def test_reconciliation_checks_use_decimal_outcomes_not_model_labels():
    invoice = NormalizedInvoice.model_validate({
        "items": [{"item_name": "Gadget A", "quantity": "3", "unit_price": "10", "line_amount": "30.00"}],
        "subtotal": "30",
        "tax_amount": "0",
        "invoice_total": "31",
    })

    checks = build_reconciliation_checks(invoice)

    assert checks[0].check_type == ReconciliationCheckType.LINE_TOTAL
    assert checks[0].outcome == ReconciliationCheckOutcome.MATCH
    assert checks[1].check_type == ReconciliationCheckType.SUBTOTAL
    assert checks[1].outcome == ReconciliationCheckOutcome.MATCH
    assert checks[2].check_type == ReconciliationCheckType.TOTAL
    assert checks[2].outcome == ReconciliationCheckOutcome.MISMATCH


def test_rush_fulfillment_qualifier_consolidates_identity_but_preserves_lines_and_prices():
    invoice = NormalizedInvoice.model_validate({
        "items": [
            {"item_name": "WidgetA", "quantity": "8", "unit_price": "250", "line_amount": "2000"},
            {"item_name": "WidgetA (rush order)", "quantity": "4", "unit_price": "300", "line_amount": "1200"},
        ],
        "subtotal": "3200",
    })

    evidence = build_arithmetic_evidence(invoice)
    consolidated = evidence["consolidated_items"]

    assert len(consolidated) == 1
    assert consolidated[0]["product_name"] == "WidgetA"
    assert consolidated[0]["combined_quantity"] == Decimal("12")
    assert consolidated[0]["derived_line_total"] == Decimal("3200")
    assert consolidated[0]["source_lines"] == [1, 2]
    assert consolidated[0]["unit_prices"] == [Decimal("250"), Decimal("300")]
    assert [(item["source_line"], item["resolved_product"]) for item in evidence["identity_mappings"]] == [
        (1, "WidgetA"),
        (2, "WidgetA"),
    ]


def test_unknown_parenthesized_qualifier_remains_separate_and_unresolved():
    invoice = NormalizedInvoice.model_validate({
        "items": [
            {"item_name": "WidgetA", "quantity": "8"},
            {"item_name": "WidgetA (blue finish)", "quantity": "4"},
        ],
    })

    evidence = build_arithmetic_evidence(invoice)

    assert [item["source_lines"] for item in evidence["consolidated_items"]] == [[1], [2]]
    assert evidence["identity_mappings"][1]["resolution"] == "unresolved_qualifier"
    assert evidence["identity_mappings"][1]["resolved_product"] is None


def test_inventory_checks_consolidated_quantity_against_stock(monkeypatch):
    ingestion = IngestionResult(
        status="accept",
        source_path="controlled.json",
        normalization=NormalizationResult(invoice={
            "items": [
                {"item_name": "WidgetA", "quantity": "8"},
                {"item_name": "WidgetA (rush order)", "quantity": "8"},
            ],
        }, evidence=[]),
    )
    # Materialize the same deterministic result used by the graph without a model call.
    from invoice_system.validation.arithmetic import build_arithmetic_evidence
    from invoice_system.validation.models import ReconciliationResult

    evidence = build_arithmetic_evidence(ingestion.normalization.invoice)
    recon = ReconciliationResult.model_validate({
        "status": "PASS",
        "summary": "fixture",
        "consolidated_items": evidence["consolidated_items"],
        "identity_mappings": evidence["identity_mappings"],
    })
    monkeypatch.setattr(
        "invoice_system.validation.database.lookup_inventory_bulk",
        lambda names, **kwargs: [InventoryLookup(
            requested_name=names[0], matched_item="WidgetA", available_stock=15, product_found=True
        )],
    )

    database_result = resolve_inventory(
        ingestion,
        reconciliation_result=recon,
        retry_proposer=lambda unresolved: [],
    )

    assert database_result.status.value == "DENY"
    assert database_result.issues[0].code == "INSUFFICIENT_INVENTORY"
    assert database_result.results[0].requested_quantity == Decimal("16")
    assert database_result.results[0].source_lines == [1, 2]
