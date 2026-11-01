"""Platform registry. Adding a platform means adding one adapter here."""

from app.publishing.base import PlatformAdapter
from app.publishing.facebook_adapter import FacebookAdapter
from app.publishing.instagram_adapter import InstagramAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {
    adapter.platform: adapter for adapter in (InstagramAdapter(), FacebookAdapter())
}


def supported_platforms() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(platform: str) -> PlatformAdapter:
    return _ADAPTERS[platform]
