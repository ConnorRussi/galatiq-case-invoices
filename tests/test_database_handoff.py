"""Exercise the CLI's actual validation graph with offline model responses."""
import json
from decimal import Decimal

import pytest

from invoice_system.ingestion.models import IngestionResult, NormalizationResult
from invoice_system.validation import critic, graph, reconciliation, runner
from invoice_system.validation.models import SemanticResult


def source():
    return IngestionResult(status="accept", source_path="controlled.txt",
        normalization=NormalizationResult(invoice={
            "items": [
                {"item_name": "WidgetA", "quantity": "8", "unit_price": "250", "line_amount": "2000"},
                {"item_name": "WidgetB", "quantity": "4", "unit_price": "500", "line_amount": "2000"},
                {"item_name": "GadgetX", "quantity": "2", "unit_price": "750", "line_amount": "1500"},
                {"item_name": "WidgetA (rush order)", "quantity": "4", "unit_price": "300", "line_amount": "1200"},
            ], "subtotal": "6700", "tax_amount": "335", "shipping": "150", "invoice_total": "7185",
        }, evidence=[]))


def setup_models(monkeypatch, response=None):
    captured = []
    monkeypatch.setattr(graph, "validate_semantics", lambda *a, **k: SemanticResult(status="PASS", summary="valid"))
    monkeypatch.setattr(reconciliation, "invoke_structured",
        lambda **k: k["output_model"](status="PASS", summary="reconciles"))

    def review(**kwargs):
        payload = json.loads(kwargs["content"])
        if payload["current_stage"] == "database":
            captured.append(payload)
            return kwargs["output_model"].model_validate(response or {"decision": "AGREE", "summary": "supported"})
        return kwargs["output_model"](decision="AGREE", summary="supported")

    monkeypatch.setattr(critic, "invoke_structured", review)
    return captured


def test_real_graph_delivers_mapping_and_preserves_invoice(monkeypatch):
    captured = setup_models(monkeypatch)
    ingestion = source()
    before = ingestion.model_dump(mode="json")
    result = runner.run_validation(ingestion, run_database=True, persist_artifacts=False)
    assert result.status.value == "VALID"
    assert ingestion.model_dump(mode="json") == before
    payload = captured[0]
    mapping = payload["reconciliation_result"]["identity_mappings"][3]
    assert mapping["source_description"] == "WidgetA (rush order)"
    assert mapping["resolved_product"] == "WidgetA"
    assert mapping["qualifier"] == "rush order"
    item = result.database_result.results[0]
    assert item.source_lines == [1, 4]
    assert item.requested_quantity == 12 and item.available_stock == 15
    consolidated = result.reconciliation_result.consolidated_items[0]
    assert consolidated.unit_prices == [250, 300]
    assert consolidated.derived_line_total == 3200
    assert result.reconciliation_result.calculations[-1].calculated == 7185
    assert payload["deterministic_database_findings"] == []


@pytest.mark.parametrize("damage,code", [
    ("missing", "DATABASE_LINE_COVERAGE"),
    ("duplicate", "DATABASE_LINE_COVERAGE"),
    ("quantity", "DATABASE_QUANTITY_MISMATCH"),
    ("stock", "DATABASE_STOCK_MISMATCH"),
    ("unknown", "DATABASE_UNSUPPORTED_PASS"),
])
def test_real_graph_rejects_inconsistent_database_pass(monkeypatch, damage, code):
    setup_models(monkeypatch)
    resolve = graph.resolve_inventory

    def damaged(*args, **kwargs):
        result = resolve(*args, **kwargs)
        item = result.results[0]
        if damage == "missing":
            item.source_lines = [1]
        elif damage == "duplicate":
            item.source_lines = [1, 4, 4]
        elif damage == "quantity":
            item.requested_quantity = Decimal("8")
        elif damage == "stock":
            item.available_stock = 10
        else:
            item.matched_item = None
            item.product_found = False
        return result

    monkeypatch.setattr(graph, "resolve_inventory", damaged)
    result = runner.run_validation(source(), run_database=True, persist_artifacts=False)
    assert result.status.value == "DENIED"
    assert result.reason == "unresolved_validation"
    assert code in {f.code for f in result.database_critic_result.findings}


@pytest.mark.parametrize("response", [
    {"decision": "AGREE", "summary": "supported", "revision_instructions": "Check identity"},
    {"decision": "AGREE", "summary": "supported", "findings": [
        {"code": "UNSUPPORTED_IDENTITY", "message": "Identity is ambiguous"}]},
])
def test_contradictory_agreement_never_reaches_approval(monkeypatch, response):
    setup_models(monkeypatch, response)
    result = runner.run_validation(source(), run_database=True, persist_artifacts=False)
    assert result.status.value == "DENIED"
    assert "CRITIC_CONTRADICTION" in {f.code for f in result.database_critic_result.findings}


def test_identity_disagreement_is_not_overridden_by_complete_coverage(monkeypatch):
    setup_models(monkeypatch, {"decision": "REVISE", "summary": "Identity needs review",
        "findings": [{"code": "MISSING_LOOKUP_FOR_VARIANT", "message": "Review the identity mapping"}]})
    result = runner.run_validation(source(), run_database=True, persist_artifacts=False)
    assert result.status.value == "DENIED"
    assert result.database_critic_result.findings[0].code == "MISSING_LOOKUP_FOR_VARIANT"


def test_supported_stock_denial_can_receive_agreement_with_findings(monkeypatch):
    setup_models(monkeypatch, {"decision": "AGREE", "summary": "Stock denial is supported",
        "findings": [{"code": "INSUFFICIENT_INVENTORY", "message": "16 exceeds 15"}]})
    ingestion = source()
    ingestion.normalization.invoice.items[3].quantity = Decimal("8")
    result = runner.run_validation(ingestion, run_database=True, persist_artifacts=False)
    assert result.status.value == "DENIED"
    assert result.reason == "database_denied"
    assert result.database_result.results[0].requested_quantity == 16
    assert result.database_critic_result.decision.value == "AGREE"
