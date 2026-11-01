"""Common platform adapter interface.

An adapter turns approved content into one platform's format and export files.
It does not run the workflow, and Phase 1 adapters do not publish. Actual posting
can later be added as another method on this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.ai.prompts import Prompt
from app.ai.providers.llm_provider import LLMProvider
from app.ai.providers.model_config import ModelRole
from app.schemas.content import GenerationContext, MasterCopy


@dataclass(frozen=True)
class SlideExport:
    """One approved image plus the text that belongs to it."""

    asset_id: str
    slide_number: int
    alt_text: str
    data: bytes


class PlatformAdapter(ABC):
    platform: str
    model_role: ModelRole

    @property
    @abstractmethod
    def prompt(self) -> Prompt: ...

    @abstractmethod
    async def adapt(
        self,
        llm: LLMProvider,
        context: GenerationContext,
        master: MasterCopy,
        *,
        feedback: str | None = None,
    ) -> BaseModel:
        """Generate platform copy from the approved draft."""

    @abstractmethod
    def finalize_payload(self, payload: dict[str, Any], slides: list[SlideExport]) -> dict[str, Any]:
        """Add references to the final images once they are approved."""

    @abstractmethod
    def package_files(
        self, payload: dict[str, Any], slides: list[SlideExport], *, combined: bool = False
    ) -> dict[str, bytes]:
        """Files for this platform's export, keyed by path relative to the platform folder."""
