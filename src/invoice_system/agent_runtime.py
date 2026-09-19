"""Shared structured calls through the TAMUS AI Chat API."""

import json
import logging
import os
import time

import httpx
from langsmith import traceable
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class ModelInvocationError(Exception):
    """Configuration, API, or structured response failure."""


class StructuredOutputError(ModelInvocationError):
    """The model response remained invalid after the schema correction retry."""


@traceable(name="TAMUS structured output", run_type="llm")
def invoke_structured[T: BaseModel](
    *, system_prompt: str, content: str, output_model: type[T], model: str | None = None
) -> T:
    api_key = os.getenv("TAMUS_AI_CHAT_API_KEY")
    selected_model = model or os.getenv("TAMUS_AI_CHAT_MODEL")
    if not api_key or not selected_model:
        raise ModelInvocationError(
            "Set TAMUS_AI_CHAT_API_KEY and TAMUS_AI_CHAT_MODEL in the environment or .env"
        )
    endpoint = os.getenv("TAMUS_AI_CHAT_API_ENDPOINT", "https://chat-api.tamu.ai").rstrip("/")
    try:
        prompt = system_prompt
        for schema_attempt in range(2):
            text = _request_structured_text(
                api_key=api_key,
                endpoint=endpoint,
                model=selected_model,
                system_prompt=prompt,
                content=content,
                output_model=output_model,
            )
            try:
                return output_model.model_validate_json(text)
            except ValidationError as exc:
                if schema_attempt:
                    raise StructuredOutputError(
                        f"TAMUS returned invalid structured output after schema retry: {exc}"
                    ) from exc
                logger.warning("[model] Structured output failed schema validation; requesting one correction")
                prompt = (
                    system_prompt
                    + "\n\nYour previous response did not match the required schema. "
                    "Return a corrected complete JSON object only; preserve the source claims and "
                    "do not omit unrelated valid fields. Validation error:\n"
                    + str(exc)
                )
    except ModelInvocationError:
        raise
    except Exception as exc:
        raise ModelInvocationError(f"TAMUS invocation failed ({selected_model}): {exc}") from exc


def _request_structured_text[T: BaseModel](
    *,
    api_key: str,
    endpoint: str,
    model: str,
    system_prompt: str,
    content: str,
    output_model: type[T],
) -> str:
    schema_instruction = (
        "\nReturn only one JSON object matching this JSON Schema. "
        "Do not include markdown fences or commentary.\n"
        + json.dumps(output_model.model_json_schema())
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt + schema_instruction},
            {"role": "user", "content": content},
        ],
    }
    # The TAMUS quickstart does not promise server-side JSON schema enforcement.
    with httpx.Client(timeout=120) as client:
        for attempt in range(3):
            try:
                response = client.post(
                    endpoint + "/api/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
            except httpx.TransportError:
                if attempt == 2:
                    raise
                logger.warning("[model] Transient transport error; retrying request")
                time.sleep(2 ** attempt)
                continue
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                logger.warning("[model] HTTP %s; retrying request", response.status_code)
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            break
    body = response.json()
    choice = body["choices"][0]
    if choice.get("finish_reason") not in {None, "stop"}:
        raise ModelInvocationError(f"TAMUS response did not finish normally: {choice['finish_reason']}")
    text = choice["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ModelInvocationError("TAMUS returned no structured text")
    return text
