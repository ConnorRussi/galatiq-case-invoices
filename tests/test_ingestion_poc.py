from decimal import Decimal
from pathlib import Path

import pytest

from invoice_system.ingestion.ingest import ingest
from invoice_system.ingestion.models import DecimalField, EvidenceLocator, Invoice, LineItem, TextField
from invoice_system.ingestion.providers import ModelResponse


class FixedProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.contexts = []

    def interpret_text(self, context):
        self.calls += 1
        self.contexts.append(context)
        return ModelResponse(self.payload, {"prompt_tokens": 12})


def locator():
    return EvidenceLocator(page=1, block_id="line-1", word_ids=[0], bbox=[0, 0, 10, 10])


def invoice_payload():
    return Invoice(
        invoice_number=TextField(original="INV 1011", normalized="INV 1011", evidence=[locator()]),
        line_items=[LineItem(name=TextField(original="Widget A", normalized="Widget A", evidence=[locator()]), quantity=DecimalField(original="2", normalized=Decimal("2"), evidence=[locator()]))],
    ).model_dump(mode="json")


def test_poc_makes_one_model_call_preserves_model_values_and_writes_human_report(tmp_path):
    source = tmp_path / "invoice.txt"
    source.write_text("Invoice: INV 1011\nWidget A 2", encoding="utf-8")
    provider = FixedProvider(invoice_payload())

    batch = ingest([source], provider=provider, runs_dir=tmp_path / "runs")

    item = batch.results[0]
    assert provider.calls == 1
    assert item.result.status == "ready_for_validation"
    assert item.result.invoice.invoice_number.normalized == "INV 1011"
    assert item.result.invoice.line_items[0].name.normalized == "Widget A"
    report = (tmp_path / "runs" / item.result.run_id / "run-report.md").read_text(encoding="utf-8")
    assert "model extraction" in report
    assert "no business validation was performed" in report
    assert (tmp_path / "runs" / item.result.run_id / "extracted-text.txt").is_file()


@pytest.mark.parametrize("suffix, content", [
    (".txt", "Invoice: INV 1011"),
    (".json", '{"invoice": "INV 1011"}'),
    (".csv", "invoice,INV 1011"),
    (".xml", "<invoice>INV 1011</invoice>"),
])
def test_poc_keeps_supported_text_readers(tmp_path, suffix, content):
    source = tmp_path / f"invoice{suffix}"
    source.write_text(content, encoding="utf-8")
    provider = FixedProvider(invoice_payload())

    item = ingest([source], provider=provider, runs_dir=tmp_path / "runs").results[0]

    assert item.result.status == "ready_for_validation"
    assert provider.calls == 1


def test_poc_keeps_native_text_pdf_reader(tmp_path):
    source = Path("data/invoices/invoice_1011.pdf")
    provider = FixedProvider(invoice_payload())

    item = ingest([source], provider=provider, runs_dir=tmp_path / "runs").results[0]

    assert item.result.status == "ready_for_validation"
    assert "INVOICE" in provider.contexts[0].document.text


def test_poc_reports_unsupported_formats_for_humans(tmp_path):
    source = tmp_path / "invoice.docx"
    source.write_bytes(b"not an invoice")

    item = ingest([source], provider=FixedProvider(invoice_payload()), runs_dir=tmp_path / "runs").results[0]

    assert item.result.status == "invalid_input"
    report = (tmp_path / "runs" / item.result.run_id / "run-report.md").read_text(encoding="utf-8")
    assert "Expected an accessible PDF, TXT, JSON, CSV, or XML invoice" in report
