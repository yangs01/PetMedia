"""LLM provider interface and the OpenAI-compatible implementation.

The real provider uses httpx directly against the ``/chat/completions`` endpoint.
That keeps the dependency small and works with any compatible service through
``LLM_BASE_URL``.
"""

import json
import logging
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.prompts import load_prompt
from app.core.config import Settings
from app.core.exceptions import (
    ProviderNotConfiguredError,
    ProviderPermanentError,
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


class OpenAICompatibleLLMProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        if not api_key or not settings.llm_model:
            raise ProviderNotConfiguredError(
                "The real LLM provider needs LLM_API_KEY and LLM_MODEL. "
                "Set them in .env, or set LLM_PROVIDER=mock for offline use."
            )
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature
        self._structured_mode = settings.llm_structured_mode
        self._max_attempts = settings.llm_max_structured_retries
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.llm_timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

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
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": f"{guidelines.text}\n\n{prompt.text}\n\n## JSON schema\n{schema_json}",
            },
            {
                "role": "user",
                "content": f"<untrusted_data>\n{json.dumps(data, ensure_ascii=False)}\n</untrusted_data>",
            },
        ]
        problem = "no response"
        for attempt in range(1, self._max_attempts + 1):
            raw = await self._chat(messages, schema, prompt_name)
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
                messages = [
                    *messages[:2],
                    {"role": "assistant", "content": raw[:20000]},
                    {
                        "role": "user",
                        "content": f"That response is invalid: {problem}\nReturn corrected JSON only.",
                    },
                ]
        raise StructuredOutputError(
            f"The model returned invalid output for '{prompt_name}' {self._max_attempts} times.",
            details={"last_problem": problem},
        )

    async def _chat(self, messages: list[dict[str, str]], schema: type[BaseModel], operation: str) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "response_format": self._response_format(schema),
        }
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
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise StructuredOutputError("The LLM API response had an unexpected shape.") from error
        if not content:
            raise StructuredOutputError("The LLM API returned an empty message.")
        return content

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        if self._structured_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            }
        return {"type": "json_object"}
