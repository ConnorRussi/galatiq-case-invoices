from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from invoice_system.ingestion.artifacts import atomic_json
from invoice_system.ingestion.config import IngestionSettings, load_settings
from invoice_system.ingestion.extraction import InvalidInput, extract, read_source, valid_evidence
from invoice_system.ingestion.fake import FakeProvider, fixture_proposal
from invoice_system.ingestion.normalization import normalize, normalize_literal
from invoice_system.ingestion.providers import GeminiProvider, ModelContext, TransportFailure, _gemini_schema
from invoice_system.ingestion.models import Critique, EvidenceLocator, IngestionResult, InvoiceProposal, ObservedField, TransformationProposal
from invoice_system.ingestion.workflow import run_pipeline


def execute(path, tmp_path, settings, provider):
    return run_pipeline([path], settings=settings, provider=provider, runs_dir=tmp_path / "runs").results[0].result


def test_corpus(invoices, tmp_path, settings):
    batch = run_pipeline(invoices, settings=settings, provider=FakeProvider(), runs_dir=tmp_path / "runs")
    assert batch.status == "completed"
    a, b, c = [item.result for item in batch.results]
    assert a.issues == []
    assert a.invoice.invoice_number.value == "INV-1011"
    assert a.invoice.declared_total.value == Decimal("3000.00")
    assert b.invoice.vendor.value == "QuickShip Distributers"
    assert b.invoice.invoice_date.value == date(2026, 1, 26)
    assert b.invoice.invoice_date.observed.literal == "26-Jan-2O26"
    assert b.invoice.invoice_date.applied_rule == "ocr_date_O_to_0"
    assert b.invoice.line_items[0].name.value == "WidgetA"
    assert b.invoice.line_items[0].name.observed.literal == "Widget A"
    assert b.invoice.line_items[1].declared_amount.applied_rule == "ocr_money_O_to_0"
    assert len(c.invoice.line_items) == 8
    assert c.invoice.declared_total.value == Decimal("22562.80")
    assert len({r.run_id for r in (a, b, c)}) == 3
    for item in batch.results:
        directory = Path(item.artifact).parent
        assert {p.name for p in directory.iterdir()} >= {"source.json", "extraction.json", "result.json", "events.jsonl"}
        assert not list(directory.glob("*.pdf"))
        assert json.loads(Path(item.artifact).read_text())["invoice"]["declared_total"]["value"]
        assert IngestionResult.model_validate_json(Path(item.artifact).read_text()) == item.result
        records = [json.loads(s) for s in (directory / "events.jsonl").read_text().splitlines()]
        assert all({"node", "counters", "model", "prompt_version", "usage", "latency_ms", "outcome"} <= r.keys() for r in records)


def test_intake_hash_and_coordinates(invoices, settings, document):
    source, data = read_source(invoices[0], settings.documents)
    assert source.sha256 == hashlib.sha256(data).hexdigest()
    assert source.size_bytes == len(data)
    assert document.pages[0].blocks
    proposal = fixture_proposal(document)
    assert valid_evidence(proposal.vendor.literal, proposal.vendor.evidence, document, visual=False)
    bad = proposal.vendor.evidence[0].model_copy(update={"block_id": "invented"})
    assert not valid_evidence(proposal.vendor.literal, [bad], document, visual=False)
    assert not valid_evidence("Fabricated Vendor", proposal.vendor.evidence, document, visual=False)


@pytest.mark.parametrize("name,data", [("missing.pdf", None), ("input.doc", b"unsupported"), ("bad.pdf", b"not a pdf")])
def test_invalid_paths(name, data, tmp_path, settings):
    path = tmp_path / name
    if data is not None:
        path.write_bytes(data)
    assert execute(path, tmp_path, settings, FakeProvider()).status == "invalid_input"


@pytest.mark.parametrize("limit,value", [("max_file_bytes", 50), ("max_extracted_characters", 20), ("max_pdf_pages", 1)])
def test_document_limits(limit, value, invoices, tmp_path, settings):
    path = invoices[0]
    if limit == "max_pdf_pages":
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.add_page()
        path = tmp_path / "pages.pdf"
        pdf.output(path)
    setattr(settings.documents, limit, value)
    assert execute(path, tmp_path, settings, FakeProvider()).status == "invalid_input"


@pytest.mark.parametrize("literal,kind,expected,rule", [
    ("$3,500.O0", "declared_total", Decimal("3500.00"), "ocr_money_O_to_0"),
    ("-$1.00", "unit_price", None, None),
    ("$-1.00", "unit_price", Decimal("-1.00"), "decimal_money"),
    ("$250", "unit_price", Decimal("250"), "decimal_money"),
    ("26-Jan-2O26", "invoice_date", date(2026, 1, 26), "ocr_date_O_to_0"),
    ("2026-01-20", "invoice_date", date(2026, 1, 20), "controlled_date"),
    ("Widget A", "name", "WidgetA", "product_alias"),
    ("Widget B", "name", "WidgetB", "product_alias"),
    ("Gadget X", "name", "GadgetX", "product_alias"),
    ("Unknown Thing", "name", "Unknown Thing", None),
    ("QuickShip Distributers", "vendor", "QuickShip Distributers", None),
    ("-3", "quantity", Decimal("-3"), "decimal_quantity"),
    ("2.5", "quantity", Decimal("2.5"), "decimal_quantity"),
])
def test_normalization_accepted(literal, kind, expected, rule):
    if expected is None:
        with pytest.raises(ValueError):
            normalize_literal(literal, kind)
    else:
        assert normalize_literal(literal, kind) == (expected, rule)


@pytest.mark.parametrize("literal,kind", [
    ("$3,50O.000", "tax"), ("$O.OO", "tax"), ("$1,23.45", "tax"), ("NaN", "tax"),
    ("1e3", "unit_price"), ("$1.0O USD", "unit_price"), ("2026-02-30", "invoice_date"),
        ("26-JOn-2026", "invoice_date"), ("2O", "quantity"),
    ("two", "quantity"), ("Infinity", "quantity"),
])
def test_normalization_rejected(literal, kind):
    with pytest.raises(ValueError):
        normalize_literal(literal, kind)


def test_unsupported_and_ambiguous_fields(document):
    proposal = fixture_proposal(document)
    proposal.vendor.transformation = TransformationProposal(normalized="Other Vendor", explanation="spelling")
    proposal.invoice_number.alternatives = ["INV-1011", "INV-101I"]
    proposal.line_items[0].unit_price.literal = "$999"
    candidate, issues = normalize(proposal, document)
    assert candidate.vendor.value == "Summit Manufacturing Co."
    assert candidate.invoice_number.value is None
    assert candidate.line_items[0].unit_price.value is None
    assert {i.code for i in issues} >= {"REJECTED_TRANSFORMATION", "AMBIGUOUS_FIELD", "UNSUPPORTED_EVIDENCE"}


def test_partial_and_omission_critic(invoices, document, settings, tmp_path):
    proposal = fixture_proposal(document)
    proposal.vendor = ObservedField()
    result = execute(invoices[0], tmp_path, settings, FakeProvider({"interpret_text": [proposal]}))
    assert result.status == "ready_for_validation"
    assert any(i.code == "MISSING_FIELD" and i.field == "vendor" for i in result.issues)
    proposal.line_items.pop()
    fake = FakeProvider({"interpret_text": [proposal]})
    context = ModelContext(document, b"", proposal=proposal)
    assert Critique.model_validate(fake.critique(context).payload).issues[0].code == "OMITTED_SOURCE_ROW"
    result = execute(invoices[0], tmp_path, settings, fake)
    assert result.counters.revisions == 1
    assert result.counters.critic_runs == 2
    assert len(result.invoice.line_items) == 2


@pytest.mark.parametrize("scenario", ["repeated_revise", "malformed", "timeout", "disagreement"])
def test_bounded_paths(scenario, invoices, settings, tmp_path):
    script = {
        "repeated_revise": {"critique": [Critique(decision="revise")] * 20},
        "malformed": {"interpret_text": [{"wrong": True}] * 20, "pro": ["broken"]},
        "timeout": {"interpret_text": [TransportFailure("secret exception")] * 20},
        "disagreement": {"critique": [Critique(decision="review")] * 20},
    }[scenario]
    fake = FakeProvider(script)
    result = execute(invoices[0], tmp_path, settings, fake)
    assert result.counters.model_requests <= 7
    assert result.counters.graph_steps <= 14
    assert result.counters.revisions <= 1
    assert result.counters.pro_escalations <= 1
    if "pro" in fake.calls:
        assert fake.calls[-1] == "pro"
    if scenario == "timeout":
        assert result.status == "technical_failure"
        assert result.counters.model_requests == 2
    elif scenario == "malformed":
        assert result.status == "needs_review"
    else:
        assert result.status == "ready_for_validation"


@pytest.mark.parametrize("budget", [1, 2, 3, 4, 5, 6, 7])
def test_budget_with_retries(budget, invoices, settings, tmp_path):
    settings.limits.max_total_model_requests = budget
    fake = FakeProvider({"interpret_text": [TransportFailure()], "critique": [Critique(decision="revise")] * 4})
    result = execute(invoices[0], tmp_path, settings, fake)
    assert result.counters.model_requests <= budget
    assert result.counters.model_requests == len(fake.calls)
    if budget < 6:
        assert any(i.code == "INGESTION_BUDGET_EXHAUSTED" for i in result.issues)
    if budget >= 2:
        assert result.invoice is not None


@pytest.mark.parametrize("steps", [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14])
def test_step_budget(steps, invoices, settings, tmp_path):
    settings.limits.max_graph_steps = steps
    result = execute(invoices[0], tmp_path, settings, FakeProvider({"critique": [Critique(decision="revise")] * 4}))
    assert result.counters.graph_steps <= steps


def test_image_routing(image_pdf, settings, tmp_path):
    source, data = read_source(image_pdf, settings.documents)
    document = extract(source, data, settings.documents)
    assert not document.usable_text
    proposal = InvoiceProposal(invoice_number=ObservedField(literal="SCAN-001", confidence=1,
        evidence=[EvidenceLocator(page=1, bbox=(25, 25, 200, 50))]))
    fake = FakeProvider(visual_proposal=proposal)
    result = execute(image_pdf, tmp_path, settings, fake)
    assert fake.calls == ["interpret_visual", "critique"]
    assert result.status == "ready_for_validation"
    assert result.invoice.invoice_number.value == "SCAN-001"


def test_batch_isolation(invoices, tmp_path, settings):
    fake = FakeProvider({"interpret_text": [RuntimeError("private data")]})
    batch = run_pipeline([tmp_path / "absent.pdf", *invoices], settings=settings, provider=fake, runs_dir=tmp_path / "runs")
    assert [i.result.status for i in batch.results] == ["invalid_input", "technical_failure", "ready_for_validation", "ready_for_validation"]
    assert "private data" not in batch.model_dump_json()


def test_atomic_failure(tmp_path, monkeypatch):
    import invoice_system.ingestion.artifacts as artifacts
    path = tmp_path / "result.json"
    atomic_json(path, {"old": 1})
    def fail(*args):
        raise OSError("disk")
    monkeypatch.setattr(artifacts.os, "replace", fail)
    with pytest.raises(OSError):
        atomic_json(path, {"new": 2})
    assert json.loads(path.read_text()) == {"old": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_storage_failure_continues(invoices, settings, tmp_path, monkeypatch):
    import invoice_system.ingestion.workflow as workflow
    monkeypatch.setattr(workflow, "atomic_json", Mock(side_effect=OSError("disk")))
    batch = run_pipeline(invoices, settings=settings, provider=FakeProvider(), runs_dir=tmp_path / "runs")
    assert len(batch.results) == 3
    assert all(i.result.status == "technical_failure" and i.artifact is None for i in batch.results)


def test_shared_provider_contract(document, settings):
    proposal = fixture_proposal(document)
    client = Mock()
    client.models.generate_content.return_value = Mock(text=proposal.model_dump_json(), usage_metadata=None)
    gemini = GeminiProvider(settings, client=client)
    context = ModelContext(document, b"%PDF-test")
    for provider in (gemini, FakeProvider()):
        payload = provider.interpret_text(context).payload
        parsed = InvoiceProposal.model_validate(payload) if isinstance(payload, dict) else InvoiceProposal.model_validate_json(payload)
        assert parsed == proposal
    response = gemini.interpret_visual(context)
    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert contents[1].inline_data.data == b"%PDF-test"
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema is None
    assert json.dumps(_gemini_schema(InvoiceProposal.model_json_schema())) in contents[0]
    client.models.generate_content.return_value.text = '{"wrong": 1}'
    with pytest.raises(ValidationError):
        InvoiceProposal.model_validate_json(gemini.interpret_text(context).payload)


def test_config_env_and_validation(monkeypatch):
    monkeypatch.setenv("INGESTION_MODELS_FLASH_MODEL", "custom-flash")
    monkeypatch.setenv("INGESTION_LIMITS_MAX_TOTAL_MODEL_REQUESTS", "1")
    assert load_settings().models.flash_model == "custom-flash"
    assert load_settings().limits.max_total_model_requests == 1
    monkeypatch.setenv("INGESTION_LIMITS_MAX_FLASH_REVISIONS", "2")
    with pytest.raises(ValidationError):
        load_settings()


def test_encrypted_pdf(tmp_path, settings):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_encryption(owner_password="owner", user_password="reader")
    path = tmp_path / "encrypted.pdf"
    pdf.output(path)
    assert execute(path, tmp_path, settings, FakeProvider()).status == "invalid_input"


def test_inaccessible_pdf(invoices, tmp_path, settings, monkeypatch):
    original = Path.open
    def inaccessible(path, *args, **kwargs):
        if path == invoices[0]:
            raise PermissionError("blocked")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", inaccessible)
    assert execute(invoices[0], tmp_path, settings, FakeProvider()).status == "invalid_input"


def test_missing_key_is_not_offline_fallback(invoices, tmp_path, settings, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = execute(invoices[0], tmp_path, settings, None)
    assert result.status == "technical_failure"
    assert result.counters.model_requests == 0
    assert result.issues[0].code == "PROVIDER_UNAVAILABLE"


def test_gemini_retry_config(settings, monkeypatch):
    from google import genai
    factory = Mock()
    monkeypatch.setattr(genai, "Client", factory)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    GeminiProvider(settings)
    options = factory.call_args.kwargs["http_options"]
    assert options.retry_options.attempts == 1
    assert options.timeout == 45000


def test_gemini_pro_and_critic_contract(document, settings):
    proposal = fixture_proposal(document)
    client = Mock()
    client.models.generate_content.return_value = Mock(text=proposal.model_dump_json(), usage_metadata=None)
    gemini = GeminiProvider(settings, client=client)
    context = ModelContext(document, b"%PDF-original", proposal=proposal, adjudicate=True)
    assert InvoiceProposal.model_validate_json(gemini.interpret_visual(context).payload) == proposal
    assert client.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-pro"
    assert client.models.generate_content.call_args.kwargs["contents"][1].inline_data.data == context.pdf
    context.adjudicate = False
    client.models.generate_content.return_value.text = Critique(decision="accept").model_dump_json()
    for provider in (gemini, FakeProvider()):
        payload = provider.critique(context).payload
        value = Critique.model_validate_json(payload) if isinstance(payload, str) else Critique.model_validate(payload)
        assert value.decision == "accept"


def test_evidence_bounds(document):
    with pytest.raises(ValidationError):
        EvidenceLocator(page=0, bbox=(0, 0, 1, 1))
    with pytest.raises(ValidationError):
        EvidenceLocator(page=1, bbox=(0, 0, -1, 1))
    assert not valid_evidence("anything", [EvidenceLocator(page=2, bbox=(1, 1, 2, 2))], document, visual=True)
    assert not valid_evidence("anything", [EvidenceLocator(page=1, bbox=(1, 1, 9999, 9999))], document, visual=True)


def test_unknown_values_negative_quantity_repeated_rows(tmp_path, settings):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in ["Invoice: INV-UNKNOWN", "Vendor: UnknOwn Distributers", "Date: 2026-01-01",
                 "Mystery Product -2 $5.00 $-10.00", "Mystery Product -2 $5.00 $-10.00", "Total: $-20.00"]:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    path = tmp_path / "unknown.pdf"
    pdf.output(path)
    result = execute(path, tmp_path, settings, FakeProvider())
    assert result.status == "ready_for_validation"
    assert result.invoice.vendor.value == "UnknOwn Distributers"
    assert len(result.invoice.line_items) == 2
    for row in result.invoice.line_items:
        assert row.name.value == "Mystery Product"
        assert row.quantity.value == Decimal("-2")
        assert row.quantity.observed.literal == "-2"


def test_pro_recommendation_and_failure_are_terminal(invoices, tmp_path, settings):
    for response in (InvoiceProposal(recommend_review=True), TransportFailure("timeout")):
        fake = FakeProvider({"critique": [Critique(decision="review")], "pro": [response]})
        result = execute(invoices[0], tmp_path, settings, fake)
        assert result.status == ("technical_failure" if isinstance(response, Exception) else "needs_review")
        assert fake.calls == ["interpret_text", "critique", "pro"]


def test_proposals_and_critique_history_saved(invoices, tmp_path, settings, document):
    proposal = fixture_proposal(document)
    proposal.line_items.pop()
    result = execute(invoices[0], tmp_path, settings, FakeProvider({"interpret_text": [proposal]}))
    directory = tmp_path / "runs" / result.run_id
    assert len(json.loads((directory / "interpret-1.json").read_text())["line_items"]) == 1
    assert json.loads((directory / "critique-2.json").read_text())["issues"][0]["code"] == "OMITTED_SOURCE_ROW"
    assert len(json.loads((directory / "revise-3.json").read_text())["line_items"]) == 2


@pytest.mark.live
def test_live_gemini(invoices, tmp_path):
    settings = load_settings()
    batch = run_pipeline(invoices, settings=settings, runs_dir=tmp_path / "runs")
    assert batch.status == "completed"
    assert len(batch.results[2].result.invoice.line_items) == 8
