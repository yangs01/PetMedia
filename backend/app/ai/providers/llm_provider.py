"""LLM provider interface, the shared structured-output loop, and the OpenAI-style providers.

These providers use httpx directly against the ``/chat/completions`` endpoint. That
keeps the dependency small and works with any compatible service through a base URL.
What differs by vendor stays in small overrides, because compatible APIs are not identical.
"""

import json
import logging
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.prompts import load_prompt
from app.ai.providers.model_config import LEGACY_CREDENTIAL_ENV, ModelProfile, legacy_llm_profile
from app.core.config import Settings
from app.core.exceptions import (
    ProviderNotConfiguredError,
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderTransientError,
    StructuredOutputError,
)
from app.schemas.content import (
    CarouselPlanOutput,
    FacebookOutput,
    GenerationContext,
    InstagramOutput,
    MasterCopy,
    TopicBatchOutput,
    TopicOutput,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
# Keywords that strict mode either rejects or does not document as supported.
# Pydantic still enforces them on every response.
_NON_STRICT_KEYWORDS = {"default", "minLength", "maxLength"}


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate_topics(
        self,
        context: GenerationContext,
        *,
        count: int,
        feedback: str | None = None,
        previous_titles: list[str] | None = None,
    ) -> TopicBatchOutput: ...

    @abstractmethod
    async def generate_master_copy(self, context: GenerationContext, *, topic: TopicOutput) -> MasterCopy: ...

    @abstractmethod
    async def revise_master_copy(
        self, context: GenerationContext, *, topic: TopicOutput, current: MasterCopy, feedback: str
    ) -> MasterCopy: ...

    @abstractmethod
    async def adapt_instagram(
        self, context: GenerationContext, *, master: MasterCopy, feedback: str | None = None
    ) -> InstagramOutput: ...

    @abstractmethod
    async def adapt_facebook(
        self, context: GenerationContext, *, master: MasterCopy, feedback: str | None = None
    ) -> FacebookOutput: ...

    @abstractmethod
    async def plan_carousel(
        self,
        context: GenerationContext,
        *,
        master: MasterCopy,
        image_count: int,
        feedback: str | None = None,
    ) -> CarouselPlanOutput: ...


def _context_data(context: GenerationContext) -> dict[str, Any]:
    """Task data sent to the model. Internal storage paths are not its business."""
    return context.model_dump(
        mode="json", exclude={"brand": {"logo_path"}, "products": {"__all__": {"image_paths"}}}
    )


class StructuredLLMProvider(LLMProvider):
    """Prompts and bounded validation retries. Subclasses make the actual request."""

    def __init__(self, profile: ModelProfile) -> None:
        self._model = profile.model
        self._max_attempts = profile.max_structured_retries

    @abstractmethod
    async def _complete(
        self, system: str, messages: list[dict[str, str]], schema: type[BaseModel], operation: str
    ) -> str:
        """Return the model's text. A blank result counts as invalid output and is retried."""

    async def generate_topics(self, context, *, count, feedback=None, previous_titles=None):
        data = {
            **_context_data(context),
            "topic_count": count,
            "operator_feedback": feedback,
            "previous_titles": previous_titles or [],
        }

        def exact_count(batch: TopicBatchOutput) -> None:
            if len(batch.topics) != count:
                raise ValueError(f"Return exactly {count} topics; got {len(batch.topics)}.")

        return await self._structured("topic_generation", data, TopicBatchOutput, exact_count)

    async def generate_master_copy(self, context, *, topic):
        data = {**_context_data(context), "selected_topic": topic.model_dump()}
        return await self._structured("copy_generation", data, MasterCopy)

    async def revise_master_copy(self, context, *, topic, current, feedback):
        data = {
            **_context_data(context),
            "selected_topic": topic.model_dump(),
            "current_draft": current.model_dump(),
            "revision_feedback": feedback,
        }
        return await self._structured("copy_revision", data, MasterCopy)

    async def adapt_instagram(self, context, *, master, feedback=None):
        data = {**_context_data(context), "approved_draft": master.model_dump(), "validation_feedback": feedback}
        return await self._structured("instagram_adapter", data, InstagramOutput)

    async def adapt_facebook(self, context, *, master, feedback=None):
        data = {**_context_data(context), "approved_draft": master.model_dump(), "validation_feedback": feedback}
        return await self._structured("facebook_adapter", data, FacebookOutput)

    async def plan_carousel(self, context, *, master, image_count, feedback=None):
        data = {
            **_context_data(context),
            "approved_draft": master.model_dump(),
            "image_count": image_count,
            "validation_feedback": feedback,
        }

        def exact_count(plan: CarouselPlanOutput) -> None:
            if len(plan.slides) != image_count:
                raise ValueError(f"Return exactly {image_count} slides; got {len(plan.slides)}.")

        return await self._structured("carousel_planning", data, CarouselPlanOutput, exact_count)

    async def _structured[T: BaseModel](
        self, prompt_name: str, data: dict[str, Any], schema: type[T], extra_check=None
    ) -> T:
        """Call the model until the response validates, within a fixed number of attempts."""
        guidelines = load_prompt("brand_guidelines")
        prompt = load_prompt(prompt_name)
        schema_json = json.dumps(schema.model_json_schema())
        system = f"{guidelines.text}\n\n{prompt.text}\n\n## JSON schema\n{schema_json}"
        request = {
            "role": "user",
            "content": f"<untrusted_data>\n{json.dumps(data, ensure_ascii=False)}\n</untrusted_data>",
        }
        messages: list[dict[str, str]] = [request]
        problem = "no response"
        for attempt in range(1, self._max_attempts + 1):
            raw = await self._complete(system, messages, schema, prompt_name)
            try:
                parsed = schema.model_validate_json(raw)
                if extra_check:
                    extra_check(parsed)
                return parsed
            except (ValidationError, ValueError) as error:
                problem = str(error)[:1500]
                logger.warning(
                    "LLM returned invalid structured output",
                    extra={"operation": prompt_name, "attempt": attempt, "provider": self.name},
                )
                earlier = [{"role": "assistant", "content": raw[:20000]}] if raw.strip() else []
                messages = [
                    request,
                    *earlier,
                    {
                        "role": "user",
                        "content": f"That response is invalid: {problem}\nReturn corrected JSON only.",
                    },
                ]
        raise StructuredOutputError(
            f"The model returned invalid output for '{prompt_name}' {self._max_attempts} times.",
            details={"last_problem": problem},
        )


class OpenAIChatProvider(StructuredLLMProvider):
    """Any service with a compatible ``/chat/completions`` endpoint."""

    name = "openai_compatible"
    _max_tokens_field = "max_tokens"

    def __init__(
        self, profile: ModelProfile, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        super().__init__(profile)
        self._temperature = profile.temperature
        self._max_tokens = profile.max_tokens
        self._structured_mode = profile.structured_mode or "json_object"
        self._client = httpx.AsyncClient(
            base_url=profile.base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=profile.timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(
        self, system: str, messages: list[dict[str, str]], schema: type[BaseModel], operation: str
    ) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "response_format": self._response_format(schema),
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._max_tokens is not None:
            body[self._max_tokens_field] = self._max_tokens
        started = perf_counter()
        try:
            response = await self._client.post("chat/completions", json=body)
        except httpx.TimeoutException as error:
            raise ProviderTransientError("The LLM request timed out.") from error
        except httpx.TransportError as error:
            raise ProviderTransientError(f"Could not reach the LLM API: {type(error).__name__}.") from error
        logger.info(
            "LLM call finished",
            extra={
                "provider": self.name,
                "operation": operation,
                "status_code": response.status_code,
                "duration": round(perf_counter() - started, 3),
            },
        )
        if response.status_code in RETRYABLE_STATUS:
            raise ProviderTransientError(f"The LLM API returned HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise ProviderPermanentError(
                f"The LLM API rejected the request with HTTP {response.status_code}.",
                details={"response": response.text[:500]},
            )
        return self._read_choice(response)

    def _read_choice(self, response: httpx.Response) -> str:
        try:
            choice = response.json()["choices"][0]
            message = choice["message"]
            content = message["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise StructuredOutputError("The LLM API response had an unexpected shape.") from error
        finish_reason = choice.get("finish_reason")
        if message.get("refusal") or finish_reason == "content_filter":
            raise ProviderRefusalError("The model declined to answer this request.")
        if finish_reason == "length":
            # Retrying at the same limit would stop at the same place.
            raise StructuredOutputError("The model hit its token limit. Raise max_tokens on its profile.")
        if finish_reason == "insufficient_system_resource":
            raise ProviderTransientError("The LLM API ran out of capacity mid-response.")
        if content is not None and not isinstance(content, str):
            raise StructuredOutputError("The LLM API response had an unexpected shape.")
        return content or ""

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        if self._structured_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            }
        return {"type": "json_object"}


class OpenAICompatibleLLMProvider(OpenAIChatProvider):
    """The original single-model provider, configured from the global LLM_* settings."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        if not api_key or not settings.llm_model:
            raise ProviderNotConfiguredError(
                f"The real LLM provider needs {LEGACY_CREDENTIAL_ENV} and LLM_MODEL. "
                "Set them in .env, or set LLM_PROVIDER=mock for offline use."
            )
        super().__init__(legacy_llm_profile(settings), api_key, transport=transport)


class OpenAILLMProvider(OpenAIChatProvider):
    name = "openai"
    # OpenAI deprecated max_tokens here, and it does not work with its reasoning models.
    _max_tokens_field = "max_completion_tokens"

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        if self._structured_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": strict_json_schema(schema.model_json_schema()),
                },
            }
        return {"type": "json_object"}


class DeepSeekLLMProvider(OpenAIChatProvider):
    """DeepSeek's JSON mode needs the word "json" in the prompt, which the system prompt has.

    It offers no JSON schema mode, and it can answer with only spaces when its output
    is not recognized as JSON. The structured-output loop retries those blank answers.
    """

    name = "deepseek"


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Apply OpenAI's strict rules: closed objects with every property listed as required."""
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _NON_STRICT_KEYWORDS:
            continue
        if key in ("properties", "$defs"):
            # These keys hold names, so a field called "default" must survive.
            result[key] = {name: strict_json_schema(item) for name, item in value.items()}
        elif isinstance(value, dict):
            result[key] = strict_json_schema(value)
        elif isinstance(value, list):
            result[key] = [strict_json_schema(item) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
    if result.get("type") == "object":
        result["additionalProperties"] = False
        result["required"] = list(result.get("properties", {}))
    return result
