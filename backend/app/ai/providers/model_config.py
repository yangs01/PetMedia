"""Typed configuration for LLM model profiles and the workflow roles that use them.

A profile says how to reach one model. A role names a generation task. The YAML
file named by ``LLM_PROFILES_PATH`` maps roles to profiles. Without that file, the
global ``LLM_*`` settings serve every role, exactly as before profiles existed.

Profiles name the environment variable that holds a key, never the key itself, and
validation errors hide their input in case a key was pasted into the wrong field.
"""

import os
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import PROJECT_ROOT, Settings
from app.core.exceptions import ProviderNotConfiguredError

LEGACY_PROFILE = "default"
LEGACY_CREDENTIAL_ENV = "LLM_API_KEY"

_REFERENCE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class ProviderType(StrEnum):
    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"


class ModelRole(StrEnum):
    TOPIC_GENERATION = "topic_generation"
    COPY_GENERATION = "copy_generation"
    COPY_REVISION = "copy_revision"
    INSTAGRAM_ADAPTATION = "instagram_adaptation"
    FACEBOOK_ADAPTATION = "facebook_adaptation"
    CAROUSEL_PLANNING = "carousel_planning"


class ModelProfile(BaseModel):
    """How to reach one model. ``ModelRegistry`` checks these against provider capabilities."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    provider: ProviderType
    model: str = ""
    credential_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")
    base_url: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=120, gt=0)
    structured_mode: Literal["json_object", "json_schema"] | None = None
    max_structured_retries: int = Field(default=3, ge=1, le=10)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    fallback_profile: str | None = None


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    profiles: dict[str, ModelProfile] = Field(min_length=1)
    default_profile: str | None = None
    roles: dict[ModelRole, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references_are_complete(self) -> "ModelConfig":
        missing = [role.value for role in ModelRole if role not in self.roles]
        if missing and self.default_profile is None:
            # Falling back to LLM_* here could quietly send real work to the mock provider.
            raise ValueError(f"Set default_profile, or map these roles: {', '.join(missing)}.")
        referenced = {*self.roles.values(), self.default_profile} - {None}
        for name in sorted(referenced):
            if name not in self.profiles:
                raise ValueError(f"Profile '{name}' is referenced but not defined.")
        for name, profile in self.profiles.items():
            self._check_fallback(name, profile)
        return self

    def _check_fallback(self, name: str, profile: ModelProfile) -> None:
        target_name = profile.fallback_profile
        if target_name is None:
            return
        target = self.profiles.get(target_name)
        if target is None:
            raise ValueError(f"Profile '{name}' falls back to undefined profile '{target_name}'.")
        if target_name == name or target.fallback_profile is not None:
            raise ValueError(f"Profile '{name}' must fall back to a profile with no fallback of its own.")
        if ProviderType.MOCK in (profile.provider, target.provider):
            raise ValueError(f"Profile '{name}' cannot fall back to or from the mock provider.")

    def profile_name_for(self, role: ModelRole) -> str:
        return self.roles.get(role, self.default_profile)

    def referenced_profiles(self) -> list[str]:
        """Profiles the workflow can reach, so an unused profile needs no credential."""
        names = {self.profile_name_for(role) for role in ModelRole}
        names |= {self.profiles[name].fallback_profile for name in names} - {None}
        return sorted(names)


def legacy_model_config(settings: Settings) -> ModelConfig:
    """The global LLM_* settings, as one profile that serves every role."""
    if settings.llm_provider == "mock":
        profile = ModelProfile(provider=ProviderType.MOCK)
    else:
        if not settings.llm_api_key or not settings.llm_model:
            raise ProviderNotConfiguredError(
                "The real LLM provider needs LLM_API_KEY and LLM_MODEL. "
                "Set them in .env, or set LLM_PROVIDER=mock for offline use."
            )
        profile = legacy_llm_profile(settings)
    return ModelConfig(profiles={LEGACY_PROFILE: profile}, default_profile=LEGACY_PROFILE)


def legacy_llm_profile(settings: Settings) -> ModelProfile:
    return ModelProfile(
        provider=ProviderType.OPENAI_COMPATIBLE,
        model=settings.llm_model,
        credential_env=LEGACY_CREDENTIAL_ENV,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        structured_mode=settings.llm_structured_mode,
        max_structured_retries=settings.llm_max_structured_retries,
    )


def read_environment() -> dict[str, str]:
    """Process variables over the project .env, which Settings alone does not export."""
    from_file = dotenv_values(PROJECT_ROOT / ".env")
    return {**{key: value for key, value in from_file.items() if value}, **os.environ}


def load_model_config(path: Path, environ: Mapping[str, str]) -> ModelConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProviderNotConfiguredError(f"Could not read LLM_PROFILES_PATH file: {path}.") from error
    except yaml.YAMLError as error:
        # The parser's message can quote the file's contents, so it stays out of ours.
        raise ProviderNotConfiguredError(f"{path} is not valid YAML.") from error
    if not isinstance(raw, dict):
        raise ProviderNotConfiguredError(f"{path} must contain a mapping with profiles and roles.")
    for profile in (raw.get("profiles") or {}).values():
        if isinstance(profile, dict):
            _expand_references(profile, environ)
    try:
        return ModelConfig.model_validate(raw)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or 'file'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise ProviderNotConfiguredError(f"Invalid model configuration in {path}: {problems}") from error


def _expand_references(profile: dict, environ: Mapping[str, str]) -> None:
    # Limited to these fields: credential_env must stay a name, never become a value.
    for field in ("model", "base_url"):
        if isinstance(profile.get(field), str):
            profile[field] = _REFERENCE.sub(lambda match: _lookup(match[1], environ), profile[field])


def _lookup(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if not value:
        raise ProviderNotConfiguredError(f"The model configuration refers to {name}, which is not set.")
    return value
