from pydantic import BaseModel

from invoice_system import agent_runtime


class _Output(BaseModel):
    value: int


def test_invalid_structured_output_gets_one_schema_correction_retry(monkeypatch):
    prompts = []
    responses = iter(['{"value": "not an integer"}', '{"value": 7}'])

    def fake_request(**kwargs):
        prompts.append(kwargs["system_prompt"])
        return next(responses)

    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "test-model")
    monkeypatch.setattr(agent_runtime, "_request_structured_text", fake_request)

    result = agent_runtime.invoke_structured(
        system_prompt="base prompt",
        content="source",
        output_model=_Output,
    )

    assert result.value == 7
    assert len(prompts) == 2
    assert "did not match the required schema" in prompts[1]


def test_second_schema_failure_is_reported(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "test-model")
    monkeypatch.setattr(
        agent_runtime,
        "_request_structured_text",
        lambda **kwargs: '{"value": "not an integer"}',
    )

    try:
        agent_runtime.invoke_structured(
            system_prompt="base prompt",
            content="source",
            output_model=_Output,
        )
    except agent_runtime.ModelInvocationError as exc:
        assert "after schema retry" in str(exc)
    else:
        raise AssertionError("expected schema retry failure")


def test_tamu_provider_uses_tamu_configuration(monkeypatch):
    request = {}

    def fake_request(**kwargs):
        request.update(kwargs)
        return '{"value": 7}'

    monkeypatch.setenv("LLM_PROVIDER", "tamu")
    monkeypatch.setenv("TAMUS_AI_CHAT_API_KEY", "tamu-key")
    monkeypatch.setenv("TAMUS_AI_CHAT_MODEL", "tamu-model")
    monkeypatch.setattr(agent_runtime, "_request_structured_text", fake_request)

    result = agent_runtime.invoke_structured(
        system_prompt="base prompt",
        content="source",
        output_model=_Output,
    )

    assert result.value == 7
    assert request["api_key"] == "tamu-key"
    assert request["model"] == "tamu-model"
    assert request["endpoint"] == "https://chat-api.tamu.ai"
    assert request["chat_path"] == "/api/chat/completions"


def test_grok_provider_does_not_use_tamu_model(monkeypatch):
    request = {}

    def fake_request(**kwargs):
        request.update(kwargs)
        return '{"value": 7}'

    monkeypatch.setenv("LLM_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "grok-key")
    monkeypatch.delenv("XAI_MODEL", raising=False)
    monkeypatch.setenv("TAMUS_AI_CHAT_MODEL", "must-not-be-used")
    monkeypatch.setattr(agent_runtime, "_request_structured_text", fake_request)

    result = agent_runtime.invoke_structured(
        system_prompt="base prompt",
        content="source",
        output_model=_Output,
    )

    assert result.value == 7
    assert request["api_key"] == "grok-key"
    assert request["model"] == "grok-3-mini"
    assert request["endpoint"] == "https://api.x.ai/v1"
    assert request["chat_path"] == "/chat/completions"
