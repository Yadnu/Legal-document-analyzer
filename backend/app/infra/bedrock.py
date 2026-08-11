"""Bedrock Runtime helpers for grounded generation."""

from __future__ import annotations

from typing import Any

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.exceptions import AwsError
from app.infra.aws import get_bedrock_runtime_client

log = structlog.get_logger(__name__)


async def converse_text(
    *,
    system: str,
    user: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Call Bedrock Converse and return the assistant text.
    Raises ``AwsError`` on AWS failures so callers can fall back or surface 502.
    """
    try:
        async with get_bedrock_runtime_client() as client:
            response: dict[str, Any] = await client.converse(
                modelId=settings.bedrock_model_id,
                system=[{"text": system}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": user}],
                    }
                ],
                inferenceConfig={
                    "maxTokens": max_tokens or settings.generation_max_tokens,
                    "temperature": (
                        settings.generation_temperature
                        if temperature is None
                        else temperature
                    ),
                },
            )
    except (ClientError, BotoCoreError) as exc:
        log.error("bedrock_converse_failed", error=type(exc).__name__)
        raise AwsError("Generation service unavailable.") from exc
    output = response.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    texts = [block.get("text", "") for block in content if isinstance(block, dict)]
    joined = "\n".join(t for t in texts if t).strip()
    if not joined:
        raise AwsError("Generation service returned an empty response.")
    return joined
