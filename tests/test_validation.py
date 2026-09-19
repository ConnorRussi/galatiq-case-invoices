import json
from datetime import date
from decimal import Decimal
import pytest

from invoice_system.ingestion.models import (
    IngestionResult,
    NormalizationResult,
    NormalizedInvoice,
)
from invoice_system.validation import runner
from invoice_system.validation import critic as critic_module
from invoice_system.validation import graph as graph_module
from invoice_system.validation import semantic as semantic_module
from invoice_system.validation.models import (
    CriticDecision,
    CriticResult,
    SemanticResult,
    SemanticStatus,
    ValidationStatus,
)


def ingestion(invoice: NormalizedInvoice | dict) -> IngestionResult:
    return IngestionResult(
        status="accept",
        source_path="test.json",
        normalization=NormalizationResult(invoice=invoice, evidence=[]),
    )


def semantic_result(status: SemanticStatus, *issues: dict) -> SemanticResult:
    return SemanticResult(
        status=status,
        issues=list(issues),
        summary="semantic review complete",
    )


def critic_result(decision: CriticDecision, **kwargs) -> CriticResult:
    return CriticResult(
        decision=decision,
        summary="critic review complete",
        **kwargs,
    )


def test_valid_invoice_passes_and_critic_agrees(monkeypatch):
    original = ingestion(
        {
            "invoice_date": date(2026, 9, 1),
            "due_date": date(2026, 9, 15),
            "items": [{"item_name": "Widget", "quantity": Decimal("2")}],
        }
    )
    before = original.model_dump(mode="json")
    monkeypatch.setattr(
        graph_module,
        "validate_semantics",
        lambda *args, **kwargs: semantic_result(SemanticStatus.PASS),
    )
    monkeypatch.setattr(
        graph_module,
        "review_stage",
        lambda *args, **kwargs: critic_result(CriticDecision.AGREE),
    )

    result = runner.run_validation(original, persist_artifacts=False)

    assert result.status == ValidationStatus.VALID
    assert result.reason == "semantic_pass"
    assert original.model_dump(mode="json") == before


def test_technical_ingestion_failure_cannot_enter_validation():
    original = ingestion({"items": [{"quantity": Decimal("2")}]})
    original.status = "technical_failure"

    with pytest.raises(ValueError, match="accepted or reviewable ingestion"):
        runner.run_validation(original, persist_artifacts=False)


def test_validation_graph_failure_returns_structured_technical_result(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("2")}]})

    class FailingGraph:
        def stream(self, state, stream_mode):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(runner, "build_graph", lambda **kwargs: FailingGraph())

    result = runner.run_validation(original, persist_artifacts=False)

    assert result.status == ValidationStatus.TECHNICAL_FAILURE
    assert result.reason == "technical_failure"
    assert result.error_message == "provider unavailable"


def test_future_invoice_date_is_not_a_semantic_blocker(monkeypatch):
    original = ingestion(
        {
            "invoice_date": date(2099, 1, 15),
            "due_date": date(2099, 2, 15),
            "items": [{"item_name": "Future Widget", "quantity": Decimal("2")}],
        }
    )
    captured: dict[str, str] = {}

    def fake_invoke(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return kwargs["output_model"].model_validate(
            {"stage": "semantic", "status": "PASS", "issues": [], "summary": "Dates are internally consistent."}
        )

    monkeypatch.setattr(semantic_module, "invoke_structured", fake_invoke)
    result = semantic_module.validate_semantics(original)

    assert result.status == SemanticStatus.PASS
    assert "future invoice date is NOT by itself a Phase 1 semantic error" in captured["system_prompt"]
    assert "model knowledge" in captured["system_prompt"]


def test_relative_date_is_denied_by_semantic_result(monkeypatch):
    original = ingestion({"additional_fields": {"due_date_raw": "yesterday"}})
    monkeypatch.setattr(
        graph_module,
        "validate_semantics",
        lambda *args, **kwargs: semantic_result(
            SemanticStatus.DENY,
            {
                "code": "relative_date",
                "field": "due_date",
                "message": "Relative date is not a normalized invoice date.",
                "evidence": ["yesterday"],
            },
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "review_stage",
        lambda *args, **kwargs: critic_result(CriticDecision.AGREE),
    )

    result = runner.run_validation(original, persist_artifacts=False)

    assert result.status == ValidationStatus.DENIED
    assert result.issues[0].code == "relative_date"


def test_negative_quantity_is_denied(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("-5")}]})
    monkeypatch.setattr(
        graph_module,
        "validate_semantics",
        lambda *args, **kwargs: semantic_result(
            SemanticStatus.DENY,
            {
                "code": "negative_quantity",
                "field": "items[0].quantity",
                "message": "Negative quantities are invalid.",
            },
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "review_stage",
        lambda *args, **kwargs: critic_result(CriticDecision.AGREE),
    )

    assert runner.run_validation(original, persist_artifacts=False).status == ValidationStatus.DENIED


def test_contradictory_dates_are_denied(monkeypatch):
    original = ingestion(
        {"invoice_date": date(2026, 9, 18), "due_date": date(2026, 9, 10)}
    )
    monkeypatch.setattr(
        graph_module,
        "validate_semantics",
        lambda *args, **kwargs: semantic_result(
            SemanticStatus.DENY,
            {
                "code": "contradictory_dates",
                "field": "due_date",
                "message": "Due date precedes invoice date.",
            },
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "review_stage",
        lambda *args, **kwargs: critic_result(CriticDecision.AGREE),
    )

    assert runner.run_validation(original, persist_artifacts=False).status == ValidationStatus.DENIED


def test_critic_revises_false_pass_for_negative_quantity(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("-5")}]})

    def fake_invoke(**kwargs):
        payload = json.loads(kwargs["content"])
        assert payload["specialist_stage_result"]["status"] == "PASS"
        assert payload["original_ingestion"]["normalization"]["invoice"]["items"][0]["quantity"] == "-5"
        return kwargs["output_model"].model_validate(
            {
                "decision": "REVISE",
                "summary": "Negative quantity was missed.",
                "revision_instructions": "Re-check every line-item quantity.",
                "findings": [
                    {
                        "code": "negative_quantity",
                        "field": "items[0].quantity",
                        "message": "Quantity -5 is invalid.",
                    }
                ],
            }
        )

    monkeypatch.setattr(critic_module, "invoke_structured", fake_invoke)
    result = critic_module.review_stage(
        original,
        "semantic",
        semantic_result(SemanticStatus.PASS),
    )

    assert result.decision == CriticDecision.REVISE


def test_critic_agrees_with_correct_semantic_pass(monkeypatch):
    monkeypatch.setattr(
        critic_module,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {"decision": "AGREE", "summary": "The valid invoice is in scope."}
        ),
    )

    result = critic_module.review_stage(
        ingestion({"items": [{"quantity": Decimal("2")}]}),
        "semantic",
        semantic_result(SemanticStatus.PASS),
    )

    assert result.decision == CriticDecision.AGREE


def test_critic_agrees_with_correct_semantic_deny(monkeypatch):
    monkeypatch.setattr(
        critic_module,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {"decision": "AGREE", "summary": "The negative quantity is a valid Semantic denial."}
        ),
    )

    result = critic_module.review_stage(
        ingestion({"items": [{"quantity": Decimal("-5")}]}),
        "semantic",
        semantic_result(
            SemanticStatus.DENY,
            {"code": "negative_quantity", "field": "items[0].quantity", "message": "Negative quantity."},
        ),
    )

    assert result.decision == CriticDecision.AGREE


def test_critic_revises_unsupported_false_deny(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("5")}]})
    monkeypatch.setattr(
        critic_module,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {
                "decision": "REVISE",
                "summary": "The denial has no supported semantic issue.",
                "revision_instructions": "Re-check the unsupported denial and pass if no issue remains.",
                "findings": [
                    {
                        "code": "unsupported_denial",
                        "message": "The valid quantity does not support DENY.",
                    }
                ],
            }
        ),
    )

    result = critic_module.review_stage(
        original,
        "semantic",
        semantic_result(SemanticStatus.DENY, {"code": "not_supported", "message": "No real issue."}),
    )

    assert result.decision == CriticDecision.REVISE


def test_semantic_and_critic_use_the_same_scope_contract():
    semantic_prompt = semantic_module._semantic_prompt()
    critic_prompt = critic_module._critic_prompt()

    for phrase in (
        "invoice_total",
        "amount_due",
        "payment terms",
        "line totals",
        "Root-cause policy",
        "DO NOT compare invoice dates against the current date",
        "invoice_date > due_date",
        'invoice_date > "today"',
        "Repeated normalized products may legitimately have different unit prices",
    ):
        assert phrase in semantic_prompt
        assert phrase in critic_prompt
    assert "REVISE is the structured equivalent of disagreement" in critic_prompt.replace("\n", " ")


def test_reconciliation_critic_prompt_is_isolated_from_semantic_phase_one_rules():
    prompt = critic_module._critic_prompt("reconciliation")

    assert "PHASE 2 RECONCILIATION SCOPE CONTRACT" in prompt
    assert "Different unit prices for repeated normalized products are allowed" in prompt
    assert "Phase 1 contract" not in prompt
    assert "amount_due" not in prompt


def test_critic_revises_reconciliation_only_denial(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("2"), "unit_price": Decimal("5")} ]})
    monkeypatch.setattr(
        critic_module,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {
                "decision": "REVISE",
                "summary": "Reconciliation is outside Phase 1.",
                "revision_instructions": "Remove the total mismatch and re-evaluate Semantic issues.",
                "findings": [
                    {
                        "code": "out_of_scope_reconciliation",
                        "field": "invoice_total",
                        "message": "Invoice-total reconciliation belongs to a later stage.",
                    }
                ],
            }
        ),
    )

    result = critic_module.review_stage(
        original,
        "semantic",
        semantic_result(
            SemanticStatus.DENY,
            {"code": "invoice_total_mismatch", "field": "invoice_total", "message": "Totals differ."},
        ),
    )

    assert result.decision == CriticDecision.REVISE


def test_critic_revises_invented_required_amount_due(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("2")} ]})
    monkeypatch.setattr(
        critic_module,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {
                "decision": "REVISE",
                "summary": "Amount due is not a Phase 1 requirement.",
                "revision_instructions": "Remove the invented required-field denial and re-check the invoice.",
                "findings": [
                    {
                        "code": "invented_required_field",
                        "field": "amount_due",
                        "message": "amount_due is not universally required by Semantic validation.",
                    }
                ],
            }
        ),
    )

    result = critic_module.review_stage(
        original,
        "semantic",
        semantic_result(
            SemanticStatus.DENY,
            {"code": "missing_amount_due", "field": "amount_due", "message": "Required field missing."},
        ),
    )

    assert result.decision == CriticDecision.REVISE


def test_critic_requests_root_cause_revision_for_duplicate_symptoms(monkeypatch):
    original = ingestion({"additional_fields": {"due_date_raw": "yesterday"}})
    monkeypatch.setattr(
        critic_module,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {
                "decision": "REVISE",
                "summary": "Report the unresolved date as one root issue.",
                "revision_instructions": "Keep relative_date on due_date and remove missing_due_date.",
                "findings": [
                    {
                        "code": "duplicate_symptom",
                        "field": "due_date",
                        "message": "The missing normalized date is caused by the relative raw date.",
                    }
                ],
            }
        ),
    )

    result = critic_module.review_stage(
        original,
        "semantic",
        semantic_result(
            SemanticStatus.DENY,
            {"code": "relative_date", "field": "due_date", "message": "Relative date."},
            {"code": "missing_due_date", "field": "due_date", "message": "Date missing."},
        ),
    )

    assert result.decision == CriticDecision.REVISE


def test_unresolved_critic_loop_fails_closed(monkeypatch):
    original = ingestion({"items": [{"quantity": Decimal("5")}]})
    semantic_calls = 0
    critic_calls = 0

    def semantic_stub(*args, **kwargs):
        nonlocal semantic_calls
        semantic_calls += 1
        return semantic_result(SemanticStatus.PASS)

    def critic_stub(*args, **kwargs):
        nonlocal critic_calls
        critic_calls += 1
        return critic_result(
            CriticDecision.REVISE,
            revision_instructions="Re-check the complete invoice.",
        )

    monkeypatch.setattr(graph_module, "validate_semantics", semantic_stub)
    monkeypatch.setattr(graph_module, "review_stage", critic_stub)

    result = runner.run_validation(original, persist_artifacts=False)

    assert result.status == ValidationStatus.DENIED
    assert result.reason == "unresolved_validation"
    assert any(issue.code == "unresolved_validation" for issue in result.issues)
    assert semantic_calls == 3
    assert critic_calls == 3
