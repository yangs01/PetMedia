"""Picks the configured model for a workflow role. There is no autonomous routing."""

import logging
from collections.abc import Awaitable, Callable, Mapping

from app.ai.providers.llm_provider import LLMProvider
from app.ai.providers.model_config import ModelRole
from app.ai.providers.model_registry import ModelRegistry
from app.core.exceptions import ProviderRefusalError, ProviderTransientError, StructuredOutputError

logger = logging.getLogger(__name__)

# A rejected request or a bad key is a configuration problem that another model must not hide.
_FALLBACK_ERRORS = (ProviderTransientError, StructuredOutputError, ProviderRefusalError)


class ModelRouter:
    def __init__(
        self,
        routes: Mapping[ModelRole, tuple[LLMProvider, LLMProvider | None]],
        *,
        descriptions: Mapping[str, str] | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._routes = dict(routes)
        self._descriptions = dict(descriptions or {})
        self._close = close

    @classmethod
    def from_registry(cls, registry: ModelRegistry) -> "ModelRouter":
        """Create every client up front, so a bad configuration stops the worker at startup."""
        registry.validate()
        routes: dict[ModelRole, tuple[LLMProvider, LLMProvider | None]] = {}
        descriptions: dict[str, str] = {}
        for role in ModelRole:
            name = registry.config.profile_name_for(role)
            fallback = registry.config.profiles[name].fallback_profile
            routes[role] = (registry.get(name), registry.get(fallback) if fallback else None)
            profile = registry.resolve(name)
            descriptions[role.value] = f"{name} ({profile.provider.value}:{profile.model})"
        return cls(routes, descriptions=descriptions, close=registry.aclose)

    @classmethod
    def uniform(cls, provider: LLMProvider) -> "ModelRouter":
        """Serve every role with one provider."""
        return cls({role: (provider, None) for role in ModelRole})

    def for_role(self, role: ModelRole | str) -> LLMProvider:
        """Return the provider for a role. Read ``name`` after the call to see who answered."""
        role = ModelRole(role)
        primary, fallback = self._routes[role]
        return FallbackLLMProvider(role, primary, fallback) if fallback else primary

    def describe(self) -> dict[str, str]:
        """Role to profile, for logs. Holds no credentials."""
        return self._descriptions or {role.value: pair[0].name for role, pair in self._routes.items()}

    async def aclose(self) -> None:
        if self._close:
            await self._close()


class FallbackLLMProvider(LLMProvider):
    """Tries the fallback profile when the primary fails in a way another model could avoid.

    A new instance is made per ``for_role`` call, so ``name`` cannot be overwritten by
    another task. It names the provider that answered most recently, and records use it.
    """

    def __init__(self, role: ModelRole, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._role = role
        self._primary = primary
        self._fallback = fallback
        self.name = primary.name

    async def _call(self, method: str, *args, **kwargs):
        try:
            result = await getattr(self._primary, method)(*args, **kwargs)
            self.name = self._primary.name
            return result
        except _FALLBACK_ERRORS as error:
            logger.warning(
                "Primary model failed; using the fallback profile",
                extra={
                    "role": self._role.value,
                    "primary": self._primary.name,
                    "fallback": self._fallback.name,
                    "error_code": error.code,
                },
            )
        result = await getattr(self._fallback, method)(*args, **kwargs)
        self.name = self._fallback.name
        return result

    async def generate_topics(self, context, *, count, feedback=None, previous_titles=None):
        return await self._call(
            "generate_topics", context, count=count, feedback=feedback, previous_titles=previous_titles
        )

    async def generate_master_copy(self, context, *, topic):
        return await self._call("generate_master_copy", context, topic=topic)

    async def revise_master_copy(self, context, *, topic, current, feedback):
        return await self._call("revise_master_copy", context, topic=topic, current=current, feedback=feedback)

    async def adapt_instagram(self, context, *, master, feedback=None):
        return await self._call("adapt_instagram", context, master=master, feedback=feedback)

    async def adapt_facebook(self, context, *, master, feedback=None):
        return await self._call("adapt_facebook", context, master=master, feedback=feedback)

    async def plan_carousel(self, context, *, master, image_count, feedback=None):
        return await self._call("plan_carousel", context, master=master, image_count=image_count, feedback=feedback)
