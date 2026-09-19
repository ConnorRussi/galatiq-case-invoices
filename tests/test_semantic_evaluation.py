import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from invoice_system.ingestion.models import IngestionResult, NormalizationResult, NormalizedInvoice
from invoice_system.validation import evaluation
from invoice_system.validation.models import (
    CriticDecision,
    CriticResult,
    ReconciliationResult,
    ReconciliationStatus,
    SemanticResult,
    SemanticStatus,
    ValidationResult,
    ValidationStage,
    ValidationStatus,
)


def _ingestion() -> IngestionResult:
    return IngestionResult(
        status="accept",
        source_path="test.json",
        normalization=NormalizationResult(
            invoice=NormalizedInvoice(
                invoice_date=date(2026, 9, 1),
                due_date=date(2026, 9, 15),
                items=[{"item_name": "Widget", "quantity": Decimal("2")}],
            ),
            evidence=[],
        ),
    )


def _result(status: SemanticStatus, issues: list[dict] | None = None) -> ValidationResult:
    semantic = SemanticResult(status=status, issues=issues or [], summary="complete")
    critic = CriticResult(decision=CriticDecision.AGREE, summary="confirmed")
    return ValidationResult(
        status=ValidationStatus.VALID if status == SemanticStatus.PASS else ValidationStatus.DENIED,
        reason="semantic_pass" if status == SemanticStatus.PASS else "semantic_denied",
        denied_by=ValidationStage.SEMANTIC if status == SemanticStatus.DENY else None,
        issues=semantic.issues,
        semantic_result=semantic,
        critic_result=critic,
        ingestion=_ingestion(),
    )


def test_pass_expectation_and_actual_pass_score_correctly():
    metrics = evaluation.score_semantic_result(
        {"semantic": {"expected_status": "PASS", "expected_issues": []}},
        _result(SemanticStatus.PASS),
    )

    assert metrics.status_match
    assert metrics.expected_issue_code_coverage
    assert metrics.expected_issue_field_coverage
    assert metrics.unexpected_blocking_issue_count == 0
    assert metrics.overall_semantic_match


def test_deny_expectation_and_matching_issue_score_correctly():
    metrics = evaluation.score_semantic_result(
        {
            "semantic": {
                "expected_status": "DENY",
                "expected_issues": [{"code": "negative_quantity", "field": "items[0].quantity"}],
                "expected_denial_stage": "semantic",
            }
        },
        _result(
            SemanticStatus.DENY,
            [{"code": "negative_quantity", "field": "items[0].quantity", "message": "invalid"}],
        ),
    )

    assert metrics.status_match
    assert metrics.expected_issue_code_coverage
    assert metrics.expected_issue_field_coverage
    assert metrics.denial_stage_match
    assert metrics.overall_semantic_match


def test_status_mismatch_is_surfaced():
    metrics = evaluation.score_semantic_result(
        {"semantic": {"expected_status": "DENY", "expected_issues": []}},
        _result(SemanticStatus.PASS),
    )

    assert not metrics.status_match
    assert not metrics.overall_semantic_match


def test_missing_expected_issue_is_surfaced():
    metrics = evaluation.score_semantic_result(
        {
            "semantic": {
                "expected_status": "DENY",
                "expected_issues": [{"code": "negative_quantity", "field": "items[0].quantity"}],
            }
        },
        _result(SemanticStatus.DENY),
    )

    assert not metrics.expected_issue_code_coverage
    assert not metrics.expected_issue_field_coverage
    assert not metrics.overall_semantic_match


def test_unexpected_blocking_issue_is_surfaced():
    metrics = evaluation.score_semantic_result(
        {"semantic": {"expected_status": "PASS", "expected_issues": []}},
        _result(
            SemanticStatus.PASS,
            [{"code": "inventory_shortage", "field": "items[0].quantity", "message": "outside stage"}],
        ),
    )

    assert metrics.unexpected_blocking_issue_count == 1
    assert not metrics.overall_semantic_match


def test_critic_revision_count_is_captured():
    metrics = evaluation.score_semantic_result(
        {"semantic": {"expected_status": "PASS", "expected_issues": []}},
        _result(SemanticStatus.PASS),
        critic_revision_count=2,
    )

    assert metrics.critic_revision_count == 2


def test_one_bad_case_does_not_stop_the_remaining_suite(tmp_path, monkeypatch):
    expected_dir = tmp_path / "evals" / "validation" / "semantic" / "expected"
    fixture_dir = tmp_path / "evals" / "validation" / "semantic" / "fixtures"
    expected_dir.mkdir(parents=True)
    fixture_dir.mkdir(parents=True)
    fixture = {
        "status": "accept",
        "source_path": "valid-fixture",
        "normalization": {"invoice": {"items": []}, "evidence": []},
    }
    (fixture_dir / "valid.json").write_text(json.dumps(fixture), encoding="utf-8")
    for name, status in (("a_bad", "DENY"), ("b_good", "PASS")):
        (expected_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "invoice_id": name,
                    "input": {"kind": "semantic_fixture", "path": "valid.json"},
                    "semantic": {"expected_status": status, "expected_issues": []},
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(evaluation, "run_validation", lambda *args, **kwargs: _result(SemanticStatus.PASS))

    assert not evaluation.run_semantic_evaluation(tmp_path)
    summary_files = list((tmp_path / "logs" / "evals").glob("*/summary.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary["total"] == 2
    assert {case["case_id"] for case in summary["cases"]} == {"a_bad", "b_good"}


def test_semantic_eval_does_not_mutate_ingestion_golden(tmp_path, monkeypatch):
    source_root = Path(__file__).resolve().parents[1]
    expected_source = source_root / "evals" / "ingestion" / "expected" / "invoice_1001.json"
    golden_text = expected_source.read_text(encoding="utf-8")
    expected_dir = tmp_path / "evals" / "validation" / "semantic" / "expected"
    ingestion_dir = tmp_path / "evals" / "ingestion" / "expected"
    expected_dir.mkdir(parents=True)
    ingestion_dir.mkdir(parents=True)
    (ingestion_dir / expected_source.name).write_text(golden_text, encoding="utf-8")
    (expected_dir / "invoice_1001.json").write_text(
        json.dumps(
            {
                "invoice_id": "invoice_1001",
                "input": {"kind": "ingestion_golden", "path": "invoice_1001.json"},
                "semantic": {"expected_status": "PASS", "expected_issues": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(evaluation, "run_validation", lambda *args, **kwargs: _result(SemanticStatus.PASS))

    assert evaluation.run_semantic_evaluation(tmp_path)
    assert expected_source.read_text(encoding="utf-8") == golden_text
    assert (ingestion_dir / expected_source.name).read_text(encoding="utf-8") == golden_text


def test_validation_eval_routes_semantic_deny_and_pass_cases_through_one_pipeline(tmp_path, monkeypatch):
    expected_dir = tmp_path / "evals" / "validation" / "semantic" / "expected"
    fixture_dir = tmp_path / "evals" / "validation" / "semantic" / "fixtures"
    expected_dir.mkdir(parents=True)
    fixture_dir.mkdir(parents=True)
    fixture = {
        "status": "accept",
        "source_path": "controlled-validation-fixture",
        "normalization": {"invoice": {"items": [{"item_name": "Gadget A", "quantity": "5", "unit_price": "10", "line_amount": "50"}], "subtotal": "50", "invoice_total": "50"}, "evidence": []},
    }
    (fixture_dir / "valid.json").write_text(json.dumps(fixture), encoding="utf-8")
    deny_fixture = dict(fixture)
    deny_fixture["source_path"] = "controlled-semantic-deny"
    (fixture_dir / "deny.json").write_text(json.dumps(deny_fixture), encoding="utf-8")
    (expected_dir / "semantic_deny.json").write_text(json.dumps({
        "invoice_id": "semantic_deny",
        "input": {"kind": "semantic_fixture", "path": "deny.json"},
        "semantic": {"expected_status": "DENY", "expected_issues": [{"code": "relative_date", "field": "due_date"}], "expected_denial_stage": "semantic"},
    }), encoding="utf-8")
    (expected_dir / "semantic_pass.json").write_text(json.dumps({
        "invoice_id": "semantic_pass",
        "input": {"kind": "semantic_fixture", "path": "valid.json"},
        "semantic": {"expected_status": "PASS", "expected_issues": []},
        "reconciliation": {"expected_status": "PASS", "expected_issue_codes": [], "expected_consolidated_items": [{"product_name": "Gadget A", "expected_quantity": "5", "expected_source_lines": [1], "expected_derived_line_total": "50"}]},
    }), encoding="utf-8")

    def fake_run_validation(ingestion, **kwargs):
        is_deny = ingestion.source_path == "controlled-semantic-deny"
        semantic_status = SemanticStatus.DENY if is_deny else SemanticStatus.PASS
        semantic_issues = [{"code": "relative_date", "field": "due_date", "message": "relative"}] if semantic_status == SemanticStatus.DENY else []
        semantic = SemanticResult(status=semantic_status, issues=semantic_issues, summary="semantic")
        semantic_critic = CriticResult(decision=CriticDecision.AGREE, summary="semantic critic")
        reconciliation = None if semantic_status == SemanticStatus.DENY else ReconciliationResult(
            status=ReconciliationStatus.PASS,
            summary="reconciliation",
            consolidated_items=[{"product_name": "Gadget A", "normalized_product": "gadget a", "combined_quantity": "5", "source_lines": [1], "unit_price": "10", "derived_line_total": "50"}],
        )
        reconciliation_critic = None if reconciliation is None else CriticResult(decision=CriticDecision.AGREE, summary="reconciliation critic")
        return ValidationResult(
            status=ValidationStatus.DENIED if semantic_status == SemanticStatus.DENY else ValidationStatus.VALID,
            reason="semantic_denied" if semantic_status == SemanticStatus.DENY else "reconciliation_pass",
            denied_by=ValidationStage.SEMANTIC if semantic_status == SemanticStatus.DENY else None,
            issues=semantic.issues if reconciliation is None else reconciliation.issues,
            semantic_result=semantic,
            critic_result=semantic_critic if reconciliation is None else reconciliation_critic,
            ingestion=ingestion,
            semantic_critic_result=semantic_critic,
            reconciliation_result=reconciliation,
            reconciliation_critic_result=reconciliation_critic,
        )

    monkeypatch.setattr(evaluation, "run_validation", fake_run_validation)

    assert evaluation.run_validation_evaluation(tmp_path)
    summaries = list((tmp_path / "logs" / "evals").glob("*/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["passed"] == 2
    assert summary["semantic_denied"] == ["semantic_deny"]
    assert summary["reconciliation_denied"] == []
