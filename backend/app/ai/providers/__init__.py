"""Provider factories: the only place that maps configuration to an implementation."""

from collections.abc import Mapping

from app.ai.providers.image_provider import ImageProvider, OpenAICompatibleImageProvider
from app.ai.providers.llm_provider import LLMProvider, OpenAICompatibleLLMProvider
from app.ai.providers.mock_provider import MockImageProvider, MockLLMProvider
from app.ai.providers.model_config import (
    LEGACY_CREDENTIAL_ENV,
    legacy_model_config,
    load_model_config,
    read_environment,
)
from app.ai.providers.model_registry import ModelRegistry
from app.ai.providers.model_router import ModelRouter
from app.core.config import Settings


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockLLMProvider(delay_seconds=settings.mock_llm_delay_seconds)
    return OpenAICompatibleLLMProvider(settings)


def create_model_registry(settings: Settings, environ: Mapping[str, str] | None = None) -> ModelRegistry:
    """Use the profiles file when LLM_PROFILES_PATH is set, and the LLM_* settings otherwise."""
    path = settings.resolved_llm_profiles_path
    if path is None:
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        return ModelRegistry(legacy_model_config(settings), {LEGACY_CREDENTIAL_ENV: key}, settings)
    environ = read_environment() if environ is None else environ
    return ModelRegistry(load_model_config(path, environ), environ, settings)


def create_model_router(settings: Settings, environ: Mapping[str, str] | None = None) -> ModelRouter:
    return ModelRouter.from_registry(create_model_registry(settings, environ))


def create_image_provider(settings: Settings) -> ImageProvider:
    if settings.image_provider == "mock":
        return MockImageProvider()
    return OpenAICompatibleImageProvider(settings)
