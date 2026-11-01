from typing import Any

from pydantic import BaseModel

from app.ai.prompts import Prompt, load_prompt
from app.ai.providers.model_config import ModelRole
from app.publishing.base import PlatformAdapter, SlideExport


class FacebookAdapter(PlatformAdapter):
    platform = "facebook"
    model_role = ModelRole.FACEBOOK_ADAPTATION

    @property
    def prompt(self) -> Prompt:
        return load_prompt("facebook_adapter")

    async def adapt(self, llm, context, master, *, feedback=None) -> BaseModel:
        return await llm.adapt_facebook(context, master=master, feedback=feedback)

    def finalize_payload(self, payload: dict[str, Any], slides: list[SlideExport]) -> dict[str, Any]:
        return {
            **payload,
            "platform": self.platform,
            "image_asset_ids": [slide.asset_id for slide in slides],
        }

    def package_files(self, payload, slides, *, combined=False) -> dict[str, bytes]:
        image_folder = "images/" if combined else ""
        files = {"post.txt": f"{payload['post_text']}\n".encode()}
        files.update({f"{image_folder}image_{s.slide_number:02d}.jpg": s.data for s in slides})
        return files
