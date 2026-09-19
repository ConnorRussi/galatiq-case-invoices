"""Deterministic ingestion regression checks against hand-authored goldens."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .critic import critique
from .models import IngestionResult, IngestionStatus, NormalizationResult
from .run_logging import RunContext, make_evaluation_id, make_run_id, now_iso, write_artifact
from .runner import run_ingestion


SCALAR_FIELDS = (
    "invoice_number",
    "vendor",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax_rate",
    "tax_amount",
    "shipping",
    "discount",
    "invoice_total",
    "amount_due",
)


@dataclass
class EvalSection:
    name: str
    passed: bool = True
    messages: list[str] = field(default_factory=list)


@dataclass
class InvoiceEval:
    fixture: str
    sections: list[EvalSection]
    result: IngestionResult
    artifact_dir: Path

    @property
    def passed(self) -> bool:
        return all(section.passed for section in self.sections)


def run_evaluation(root: Path) -> bool:
    expected_dir = root / "evals" / "ingestion" / "expected"
    expected_files = sorted(expected_dir.glob("*.json"))
    if not expected_files:
        print("No ingestion expected files found.")
        return False

    evaluation_id = make_evaluation_id()
    evaluation_dir = root / "logs" / "evals" / evaluation_id
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    started_at = now_iso()

    invoice_results = [_evaluate_invoice(root, path, evaluation_dir) for path in expected_files]
    _print_invoice_results(invoice_results)

    accepted_results = [
        invoice_result.result
        for invoice_result in invoice_results
        if invoice_result.result.status == IngestionStatus.ACCEPT
        and invoice_result.result.normalization is not None
        and invoice_result.result.source_document is not None
    ]
    challenge_results = _run_critic_challenges(accepted_results[:1])
    _print_challenge_results(challenge_results)
    _print_summary(invoice_results)
    _write_summary(evaluation_dir, evaluation_id, started_at, now_iso(), invoice_results, challenge_results)
    print()
    print(f"Evaluation artifacts: {evaluation_dir}")
    return all(result.passed for result in invoice_results) and all(section.passed for section in challenge_results)


def _evaluate_invoice(root: Path, expected_path: Path, evaluation_dir: Path) -> InvoiceEval:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    fixture = expected["fixture"]
    invoice_path = root / "data" / "invoices" / fixture
    invoice_name = expected_path.stem
    artifact_dir = evaluation_dir / invoice_name
    result = run_ingestion(
        invoice_path,
        artifact_context=RunContext(run_id=make_run_id(invoice_path), run_dir=artifact_dir),
    )
    sections = [
        _status_section(result, expected),
        _common_fields_section(result, expected),
        _line_items_section(result, expected),
        _additional_fields_section(result, expected),
        _evidence_section(result),
    ]
    invoice_eval = InvoiceEval(fixture=fixture, sections=sections, result=result, artifact_dir=artifact_dir)
    write_artifact(artifact_dir, "evaluation.json", _evaluation_payload(invoice_eval))
    return invoice_eval


def _status_section(result: IngestionResult, expected: dict[str, Any]) -> EvalSection:
    expected_status = expected.get("expected_status", IngestionStatus.ACCEPT.value)
    section = EvalSection("status", result.status.value == expected_status)
    if not section.passed:
        section.messages.append(f"expected: {expected_status!r}; actual: {result.status.value!r}")
        if result.error_message:
            section.messages.append(f"error: {result.error_message}")
    return section


def _common_fields_section(result: IngestionResult, expected: dict[str, Any]) -> EvalSection:
    section = EvalSection("common_fields")
    invoice = _invoice_dict(result)
    for field_name in SCALAR_FIELDS:
        if field_name not in expected:
            continue
        _compare_value(section, field_name, expected[field_name], invoice.get(field_name))
    return section


def _line_items_section(result: IngestionResult, expected: dict[str, Any]) -> EvalSection:
    section = EvalSection("line_items")
    invoice = _invoice_dict(result)
    actual_items = invoice.get("items", [])
    expected_items = expected.get("items", [])
    if len(actual_items) != len(expected_items):
        section.passed = False
        section.messages.append(f"item count expected: {len(expected_items)}; actual: {len(actual_items)}")
    for index, expected_item in enumerate(expected_items):
        if index >= len(actual_items):
            break
        actual_item = actual_items[index]
        for field_name in ("item_name", "quantity", "unit_price", "line_amount"):
            if field_name in expected_item:
                _compare_value(section, f"items[{index}].{field_name}", expected_item[field_name], actual_item.get(field_name))
        for key, expected_value in expected_item.get("additional_fields", {}).items():
            _compare_value(
                section,
                f"items[{index}].additional_fields.{key}",
                expected_value,
                actual_item.get("additional_fields", {}).get(key),
            )
    return section


def _additional_fields_section(result: IngestionResult, expected: dict[str, Any]) -> EvalSection:
    section = EvalSection("additional_fields")
    actual = _invoice_dict(result).get("additional_fields", {})
    for key, expected_value in expected.get("additional_fields", {}).items():
        _compare_value(section, f"additional_fields.{key}", expected_value, actual.get(key))
    return section


def _evidence_section(result: IngestionResult) -> EvalSection:
    section = EvalSection("evidence")
    if result.normalization is None:
        section.passed = False
        section.messages.append("no normalization to evaluate")
        return section
    if result.source_document is None:
        section.passed = False
        section.messages.append("no source document to evaluate")
        return section
    chunks = {chunk.id: chunk.text for chunk in result.source_document.chunks}
    source_text_by_id = {chunk_id: _squash(text) for chunk_id, text in chunks.items()}
    field_paths = set(_populated_field_paths(result.normalization))
    evidence_by_path = {evidence.field_path: evidence for evidence in result.normalization.evidence}
    if len(evidence_by_path) != len(result.normalization.evidence):
        section.passed = False
        section.messages.append("duplicate evidence field paths")
    for field_path in sorted(field_paths):
        evidence = evidence_by_path.get(field_path)
        # USD is an authorized use-case assumption. If a quotation is supplied,
        # still validate it; the exception must not legitimize fabricated quotes.
        if field_path == "currency" and result.normalization.invoice.currency == "USD" and evidence is None:
            continue
        if evidence is None:
            section.passed = False
            section.messages.append(f"{field_path}: missing evidence")
            continue
        missing_chunks = [chunk_id for chunk_id in evidence.source_chunk_ids if chunk_id not in chunks]
        if not evidence.source_chunk_ids:
            section.passed = False
            section.messages.append(f"{field_path}: no source chunk ids")
        if missing_chunks:
            section.passed = False
            section.messages.append(f"{field_path}: unknown chunk ids {missing_chunks}")
        if evidence.source_text:
            quoted = _squash(evidence.source_text)
            # A pair of display quotes is not part of the claim (e.g. "6%").
            if len(quoted) >= 2 and quoted[0] == quoted[-1] and quoted[0] in {'"', "'"}:
                quoted = quoted[1:-1].strip()
            if quoted and not any(quoted in source_text_by_id.get(chunk_id, "") for chunk_id in evidence.source_chunk_ids):
                section.passed = False
                section.messages.append(f"{field_path}: source_text not found in referenced chunks")
    return section


def _run_critic_challenges(results: list[IngestionResult]) -> list[EvalSection]:
    if not results:
        return [EvalSection("critic_challenges", False, ["no accepted live result available for critic challenges"])]
    result = results[0]
    assert result.source_document is not None and result.normalization is not None
    cases = [
        ("faithful_candidate", lambda n: None, None),
        ("equivalent_decimal_representation", _rescale_decimals, None),
        ("wrong_value", lambda n: _set_invoice_value(n, "invoice_total", "999999"), "invoice_total"),
        ("missing_material_field", _remove_payment_terms, "payment_terms"),
        ("canonicalized_item_name", _canonicalize_first_spaced_item_name, None),
        ("correct_bad_source_data", _flip_negative_quantity, "quantity"),
    ]
    sections = []
    for name, mutate, expected_hint in cases:
        changed = result.normalization.model_copy(deep=True)
        mutate(changed)
        try:
            critic_result = critique(result.source_document, changed)
            matched = (
                not critic_result.issues if expected_hint is None else
                any((issue.field_path or "").endswith(expected_hint) or expected_hint in issue.message for issue in critic_result.issues)
            )
            section = EvalSection(name, matched)
            if not matched:
                section.messages.append(
                    f"expected {'no issues' if expected_hint is None else expected_hint!r}; issues: {len(critic_result.issues)}"
                )
        except Exception as exc:
            section = EvalSection(name, False, [f"critic call failed: {exc}"])
        sections.append(section)
    return sections


def _rescale_decimals(normalization: NormalizationResult) -> None:
    # Add a trailing zero without rounding or using the Decimal context.
    for model in [normalization.invoice, *normalization.invoice.items]:
        for name in type(model).model_fields:
            value = getattr(model, name)
            if isinstance(value, Decimal) and value.is_finite():
                parts = value.as_tuple()
                setattr(model, name, Decimal((parts.sign, parts.digits + (0,), parts.exponent - 1)))


def _set_invoice_value(normalization: NormalizationResult, field_name: str, value: Any) -> None:
    setattr(normalization.invoice, field_name, Decimal(str(value)))


def _remove_payment_terms(normalization: NormalizationResult) -> None:
    normalization.invoice.additional_fields.pop("payment_terms", None)
    normalization.invoice.additional_fields.pop("terms", None)


def _canonicalize_first_spaced_item_name(normalization: NormalizationResult) -> None:
    for item in normalization.invoice.items:
        if item.item_name and " " in item.item_name:
            item.item_name = item.item_name.replace(" ", "")
            return
    if normalization.invoice.items:
        normalization.invoice.items[0].item_name = (normalization.invoice.items[0].item_name or "") + "X"


def _flip_negative_quantity(normalization: NormalizationResult) -> None:
    for item in normalization.invoice.items:
        if item.quantity is not None and Decimal(item.quantity) < 0:
            item.quantity = abs(item.quantity)
            return
    if normalization.invoice.items:
        normalization.invoice.items[0].quantity = Decimal("999")


def _invoice_dict(result: IngestionResult) -> dict[str, Any]:
    if result.normalization is None:
        return {}
    return result.normalization.invoice.model_dump(mode="json")


def _compare_value(section: EvalSection, label: str, expected: Any, actual: Any) -> None:
    if not _values_equal(expected, actual):
        section.passed = False
        section.messages.append(f"{label} expected: {expected!r}; actual: {actual!r}")


def _values_equal(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is actual
    if isinstance(expected, (int, float, str)) and isinstance(actual, (int, float, str)):
        try:
            return Decimal(str(expected)) == Decimal(str(actual))
        except Exception:
            return str(expected) == str(actual)
    return expected == actual


def _populated_field_paths(normalization: NormalizationResult) -> list[str]:
    invoice = normalization.invoice
    paths = []
    for field_name, value in invoice.model_dump(mode="json").items():
        if field_name in {"items", "additional_fields"}:
            continue
        if _populated(value):
            paths.append(field_name)
    for key, value in invoice.additional_fields.items():
        if _populated(value):
            paths.append(f"additional_fields.{key}")
    for index, item in enumerate(invoice.items):
        item_data = item.model_dump(mode="json")
        for field_name, value in item_data.items():
            if field_name == "additional_fields":
                continue
            if _populated(value):
                paths.append(f"items[{index}].{field_name}")
        for key, value in item.additional_fields.items():
            if _populated(value):
                paths.append(f"items[{index}].additional_fields.{key}")
    return paths


def _populated(value: Any) -> bool:
    return value is not None and value != ""


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _evaluation_payload(result: InvoiceEval) -> dict[str, Any]:
    return {
        "fixture": result.fixture,
        "passed": result.passed,
        "status": result.result.status.value,
        "failure_count": _failure_count(result),
        "sections": [
            {
                "name": section.name,
                "passed": section.passed,
                "messages": section.messages,
            }
            for section in result.sections
        ],
    }


def _write_summary(
    evaluation_dir: Path,
    evaluation_id: str,
    started_at: str,
    completed_at: str,
    invoice_results: list[InvoiceEval],
    challenge_results: list[EvalSection],
) -> None:
    passed = sum(1 for result in invoice_results if result.passed)
    technical_failures = sum(1 for result in invoice_results if result.result.status == IngestionStatus.TECHNICAL_FAILURE)
    write_artifact(
        evaluation_dir,
        "summary.json",
        {
            "evaluation_id": evaluation_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "total": len(invoice_results),
            "passed": passed,
            "failed": len(invoice_results) - passed,
            "technical_failures": technical_failures,
            "cases": [
                {
                    "invoice": Path(result.fixture).stem,
                    "fixture": result.fixture,
                    "passed": result.passed,
                    "status": result.result.status.value,
                    "failure_count": _failure_count(result),
                    "artifact_dir": result.artifact_dir.name,
                }
                for result in invoice_results
            ],
            "critic_challenges": [
                {
                    "name": section.name,
                    "passed": section.passed,
                    "messages": section.messages,
                }
                for section in challenge_results
            ],
        },
    )


def _failure_count(result: InvoiceEval) -> int:
    return sum(len(section.messages) if section.messages else int(not section.passed) for section in result.sections if not section.passed)


def _print_invoice_results(results: list[InvoiceEval]) -> None:
    print("INGESTION EVALUATION")
    print()
    for result in results:
        print(result.fixture)
        for section in result.sections:
            print(f"  {section.name:<20} {'PASS' if section.passed else 'FAIL'}")
            for message in section.messages:
                print(f"    - {message}")
        print(f"  {'overall':<20} {'PASS' if result.passed else 'FAIL'}")
        print()


def _print_challenge_results(sections: list[EvalSection]) -> None:
    print("CRITIC CHALLENGES")
    for section in sections:
        print(f"  {section.name:<24} {'PASS' if section.passed else 'FAIL'}")
        for message in section.messages:
            print(f"    - {message}")
    print()


def _print_summary(results: list[InvoiceEval]) -> None:
    passed = sum(1 for result in results if result.passed)
    technical_failures = sum(1 for result in results if result.result.status == IngestionStatus.TECHNICAL_FAILURE)
    field_sections = [section for result in results for section in result.sections if section.name == "common_fields"]
    line_sections = [section for result in results for section in result.sections if section.name == "line_items"]
    evidence_sections = [section for result in results for section in result.sections if section.name == "evidence"]
    print("SUMMARY")
    print(f"Invoices: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {len(results) - passed}")
    print(f"Common field accuracy: {_rate(field_sections):.1f}%")
    print(f"Line item accuracy: {_rate(line_sections):.1f}%")
    print(f"Evidence validity: {_rate(evidence_sections):.1f}%")
    print(f"Technical failures: {technical_failures}")


def _rate(sections: list[EvalSection]) -> float:
    if not sections:
        return 0.0
    return 100.0 * sum(1 for section in sections if section.passed) / len(sections)
