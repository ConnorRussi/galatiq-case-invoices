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

    monkeypatch.setenv("TAMUS_AI_CHAT_API_KEY", "test-key")
    monkeypatch.setenv("TAMUS_AI_CHAT_MODEL", "test-model")
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
    monkeypatch.setenv("TAMUS_AI_CHAT_API_KEY", "test-key")
    monkeypatch.setenv("TAMUS_AI_CHAT_MODEL", "test-model")
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
