from pathlib import Path

from invoice_system.ingestion import critic, normalizer
from invoice_system.ingestion.models import (
    CritiqueResult,
    NormalizationResult,
    SourceChunk,
    SourceDocument,
)
from invoice_system.ingestion.normalization_policy import load_normalization_policy


def _source() -> SourceDocument:
    return SourceDocument(
        filename="invoice.txt",
        file_type="txt",
        chunks=(
            SourceChunk(
                id="chunk-1",
                text="Total: $225.00",
                kind="text",
                extraction_method="test",
            ),
        ),
    )


def _normalization() -> NormalizationResult:
    return NormalizationResult(invoice={}, evidence=[])


def test_normalizer_critic_and_revision_share_the_loaded_policy(monkeypatch):
    policy = "TEST POLICY MARKER"
    monkeypatch.setattr(critic, "load_normalization_policy", lambda: policy)
    monkeypatch.setattr(normalizer, "load_normalization_policy", lambda: policy)
    prompts = []

    def fake_invoke(*, system_prompt, **kwargs):
        prompts.append(system_prompt)
        return kwargs["output_model"]() if issubclass(kwargs["output_model"], CritiqueResult) else _normalization()

    monkeypatch.setattr(normalizer, "invoke_structured", fake_invoke)
    monkeypatch.setattr(critic, "invoke_structured", fake_invoke)

    source = _source()
    normalized = normalizer.normalize(source)
    critic.critique(source, normalized)
    normalizer.revise_normalization(source, normalized, CritiqueResult())

    assert len(prompts) == 3
    assert all(policy in prompt for prompt in prompts)


def test_policy_file_changes_are_visible_to_all_stage_prompts(monkeypatch):
    policy_path = Path(__file__).with_name(".normalization_policy_test.md")
    prompts = []

    def fake_invoke(*, system_prompt, **kwargs):
        prompts.append(system_prompt)
        return kwargs["output_model"]() if issubclass(kwargs["output_model"], CritiqueResult) else _normalization()

    try:
        policy_path.write_text("first policy", encoding="utf-8")
        monkeypatch.setattr("invoice_system.ingestion.normalization_policy._POLICY_PATH", policy_path)
        monkeypatch.setattr(critic, "load_normalization_policy", load_normalization_policy)
        monkeypatch.setattr(normalizer, "load_normalization_policy", load_normalization_policy)
        monkeypatch.setattr(normalizer, "invoke_structured", fake_invoke)
        monkeypatch.setattr(critic, "invoke_structured", fake_invoke)
        source = _source()

        normalizer.normalize(source)
        critic.critique(source, _normalization())
        policy_path.write_text("second policy", encoding="utf-8")
        normalizer.revise_normalization(source, _normalization(), CritiqueResult())
    finally:
        policy_path.unlink(missing_ok=True)

    assert "first policy" in prompts[0]
    assert "first policy" in prompts[1]
    assert "second policy" in prompts[2]


def test_critic_prompt_explicitly_allows_policy_permitted_values(monkeypatch):
    captured = {}

    def fake_invoke(*, system_prompt, **kwargs):
        captured["prompt"] = system_prompt
        return CritiqueResult()

    monkeypatch.setattr(critic, "invoke_structured", fake_invoke)
    result = critic.critique(_source(), _normalization())

    assert result.issues == []
    assert "Do not flag formatting-equivalent Decimal values" in captured["prompt"]
    assert "correctly preserved source mistakes" in captured["prompt"]
    assert "values left null" in captured["prompt"]


def test_critic_drops_self_contradictory_issue_explanations(monkeypatch):
    # The production invoker returns a Pydantic model; use its normal model
    # validation shape here while keeping the test independent of the API.
    from invoice_system.ingestion.models import CritiqueResult

    monkeypatch.setattr(
        critic,
        "invoke_structured",
        lambda **kwargs: kwargs["output_model"].model_validate(
            {
                "issues": [
                    {
                        "issue_type": "incorrect_value",
                        "field_path": "invoice_total",
                        "message": "The candidate is correct; no change is needed.",
                        "proposed_value": None,
                    }
                ]
            }
        ),
    )
    assert critic.critique(_source(), _normalization()).issues == []


def test_policy_defines_tax_rate_and_canonical_raw_field_rules():
    policy = load_normalization_policy()

    assert "6%` → `0.06" in policy
    assert "payment_terms" in policy
    assert "former_vendor_name" in policy
    assert "due_date_raw" in policy
    assert "amount_raw" in policy
    assert "Total Amount" in policy
    assert "Amount Due" in policy
