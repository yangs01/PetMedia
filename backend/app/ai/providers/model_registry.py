"""Validates model profiles against what each provider supports, and owns their clients."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.ai.providers.anthropic_provider import AnthropicLLMProvider
from app.ai.providers.llm_provider import (
    DeepSeekLLMProvider,
    LLMProvider,
    OpenAIChatProvider,
    OpenAILLMProvider,
)
from app.ai.providers.mock_provider import MockLLMProvider
from app.ai.providers.model_config import ModelConfig, ModelProfile, ProviderType
from app.core.config import Settings
from app.core.exceptions import ProviderNotConfiguredError

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[ModelProfile, str | None], LLMProvider]


@dataclass(frozen=True)
class ProviderCapabilities:
    structured_modes: tuple[str, ...] = ()
    default_base_url: str | None = None
    needs_credential: bool = True
    needs_base_url: bool = False
    https_only: bool = True
    supports_temperature: bool = True
    supports_max_tokens: bool = True
    supports_effort: bool = False


OPENAI_CAPABILITIES = ProviderCapabilities(
    structured_modes=("json_schema", "json_object"), default_base_url="https://api.openai.com/v1"
)
# json_object is listed first where it is the only mode or the safest for unknown services.
OPENAI_COMPATIBLE_CAPABILITIES = ProviderCapabilities(
    structured_modes=("json_object", "json_schema"), needs_base_url=True, https_only=False
)
DEEPSEEK_CAPABILITIES = ProviderCapabilities(
    structured_modes=("json_object",), default_base_url="https://api.deepseek.com"
)
ANTHROPIC_CAPABILITIES = ProviderCapabilities(
    structured_modes=("json_schema",),
    default_base_url="https://api.anthropic.com",
    supports_temperature=False,
    supports_effort=True,
)
MOCK_CAPABILITIES = ProviderCapabilities(
    needs_credential=False, supports_temperature=False, supports_max_tokens=False
)


class ModelRegistry:
    def __init__(
        self, config: ModelConfig, credentials: Mapping[str, str], settings: Settings
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._providers: dict[str, LLMProvider] = {}
        self._implementations: dict[ProviderType, tuple[ProviderFactory, ProviderCapabilities]] = {}
        self.register_provider(
            ProviderType.MOCK,
            lambda profile, key: MockLLMProvider(delay_seconds=settings.mock_llm_delay_seconds),
            MOCK_CAPABILITIES,
        )
        self.register_provider(ProviderType.OPENAI_COMPATIBLE, OpenAIChatProvider, OPENAI_COMPATIBLE_CAPABILITIES)
        self.register_provider(ProviderType.OPENAI, OpenAILLMProvider, OPENAI_CAPABILITIES)
        self.register_provider(ProviderType.DEEPSEEK, DeepSeekLLMProvider, DEEPSEEK_CAPABILITIES)
        self.register_provider(ProviderType.ANTHROPIC, AnthropicLLMProvider, ANTHROPIC_CAPABILITIES)

    @property
    def config(self) -> ModelConfig:
        return self._config

    def register_provider(
        self, provider: ProviderType, factory: ProviderFactory, capabilities: ProviderCapabilities | None = None
    ) -> None:
        """Add or replace an implementation. Omitted capabilities keep the current ones."""
        if capabilities is None:
            capabilities = self._implementations[provider][1]
        self._implementations[provider] = (factory, capabilities)

    def resolve(self, name: str) -> ModelProfile:
        """Return a profile with provider defaults applied, or explain why it cannot work."""
        profile = self._config.profiles.get(name)
        if profile is None:
            raise ProviderNotConfiguredError(f"Model profile '{name}' is not defined.")
        capabilities = self._implementations[profile.provider][1]
        self._check_settings(name, profile, capabilities)
        return profile.model_copy(
            update={
                "base_url": profile.base_url or capabilities.default_base_url,
                "structured_mode": profile.structured_mode
                or (capabilities.structured_modes[0] if capabilities.structured_modes else None),
            }
        )

    def validate(self) -> None:
        """Check every reachable profile, including its credential, without opening a client."""
        for name in self._config.referenced_profiles():
            profile = self.resolve(name)
            self._credential_for(name, profile)

    def get(self, name: str) -> LLMProvider:
        """Return this profile's provider. Each profile has one client, reused by every call."""
        if name not in self._providers:
            profile = self.resolve(name)
            factory = self._implementations[profile.provider][0]
            self._providers[name] = factory(profile, self._credential_for(name, profile))
        return self._providers[name]

    async def aclose(self) -> None:
        providers = list(self._providers.values())
        self._providers.clear()
        closers = [provider.aclose() for provider in providers if hasattr(provider, "aclose")]
        for outcome in await asyncio.gather(*closers, return_exceptions=True):
            if isinstance(outcome, Exception):
                logger.warning("Could not close an LLM client", extra={"error_type": type(outcome).__name__})

    def _check_settings(self, name: str, profile: ModelProfile, capabilities: ProviderCapabilities) -> None:
        provider = profile.provider.value

        def refuse(problem: str) -> None:
            raise ProviderNotConfiguredError(f"Model profile '{name}' ({provider}): {problem}")

        if capabilities.needs_credential and not profile.model:
            refuse("set a model identifier.")
        if capabilities.needs_base_url and not profile.base_url:
            refuse("set base_url.")
        if profile.temperature is not None and not capabilities.supports_temperature:
            refuse("this provider does not accept temperature. Remove it from the profile.")
        if profile.max_tokens is not None and not capabilities.supports_max_tokens:
            refuse("this provider does not accept max_tokens. Remove it from the profile.")
        if profile.effort is not None and not capabilities.supports_effort:
            refuse("this provider does not accept effort. Remove it from the profile.")
        if profile.structured_mode and profile.structured_mode not in capabilities.structured_modes:
            allowed = ", ".join(capabilities.structured_modes) or "none"
            refuse(f"structured_mode {profile.structured_mode} is not supported. Allowed: {allowed}.")
        if capabilities.https_only and profile.base_url and not _is_safe_url(profile.base_url):
            refuse("base_url must use HTTPS, so the API key is not sent in plain text.")

    def _credential_for(self, name: str, profile: ModelProfile) -> str | None:
        if not self._implementations[profile.provider][1].needs_credential:
            return None
        if not profile.credential_env:
            raise ProviderNotConfiguredError(f"Model profile '{name}' needs credential_env.")
        value = self._credentials.get(profile.credential_env)
        if not value:
            raise ProviderNotConfiguredError(
                f"Model profile '{name}' needs the environment variable {profile.credential_env}."
            )
        return value


def _is_safe_url(url: str) -> bool:
    return url.startswith(("https://", "http://127.0.0.1", "http://localhost"))
