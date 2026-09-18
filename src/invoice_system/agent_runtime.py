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


@traceable(name="TAMUS structured output", run_type="llm")
def invoke_structured[T: BaseModel](
    *, system_prompt: str, content: str, output_model: type[T]
) -> T:
    api_key = os.getenv("TAMUS_AI_CHAT_API_KEY")
    model = os.getenv("TAMUS_AI_CHAT_MODEL")
    if not api_key or not model:
        raise ModelInvocationError(
            "Set TAMUS_AI_CHAT_API_KEY and TAMUS_AI_CHAT_MODEL in the environment or .env"
        )
    endpoint = os.getenv("TAMUS_AI_CHAT_API_ENDPOINT", "https://chat-api.tamu.ai").rstrip("/")
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
    try:
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
        return output_model.model_validate_json(text)
    except ModelInvocationError:
        raise
    except ValidationError as exc:
        raise ModelInvocationError(f"TAMUS returned invalid structured output: {exc}") from exc
    except Exception as exc:
        raise ModelInvocationError(f"TAMUS invocation failed ({model}): {exc}") from exc
