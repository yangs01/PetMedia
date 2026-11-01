"""Image provider interface and the OpenAI-compatible implementation.

Providers only create background or lifestyle art. Real product photos and all
text are added afterwards by the renderer, so no product appearance is ever invented.
"""

import base64
import binascii
import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.exceptions import (
    ProviderNotConfiguredError,
    ProviderPermanentError,
    ProviderTransientError,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    provider: str
    is_mock: bool = False


class ImageProvider(ABC):
    name: str

    @abstractmethod
    async def generate_background(self, prompt: str, *, width: int, height: int) -> GeneratedImage:
        """Create art for the given final dimensions. The renderer crops it to fit."""


class OpenAICompatibleImageProvider(ImageProvider):
    """Calls ``POST {IMAGE_BASE_URL}/images/generations``; accepts base64 or URL responses."""

    name = "openai_compatible"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        api_key = settings.image_api_key.get_secret_value() if settings.image_api_key else ""
        if not api_key or not settings.image_model:
            raise ProviderNotConfiguredError(
                "The real image provider needs IMAGE_API_KEY and IMAGE_MODEL. "
                "Set them in .env, or set IMAGE_PROVIDER=mock for offline use."
            )
        self._model = settings.image_model
        self._size = settings.image_size
        self._client = httpx.AsyncClient(
            base_url=settings.image_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.image_timeout_seconds,
            transport=transport,
        )
        # Provider-returned file URLs are fetched without our API key attached.
        self._download_client = httpx.AsyncClient(
            timeout=settings.image_timeout_seconds, transport=transport, follow_redirects=True
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._download_client.aclose()

    async def generate_background(self, prompt: str, *, width: int, height: int) -> GeneratedImage:
        body = {"model": self._model, "prompt": prompt, "size": self._size, "n": 1}
        started = perf_counter()
        response = await self._send(lambda: self._client.post("images/generations", json=body))
        logger.info(
            "Image generation finished",
            extra={
                "provider": self.name,
                "operation": "generate_background",
                "status_code": response.status_code,
                "duration": round(perf_counter() - started, 3),
            },
        )
        data = await self._extract_bytes(response)
        _ensure_decodable(data)
        return GeneratedImage(data=data, provider=f"{self.name}:{self._model}")

    async def _send(self, request) -> httpx.Response:
        try:
            response = await request()
        except httpx.TimeoutException as error:
            raise ProviderTransientError("The image request timed out.") from error
        except httpx.TransportError as error:
            raise ProviderTransientError(f"Could not reach the image API: {type(error).__name__}.") from error
        if response.status_code in RETRYABLE_STATUS:
            raise ProviderTransientError(f"The image API returned HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise ProviderPermanentError(
                f"The image API rejected the request with HTTP {response.status_code}.",
                details={"response": response.text[:500]},
            )
        return response

    async def _extract_bytes(self, response: httpx.Response) -> bytes:
        try:
            item: dict[str, Any] = response.json()["data"][0]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderPermanentError("The image API response had an unexpected shape.") from error
        if item.get("b64_json"):
            try:
                return base64.b64decode(item["b64_json"], validate=True)
            except (binascii.Error, ValueError) as error:
                raise ProviderPermanentError("The image API returned invalid base64 data.") from error
        url = item.get("url")
        if url:
            if not str(url).startswith("https://"):
                raise ProviderPermanentError("The image API returned a non-HTTPS image URL.")
            download = await self._send(lambda: self._download_client.get(url))
            if len(download.content) > MAX_DOWNLOAD_BYTES:
                raise ProviderPermanentError("The generated image is too large to download.")
            return download.content
        raise ProviderPermanentError("The image API response contained no image.")


def _ensure_decodable(data: bytes) -> None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise ProviderPermanentError("The image API returned data that is not a valid image.") from error
