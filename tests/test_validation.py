import json
from datetime import date
from decimal import Decimal

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


def test_relative_date_is_denied_by_semantic_result(monkeypatch):
    original = ingestion({"additional_fields": {"due_date_raw": "yesterday"}})
    monkeypatch.setattr(
        graph_module,
        "validate_semantics",
        lambda *args, **kwargs: semantic_result(
            SemanticStatus.DENY,
            {
                "code": "relative_date",
                "field": "additional_fields.due_date_raw",
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
