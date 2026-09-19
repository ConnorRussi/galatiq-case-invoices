import json
from decimal import Decimal

from invoice_system.ingestion.models import IngestionResult, NormalizationResult
from invoice_system.validation import runner
from invoice_system.validation import critic as critic_module
from invoice_system.validation import reconciliation_evaluation as evaluation
from invoice_system.validation import reconciliation_runner as reconciliation_runner_module
from invoice_system.validation import graph as graph_module
from invoice_system.validation.models import (
    CriticDecision,
    CriticResult,
    ReconciliationResult,
    ReconciliationStatus,
    SemanticResult,
    SemanticStatus,
    ValidationStage,
    ValidationStatus,
)


def ingestion(items, **invoice_fields):
    return IngestionResult(
        status="accept",
        source_path="controlled.json",
        normalization=NormalizationResult(invoice={"items": items, **invoice_fields}, evidence=[]),
    )


def critic(decision=CriticDecision.AGREE):
    return CriticResult(decision=decision, summary="review complete")


def recon(status=ReconciliationStatus.PASS, issues=None, items=None):
    return ReconciliationResult(
        status=status,
        issues=issues or [],
        summary="reconciliation complete",
        consolidated_items=items or [],
    )


def test_reconciliation_critic_receives_decimal_evidence(monkeypatch):
    captured = {}

    def fake_invoke(**kwargs):
        captured.update(json.loads(kwargs["content"]))
        return kwargs["output_model"].model_validate({"decision": "AGREE", "summary": "consistent"})

    monkeypatch.setattr(critic_module, "invoke_structured", fake_invoke)
    result = critic_module.review_stage(
        ingestion([{"item_name": "Gadget A", "quantity": "8", "unit_price": "10", "line_amount": "80"}], subtotal="80", tax_amount="0", invoice_total="80"),
        ValidationStage.RECONCILIATION,
        recon(),
    )

    assert result.decision == CriticDecision.AGREE
    assert captured["arithmetic_tool_output"]["calculated_subtotal"] == "80"


def test_reconciliation_runner_reports_specialist_and_critic_progress(monkeypatch):
    progress: list[str] = []
    monkeypatch.setattr(
        reconciliation_runner_module,
        "validate_reconciliation",
        lambda *args, **kwargs: recon(),
    )
    monkeypatch.setattr(
        reconciliation_runner_module,
        "review_stage",
        lambda *args, **kwargs: critic(),
    )

    execution = reconciliation_runner_module.run_reconciliation(
        ingestion([{"item_name": "Gadget A", "quantity": "1", "unit_price": "2", "line_amount": "2"}]),
        persist_artifacts=False,
        progress_callback=progress.append,
    )

    assert execution.critic_confirmed
    assert progress == [
        "specialist attempt 1/3 started",
        "specialist attempt 1 proposed PASS with 0 issue(s)",
        "critic attempt 1: AGREE (revision count 0)",
    ]


def test_semantic_deny_short_circuits_reconciliation(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_module, "validate_semantics", lambda *a, **k: SemanticResult(status=SemanticStatus.DENY, issues=[], summary="semantic deny"))

    def review(*args, **kwargs):
        calls.append(args[1])
        return critic()

    monkeypatch.setattr(graph_module, "review_stage", review)
    monkeypatch.setattr(graph_module, "validate_reconciliation", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconciliation ran")))

    result = runner.run_validation(ingestion([]), persist_artifacts=False, run_reconciliation=True)

    assert result.status == ValidationStatus.DENIED
    assert result.denied_by == ValidationStage.SEMANTIC
    assert calls == [ValidationStage.SEMANTIC]
    assert result.reconciliation_result is None


def test_semantic_pass_runs_reconciliation_and_reconciliation_deny_finalizes(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_module, "validate_semantics", lambda *a, **k: SemanticResult(status=SemanticStatus.PASS, issues=[], summary="semantic pass"))
    monkeypatch.setattr(graph_module, "validate_reconciliation", lambda *a, **k: recon(ReconciliationStatus.DENY, [{"code": "SUBTOTAL_MISMATCH", "field": "subtotal", "message": "wrong subtotal"}]))

    def review(*args, **kwargs):
        calls.append(args[1])
        return critic()

    monkeypatch.setattr(graph_module, "review_stage", review)
    result = runner.run_validation(ingestion([]), persist_artifacts=False, run_reconciliation=True)

    assert result.status == ValidationStatus.DENIED
    assert result.denied_by == ValidationStage.RECONCILIATION
    assert result.reason == "reconciliation_denied"
    assert calls == [ValidationStage.SEMANTIC, ValidationStage.RECONCILIATION]


def test_full_graph_validates_both_stages(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_module, "validate_semantics", lambda *a, **k: SemanticResult(status=SemanticStatus.PASS, issues=[], summary="semantic pass"))
    monkeypatch.setattr(graph_module, "validate_reconciliation", lambda *a, **k: recon())

    def review(*args, **kwargs):
        calls.append(args[1])
        return critic()

    monkeypatch.setattr(graph_module, "review_stage", review)
    result = runner.run_validation(ingestion([]), persist_artifacts=False, run_reconciliation=True)

    assert result.status == ValidationStatus.VALID
    assert result.reason == "reconciliation_pass"
    assert result.semantic_critic_result is not None
    assert result.reconciliation_critic_result is not None
    assert calls == [ValidationStage.SEMANTIC, ValidationStage.RECONCILIATION]


def test_reconciliation_scoring_uses_structured_metrics_not_prose():
    actual = recon(
        ReconciliationStatus.DENY,
        [{"code": "SUBTOTAL_MISMATCH", "field": "subtotal", "message": "any wording"}],
        [],
    )
    metrics = evaluation.score_reconciliation_result(
        {"reconciliation": {"expected_status": "DENY", "expected_issue_codes": ["SUBTOTAL_MISMATCH"], "expected_issue_fields": ["subtotal"]}},
        actual,
        critic_completion=True,
    )

    assert metrics.status_match
    assert metrics.expected_issue_code_coverage
    assert metrics.expected_issue_field_coverage
    assert metrics.overall_reconciliation_match


def test_reconciliation_issue_code_without_field_accepts_structured_location():
    actual = recon(
        ReconciliationStatus.DENY,
        [{"code": "LINE_TOTAL_MISMATCH", "field": "items[0].line_amount", "message": "different wording"}],
    )

    metrics = evaluation.score_reconciliation_result(
        {"reconciliation": {"expected_status": "DENY", "expected_issue_codes": ["LINE_TOTAL_MISMATCH"]}},
        actual,
    )

    assert metrics.expected_issue_code_coverage
    assert metrics.unexpected_blocking_issue_count == 0
    assert metrics.overall_reconciliation_match


def test_reconciliation_consolidation_accuracy_rejects_unexpected_products():
    actual = recon(
        ReconciliationStatus.PASS,
        items=[
            {
                "product_name": "Gadget A",
                "normalized_product": "gadget a",
                "combined_quantity": "8",
                "source_lines": [1, 2],
                "unit_price": "10",
                "derived_line_total": "80",
            },
            {
                "product_name": "Unexpected",
                "normalized_product": "unexpected",
                "combined_quantity": "1",
                "source_lines": [3],
                "unit_price": "1",
                "derived_line_total": "1",
            },
        ],
    )

    metrics = evaluation.score_reconciliation_result(
        {
            "reconciliation": {
                "expected_status": "PASS",
                "expected_consolidated_items": [
                    {"product_name": "Gadget A", "expected_quantity": "8", "expected_source_lines": [1, 2]}
                ],
            }
        },
        actual,
    )

    assert not metrics.consolidation_accuracy
    assert not metrics.overall_reconciliation_match
