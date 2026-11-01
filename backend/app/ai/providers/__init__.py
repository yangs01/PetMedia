"""Provider factories: the only place that maps configuration to an implementation."""

from app.ai.providers.image_provider import ImageProvider, OpenAICompatibleImageProvider
from app.ai.providers.llm_provider import LLMProvider, OpenAICompatibleLLMProvider
from app.ai.providers.mock_provider import MockImageProvider, MockLLMProvider
from app.core.config import Settings


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockLLMProvider(delay_seconds=settings.mock_llm_delay_seconds)
    return OpenAICompatibleLLMProvider(settings)


def create_image_provider(settings: Settings) -> ImageProvider:
    if settings.image_provider == "mock":
        return MockImageProvider()
    return OpenAICompatibleImageProvider(settings)
