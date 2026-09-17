from __future__ import annotations

from types import SimpleNamespace

from invoice_system.ingestion.evaluation import (
    load_manifest,
    overall_exact_match,
    parity_match,
)


def test_manifest_contains_every_invoice_artifact():
    examples = load_manifest()
    assert len(examples) == 20
    assert len({example["inputs"]["artifact"] for example in examples}) == 20


def test_overall_evaluator_reports_exact_match():
    expected = load_manifest()[0]["outputs"]
    run = SimpleNamespace(outputs={**expected, "evidence_present": True})
    example = SimpleNamespace(outputs=expected)
    assert overall_exact_match(run, example)["score"] == 1


def test_overall_evaluator_reports_field_diff():
    expected = load_manifest()[0]["outputs"]
    actual = {**expected, "invoice": {**expected["invoice"], "vendor": "Wrong"}}
    score = overall_exact_match(
        SimpleNamespace(outputs=actual), SimpleNamespace(outputs=expected)
    )
    assert score["score"] == 0
    assert "vendor" in score["comment"]


def test_parity_evaluator_accepts_identical_representations():
    invoice = load_manifest()[10]["outputs"]["invoice"]
    inputs = [
        {"artifact": "data/invoices/invoice_1011.txt"},
        {"artifact": "data/invoices/invoice_1011.pdf"},
        {"artifact": "data/invoices/invoice_1012.txt"},
        {"artifact": "data/invoices/invoice_1012.pdf"},
        {"artifact": "data/invoices/invoice_1013.json"},
        {"artifact": "data/invoices/invoice_1013.pdf"},
    ]
    outputs = [{"invoice": invoice} for _ in inputs]
    assert parity_match(inputs, outputs)["score"] == 1
