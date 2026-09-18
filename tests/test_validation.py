from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from invoice_system.ingestion.models import (
    EvidenceLocator, ExtractedField, IngestionResult, Invoice, Issue, LineItem,
)
from invoice_system.validation import (
    AgentDecision, CheckStatus, IngestionRecheckRequest, SQLiteInventory, StructuredValidationAgent,
    ValidationSettings, consolidate_line_items, recalculate_invoice, validate_invoice,
)
from invoice_system.validation.models import InventoryRecord, InventoryResult, ValidationReport


def field(value=None, *, literal=None):
    return ExtractedField(normalized=value, original=str(value) if value is not None else literal)


def line(name="WidgetA", quantity="2", price="10", amount="20"):
    return LineItem(name=field(name), quantity=field(Decimal(quantity)), unit_price=field(Decimal(price)),
                    declared_amount=field(Decimal(amount) if amount is not None else None), note=field())


def candidate(items=None, **values):
    fields = {name: field() for name in Invoice.model_fields if name != "line_items"}
    fields.update({name: field(value) for name, value in {
        "invoice_number": "INV-1", "vendor": "Acme", "currency": "USD",
        "invoice_date": date(2026, 1, 1), "due_date": date(2026, 2, 1),
        "subtotal": Decimal("20"), "declared_total": Decimal("20"), **values,
    }.items()})
    return Invoice(**fields, line_items=items if items is not None else [line()])


@pytest.fixture
def inventory_path(tmp_path):
    path = tmp_path / "inventory.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE inventory (item TEXT PRIMARY KEY, stock INTEGER)")
        conn.executemany("INSERT INTO inventory VALUES (?, ?)", [("WidgetA", 15), ("WidgetB", 10), ("GadgetX", 5)])
    return path


def codes(report):
    return {finding.code for finding in report.findings}


def check(report, code):
    return next(c for c in report.checks if c.code == code)


def ambiguous_handoff():
    invoice = candidate()
    evidence = EvidenceLocator(page=1, bbox=[0, 0, 10, 10])
    invoice.line_items[0].quantity.original = "2 or 7"
    invoice.line_items[0].quantity.normalized = None
    invoice.line_items[0].quantity.evidence = [evidence]
    return IngestionResult(run_id="source", status="needs_review", invoice=invoice, issues=[
        Issue(code="AMBIGUOUS_EXTRACTION", field="line_items[0].quantity", message="Competing quantity readings", evidence=[evidence]),
    ])


def test_happy_path_and_serialization(inventory_path):
    report = validate_invoice(candidate(), inventory_path=inventory_path)
    assert report.validation_complete and report.disposition == "clear"
    assert not report.unresolved_questions
    assert all(c.status == CheckStatus.PASSED for c in report.checks)
    assert len(report.tool_calls) == 3
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report
    assert "approved" not in report.model_dump_json() and "rejected" not in report.model_dump_json()


def test_consolidation_preserves_lineage_and_all_rows():
    rows = [line("WidgetA", "10"), line("WidgetA", "12"), line("WidgetB", "4"), line("WidgetB", "14"), line("GadgetX", "9")]
    original = [row.model_dump() for row in rows]
    grouped = consolidate_line_items(rows)
    assert [(g.item, g.quantity) for g in grouped] == [("WidgetA", Decimal(22)), ("WidgetB", Decimal(18)), ("GadgetX", Decimal(9))]
    assert [g.source_rows for g in grouped] == [[0, 1], [2, 3], [4]]
    assert [row.model_dump() for row in rows] == original


def test_inv_1013_all_findings(inventory_path):
    path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1013.json"
    data = json.loads(path.read_text(), parse_float=Decimal)
    invoice = candidate(
        [line(r["item"], str(r["quantity"]), str(r["unit_price"]), str(r["amount"])) for r in data["line_items"]],
        invoice_number=data["invoice_number"], subtotal=data["subtotal"], tax=data["tax_amount"], declared_total=data["total"],
    )
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert report.validation_complete and report.disposition == "blocked"
    assert report.arithmetic.computed_total == Decimal("22512.80")
    assert report.arithmetic.declared_total == Decimal("22562.80")
    assert report.arithmetic.variance == Decimal("50.00")
    assert report.arithmetic.within_tolerance is False
    stock = [f for f in report.findings if f.code == "INSUFFICIENT_INVENTORY"]
    assert [(f.subject, f.actual, f.expected) for f in stock] == [("WidgetA", "22", "15"), ("WidgetB", "18", "10"), ("GadgetX", "9", "5")]
    assert codes(report) == {"INSUFFICIENT_INVENTORY", "TOTAL_MISMATCH", "HIGH_VALUE_REVIEW_REQUIRED"}
    assert len(report.original_invoice.line_items) == 8
    assert report.recheck_request is None


def test_all_arithmetic_and_date_failures_run(inventory_path):
    invoice = candidate([line(amount="21")], subtotal=Decimal("22"), declared_total=Decimal("23"), due_date=date(2025, 1, 1))
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert {"LINE_ITEM_TOTAL_MISMATCH", "LINE_ITEMS_SUBTOTAL_MISMATCH", "TOTAL_MISMATCH", "INVALID_DATE_ORDER"} <= codes(report)
    assert check(report, "INVENTORY_AVAILABILITY").status == CheckStatus.PASSED


@pytest.mark.parametrize("delta,within", [("0.01", True), ("0.0101", False), ("-0.01", True), ("-0.02", False)])
def test_decimal_tolerance(delta, within):
    invoice = candidate(declared_total=Decimal(20) + Decimal(delta))
    with localcontext() as ctx:
        ctx.prec = 3
        result = recalculate_invoice(invoice)
    assert result.within_tolerance is within
    assert result.variance == Decimal(delta)


def test_optional_components_are_explicit_and_present_unknown_blocks(inventory_path):
    invoice = candidate(tax=Decimal("1.5"), shipping=Decimal("2.25"), fees=Decimal(".75"), declared_total=Decimal("24.50"))
    facts = recalculate_invoice(invoice)
    assert facts.computed_total == Decimal("24.50") and facts.absent_components == []
    invoice.shipping = field(literal="unreadable")
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert report.arithmetic.computed_total is None
    assert report.arithmetic.unavailable_fields == ["shipping"]
    assert "TOTAL_MISMATCH" not in codes(report)
    assert report.disposition == "unresolved"
    absent = recalculate_invoice(candidate())
    assert absent.shipping is None and "shipping" in absent.absent_components


def test_missing_optional_subtotal_line_amount_and_due_date_skip_explicitly(inventory_path):
    invoice = candidate([line(amount=None)], subtotal=None, due_date=None)
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert report.disposition == "clear"
    for code in ("LINE_ITEM_ARITHMETIC", "SUBTOTAL_RECONCILIATION", "DATE_CONSISTENCY"):
        assert check(report, code).status == CheckStatus.SKIPPED
        assert check(report, code).skip_reason


def test_unknown_inventory_and_parameterized_lookup(inventory_path):
    name = "WidgetA'); DROP TABLE inventory;--"
    report = validate_invoice(candidate([line(name)]), inventory_path=inventory_path)
    assert "UNKNOWN_INVENTORY_ITEM" in codes(report)
    assert "INSUFFICIENT_INVENTORY" not in codes(report)
    assert SQLiteInventory(inventory_path).lookup(["WidgetA"]).records[0].stock == 15


def test_inventory_unavailable_is_unresolved_and_does_not_create_db(tmp_path):
    path = tmp_path / "missing.sqlite"
    report = validate_invoice(candidate(), inventory_path=path)
    assert report.validation_complete and report.disposition == "unresolved"
    assert "INSUFFICIENT_INVENTORY" not in codes(report)
    assert check(report, "INVENTORY_AVAILABILITY").status == CheckStatus.UNRESOLVED
    assert report.inventory.error and report.unresolved_questions
    assert len([call for call in report.tool_calls if call.tool == "get_inventory"]) == 2
    assert not path.exists()


def test_invalid_database_stock_is_not_business_failure(inventory_path):
    with sqlite3.connect(inventory_path) as conn:
        conn.execute("UPDATE inventory SET stock = ? WHERE item = ?", ("untrusted", "WidgetA"))
    report = validate_invoice(candidate(), inventory_path=inventory_path)
    assert report.disposition == "unresolved" and "INSUFFICIENT_INVENTORY" not in codes(report)


def test_justified_targeted_reingestion_preserves_original(inventory_path):
    handoff = ambiguous_handoff()
    before = handoff.model_dump_json()
    calls = []

    def reingest(source, request):
        calls.append(request)
        source.invoice.line_items[0].quantity.original = "2"
        source.invoice.line_items[0].quantity.normalized = Decimal(2)
        source.issues = []
        source.status = "ready_for_validation"
        return source

    report = validate_invoice(handoff, inventory_path=inventory_path, reingest=reingest)
    assert report.disposition == "clear" and report.reingestion_attempts == 1
    assert calls[0].fields == ["line_items[0].quantity"]
    assert calls[0].reason_code == "AMBIGUOUS_EXTRACTION" and calls[0].evidence
    assert report.original_invoice.line_items[0].quantity.original == "2 or 7"
    assert report.invoice.line_items[0].quantity.normalized == Decimal(2)
    assert handoff.model_dump_json() == before


def test_reingestion_bound_when_ambiguity_remains(inventory_path):
    calls = []

    def reingest(source, request):
        calls.append(request)
        return source

    report = validate_invoice(ambiguous_handoff(), inventory_path=inventory_path, reingest=reingest)
    assert len(calls) == report.reingestion_attempts == 1
    assert report.disposition == "unresolved"
    assert report.validation_complete


def test_business_failure_never_causes_reingestion(inventory_path):
    def forbidden(*args):
        pytest.fail("Business failure must not cause re-ingestion")

    report = validate_invoice(candidate([line(quantity="22", amount="220")], subtotal=Decimal(220), declared_total=Decimal(220)),
                              inventory_path=inventory_path, reingest=forbidden)
    assert codes(report) == {"INSUFFICIENT_INVENTORY"}
    assert report.recheck_request is None and report.reingestion_attempts == 0


def test_agent_cannot_authorize_reingestion_from_stock_failure(inventory_path):
    class BadAgent:
        def decide(self, view):
            return AgentDecision(recheck=IngestionRecheckRequest(fields=["line_items[0].quantity"],
                                 reason_code="SOURCE_CONTRADICTION", explanation="Inventory too low"))

    report = validate_invoice(candidate(), agent=BadAgent(), inventory_path=inventory_path)
    assert report.recheck_request is None and report.reingestion_attempts == 0
    assert report.disposition == "unresolved"


def test_reingestion_cannot_change_untargeted_claims(inventory_path):
    def reingest(source, request):
        source.invoice.declared_total.normalized = Decimal(1)
        return source

    report = validate_invoice(ambiguous_handoff(), reingest=reingest, inventory_path=inventory_path)
    assert report.invoice.declared_total.normalized == 20
    assert any("untargeted field" in question for question in report.unresolved_questions)


def test_reingestion_missing_adapter_is_explicit(inventory_path):
    report = validate_invoice(ambiguous_handoff(), inventory_path=inventory_path)
    assert report.recheck_request and report.reingestion_attempts == 0
    assert any("no re-ingestion adapter" in question for question in report.unresolved_questions)


@pytest.mark.parametrize("budget", [0, 1, 2])
def test_tool_budget_exhaustion(budget, inventory_path):
    report = validate_invoice(candidate(declared_total=Decimal(22)), inventory_path=inventory_path,
                              settings=ValidationSettings(max_tool_calls=budget))
    assert len(report.tool_calls) == budget
    assert not report.validation_complete and report.disposition == "unresolved"
    assert report.tool_budget_exhausted
    assert all(c.status != CheckStatus.PENDING for c in report.checks)


def test_repeated_agent_requests_terminate(inventory_path):
    class LoopAgent:
        def decide(self, view):
            return AgentDecision(tool="recalculate_invoice")

    report = validate_invoice(candidate(), agent=LoopAgent(), inventory_path=inventory_path,
                              settings=ValidationSettings(max_tool_calls=4))
    assert not report.validation_complete and report.disposition == "unresolved"
    assert len(report.tool_calls) == 4


def test_agent_cannot_mutate_source_or_omit_baseline(inventory_path):
    class MutationAgent:
        def decide(self, view):
            view.handoff.invoice.line_items[0].quantity.normalized = Decimal(0)
            view.handoff.invoice.declared_total.normalized = Decimal(0)
            view.handoff.invoice.line_items.clear()
            view.checks.clear()
            return AgentDecision()

    invoice = candidate()
    before = invoice.model_dump_json()
    report = validate_invoice(invoice, agent=MutationAgent(), inventory_path=inventory_path)
    assert report.disposition == "clear" and len(report.tool_calls) == 3
    assert report.invoice == invoice and invoice.model_dump_json() == before


def test_agent_failure_does_not_skip_required_work(inventory_path):
    class BrokenAgent:
        def decide(self, view):
            raise RuntimeError("Model unavailable")

    report = validate_invoice(candidate(), agent=BrokenAgent(), inventory_path=inventory_path)
    assert len(report.tool_calls) == 3
    assert report.disposition == "unresolved"
    assert check(report, "INVOICE_TOTAL").status == CheckStatus.PASSED


def test_agent_can_add_check_but_unknown_validator_is_unresolved(inventory_path):
    class ExtraAgent:
        def decide(self, view):
            return AgentDecision(additional_checks=["VENDOR_IDENTITY"])

    report = validate_invoice(candidate(), agent=ExtraAgent(), inventory_path=inventory_path)
    assert check(report, "VENDOR_IDENTITY").status == CheckStatus.UNRESOLVED
    assert len(report.tool_calls) == 3


def test_bounded_additional_inventory_investigation_recovers(inventory_path):
    class FlakyInventory:
        calls = 0

        def lookup(self, names):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Temporary read failure")
            return SQLiteInventory(inventory_path).lookup(names)

    inventory = FlakyInventory()
    report = validate_invoice(candidate(), inventory=inventory)
    assert inventory.calls == 2 and report.disposition == "clear"
    assert report.tool_calls[-2].error and not report.tool_calls[-1].error
    assert len(check(report, "INVENTORY_AVAILABILITY").tool_calls) == 3


def test_incomplete_inventory_response_does_not_pass():
    class IncompleteInventory:
        def lookup(self, names):
            return InventoryResult()

    report = validate_invoice(candidate(), inventory=IncompleteInventory())
    assert check(report, "INVENTORY_AVAILABILITY").status == CheckStatus.UNRESOLVED
    assert "INSUFFICIENT_INVENTORY" not in codes(report)


def test_conflicting_inventory_records_are_unresolved():
    class ConflictingInventory:
        def lookup(self, names):
            return InventoryResult(records=[InventoryRecord(item="WidgetA", stock=15)], unknown_items=["WidgetA"])

    report = validate_invoice(candidate(), inventory=ConflictingInventory())
    assert report.disposition == "unresolved" and "UNKNOWN_INVENTORY_ITEM" not in codes(report)


def test_missing_quantities_never_become_partial_stock_sums(inventory_path):
    invoice = candidate([line(), line()])
    invoice.line_items[1].quantity.normalized = None
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert report.consolidated_items[0].quantity is None
    assert check(report, "INVENTORY_AVAILABILITY").status == CheckStatus.UNRESOLVED
    assert "INSUFFICIENT_INVENTORY" not in codes(report)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_shared_normalized_model_rejects_nonfinite_values(value):
    with pytest.raises(ValidationError):
        field(value)


def test_negative_quantity_cannot_reduce_inventory_request(inventory_path):
    invoice = candidate([line(quantity="22", amount="220"), line(quantity="-20", amount="-200")])
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert "INVALID_LINE_ITEM_VALUE" in codes(report)
    assert report.consolidated_items[0].quantity is None
    assert report.disposition == "blocked"


def test_no_candidate_is_terminal_unresolved(inventory_path):
    report = validate_invoice(IngestionResult(run_id="bad", status="technical_failure"), inventory_path=inventory_path)
    assert report.validation_complete and report.disposition == "unresolved"
    assert not report.tool_calls


def test_missing_required_fields_do_not_suppress_independent_checks(inventory_path):
    report = validate_invoice(candidate(vendor=None, declared_total=None), inventory_path=inventory_path)
    assert report.disposition == "unresolved"
    assert check(report, "REQUIRED_INPUTS").status == CheckStatus.UNRESOLVED
    assert check(report, "INVENTORY_AVAILABILITY").status == CheckStatus.PASSED


def test_high_value_policy_is_configured_not_agent_decision(inventory_path):
    report = validate_invoice(candidate(), inventory_path=inventory_path, settings=ValidationSettings(high_value_threshold=Decimal(10)))
    assert "HIGH_VALUE_REVIEW_REQUIRED" in codes(report)
    assert report.disposition == "clear"  # A review flag is not a payment decision.
    disabled = validate_invoice(candidate(), inventory_path=inventory_path, settings=ValidationSettings(high_value_threshold=None))
    assert "HIGH_VALUE_POLICY" not in {c.code for c in disabled.checks}
    foreign = validate_invoice(candidate(currency="EUR"), inventory_path=inventory_path)
    assert check(foreign, "HIGH_VALUE_POLICY").status == CheckStatus.UNRESOLVED


def test_report_rejects_forged_outcome(inventory_path):
    report = validate_invoice(candidate(), inventory_path=inventory_path)
    payload = report.model_dump()
    payload["disposition"] = "blocked"
    with pytest.raises(ValidationError):
        ValidationReport.model_validate(payload)


def test_structured_agent_transport_is_constrained_and_requires_no_llm(inventory_path):
    observations = []

    def transport(instructions, observation, schema):
        assert "never calculate trusted amounts" in instructions
        assert schema is AgentDecision
        observations.append(json.loads(observation))
        return '{"explanation":"Complete the mandatory checks"}'

    report = validate_invoice(candidate(), agent=StructuredValidationAgent(transport), inventory_path=inventory_path)
    assert report.disposition == "clear"
    assert observations[0]["phase"] == "handoff" and observations[-1]["findings"] == []


def test_persisted_ingestion_handoff_cli(tmp_path, inventory_path, capsys):
    from invoice_system.validation.__main__ import main

    path = tmp_path / "result.json"
    path.write_text(IngestionResult(run_id="fixture", status="ready_for_validation", invoice=candidate()).model_dump_json(), encoding="utf-8")
    assert main([str(path), "--inventory-db", str(inventory_path)]) == 0
    report = ValidationReport.model_validate_json(capsys.readouterr().out)
    assert report.disposition == "clear" and report.validation_complete


def test_reingestion_cannot_erase_unrelated_issues(inventory_path):
    handoff = ambiguous_handoff()
    handoff.issues.append(Issue(code="MISSING_FIELD", field="vendor", message="Vendor evidence needs review"))

    def reingest(source, request):
        source.issues = []
        return source

    report = validate_invoice(handoff, reingest=reingest, inventory_path=inventory_path)
    assert any("untargeted ingestion issue" in question for question in report.unresolved_questions)


def test_agent_turn_limit_preserves_baseline(inventory_path):
    report = validate_invoice(candidate(), inventory_path=inventory_path, settings=ValidationSettings(max_agent_turns=1))
    assert len(report.tool_calls) == 3
    assert report.disposition == "unresolved" and report.validation_complete
    assert any("turn limit" in question for question in report.unresolved_questions)


def test_financial_precision_exhaustion_is_unresolved_not_silent_rounding(inventory_path):
    invoice = candidate([line(price="1." + "1" * 70)])
    report = validate_invoice(invoice, inventory_path=inventory_path)
    assert check(report, "INVOICE_TOTAL").status == CheckStatus.UNRESOLVED
    assert report.arithmetic is None and "TOTAL_MISMATCH" not in codes(report)
    assert any("Inexact" in question for question in report.unresolved_questions)


@pytest.mark.parametrize("tolerance", [0.01, Decimal("-0.01"), Decimal("NaN")])
def test_arithmetic_tool_rejects_invalid_tolerance(tolerance):
    with pytest.raises(ValueError):
        recalculate_invoice(candidate(), tolerance)
