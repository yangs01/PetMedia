"""Claude through the native Messages API, using Anthropic's official SDK.

The SDK's retries are off because node retries already handle transient failures,
and two layers would multiply API calls. The API version the SDK sends (2026-10-21)
rejects temperature, top_p and top_k, so ``ModelRegistry`` refuses those settings.
"""

import logging
from time import perf_counter
from typing import Any

import anthropic
from pydantic import BaseModel

from app.ai.providers.llm_provider import RETRYABLE_STATUS, StructuredLLMProvider
from app.ai.providers.model_config import ModelProfile
from app.core.exceptions import (
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderTransientError,
    StructuredOutputError,
)

logger = logging.getLogger(__name__)

# The Messages API requires max_tokens. Non-streaming requests stay within this limit.
DEFAULT_MAX_TOKENS = 16000


class AnthropicLLMProvider(StructuredLLMProvider):
    name = "anthropic"

    def __init__(
        self,
        profile: ModelProfile,
        api_key: str,
        *,
        http_client: anthropic.DefaultAsyncHttpxClient | None = None,
    ) -> None:
        super().__init__(profile)
        self._max_tokens = profile.max_tokens or DEFAULT_MAX_TOKENS
        self._effort = profile.effort
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=profile.base_url,
            timeout=profile.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def _complete(
        self, system: str, messages: list[dict[str, str]], schema: type[BaseModel], operation: str
    ) -> str:
        # transform_schema moves constraints the API does not accept into descriptions.
        # Pydantic still enforces them on the response.
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
        }
        if self._effort:
            output_config["effort"] = self._effort
        started = perf_counter()
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
            )
        except anthropic.APITimeoutError as error:
            raise ProviderTransientError("The LLM request timed out.") from error
        except anthropic.APIConnectionError as error:
            raise ProviderTransientError("Could not reach the LLM API: connection failed.") from error
        except anthropic.APIStatusError as error:
            raise _translate_status_error(error) from error
        logger.info(
            "LLM call finished",
            extra={
                "provider": self.name,
                "operation": operation,
                "stop_reason": response.stop_reason,
                "duration": round(perf_counter() - started, 3),
            },
        )
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise ProviderRefusalError(
                "The model declined to answer this request.", details={"category": category}
            )
        if response.stop_reason == "max_tokens":
            # Retrying at the same limit would stop at the same place.
            raise StructuredOutputError("The model hit its token limit. Raise max_tokens on its profile.")
        return "".join(block.text for block in response.content if block.type == "text")


def _translate_status_error(error: anthropic.APIStatusError) -> Exception:
    if error.status_code in RETRYABLE_STATUS or error.status_code >= 500:
        return ProviderTransientError(f"The LLM API returned HTTP {error.status_code}.")
    return ProviderPermanentError(
        f"The LLM API rejected the request with HTTP {error.status_code}.",
        details={"error_type": error.type, "response": error.message[:500]},
    )
