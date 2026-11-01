import json
from typing import Any

from pydantic import BaseModel

from app.ai.prompts import Prompt, load_prompt
from app.ai.providers.model_config import ModelRole
from app.publishing.base import PlatformAdapter, SlideExport


class InstagramAdapter(PlatformAdapter):
    platform = "instagram"
    model_role = ModelRole.INSTAGRAM_ADAPTATION

    @property
    def prompt(self) -> Prompt:
        return load_prompt("instagram_adapter")

    async def adapt(self, llm, context, master, *, feedback=None) -> BaseModel:
        return await llm.adapt_instagram(context, master=master, feedback=feedback)

    def finalize_payload(self, payload: dict[str, Any], slides: list[SlideExport]) -> dict[str, Any]:
        return {
            **payload,
            "platform": self.platform,
            "carousel_slide_ids": [slide.asset_id for slide in slides],
            "alt_text": {str(slide.slide_number): slide.alt_text for slide in slides},
        }

    def package_files(self, payload, slides, *, combined=False) -> dict[str, bytes]:
        hashtags = " ".join(payload["hashtags"])
        caption = f"{payload['caption']}\n\n{payload['call_to_action']}\n"
        files = {
            "caption.txt": caption.encode("utf-8"),
            "hashtags.txt": f"{hashtags}\n".encode(),
            "alt_text.json": json.dumps(
                {f"slide_{s.slide_number:02d}.jpg": s.alt_text for s in slides}, indent=2
            ).encode("utf-8"),
        }
        files.update({f"slide_{s.slide_number:02d}.jpg": s.data for s in slides})
        return files
