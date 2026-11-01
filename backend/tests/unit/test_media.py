"""Rendering, storage safety, upload validation and platform packaging."""

import hashlib
import io
import json
import struct
import zlib

import pytest
from PIL import Image

from app.ai.providers.mock_provider import MockImageProvider
from app.core.exceptions import MediaError
from app.media.renderer import SlideRenderInput, encode_jpeg, render_slide
from app.media.specs import CAROUSEL_SPEC
from app.media.storage import LocalStorage, validate_upload_image
from app.publishing import get_adapter, supported_platforms
from app.publishing.base import SlideExport
from tests.conftest import png_bytes

LIMITS = {"max_bytes": 1_000_000, "max_pixels": 1_000_000}


def _slide(**overrides) -> SlideRenderInput:
    values = {
        "headline": "Is Your Indoor Cat Getting Bored?",
        "supporting_text": "Simple ideas for better play.",
        "layout": "cover",
        "brand_name": "Paws & Play",
        "background": png_bytes((400, 400)),
    }
    return SlideRenderInput(**{**values, **overrides})


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


class TestRenderer:
    @pytest.mark.parametrize("layout", ["cover", "content"])
    def test_output_is_a_valid_jpeg_with_platform_dimensions(self, layout):
        image = _open(render_slide(_slide(layout=layout)))
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (CAROUSEL_SPEC.width, CAROUSEL_SPEC.height) == (1080, 1350)

    def test_layouts_are_visually_different(self):
        assert render_slide(_slide(layout="cover")) != render_slide(_slide(layout="content"))

    def test_text_is_actually_drawn(self):
        assert render_slide(_slide(headline="First headline")) != render_slide(_slide(headline="Other words"))

    def test_rendering_is_deterministic(self):
        assert render_slide(_slide()) == render_slide(_slide())

    @pytest.mark.parametrize("layout", ["cover", "content"])
    def test_extremely_long_text_does_not_crash(self, layout):
        slide = _slide(layout=layout, headline="Long headline " * 40, supporting_text="supercalifragilistic" * 40)
        assert _open(render_slide(slide)).size == (1080, 1350)

    def test_product_photo_changes_the_slide(self):
        without = render_slide(_slide(layout="content"))
        with_photo = render_slide(_slide(layout="content", product_image=png_bytes((300, 500), (10, 200, 90))))
        assert without != with_photo

    def test_no_background_uses_a_fallback(self):
        assert _open(render_slide(_slide(background=None))).size == (1080, 1350)

    def test_transparent_inputs_and_logo_are_supported(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (100, 100), (255, 0, 0, 128)).save(buffer, format="PNG")
        data = buffer.getvalue()
        assert _open(render_slide(_slide(layout="content", product_image=data, logo=data))).mode == "RGB"

    def test_output_size_limit_is_enforced(self):
        with pytest.raises(MediaError):
            encode_jpeg(Image.effect_noise((400, 400), 100).convert("RGB"), max_bytes=100)

    async def test_mock_background_depends_only_on_prompt(self):
        provider = MockImageProvider()
        first = await provider.generate_background("scene a", width=108, height=135)
        again = await provider.generate_background("scene a", width=108, height=135)
        other = await provider.generate_background("scene b", width=108, height=135)
        assert first.data == again.data != other.data
        assert first.is_mock


class TestStorage:
    @pytest.fixture
    def storage(self, tmp_path) -> LocalStorage:
        return LocalStorage(tmp_path)

    def test_round_trip(self, storage):
        storage.save_bytes("generated/a/b.jpg", b"data")
        assert storage.read_bytes("generated/a/b.jpg") == b"data"
        assert storage.exists("generated/a/b.jpg")

    @pytest.mark.parametrize("key", ["../outside.txt", "a/../../outside.txt", "..\\outside.txt", ""])
    def test_paths_outside_the_root_are_refused(self, storage, key):
        with pytest.raises(MediaError):
            storage.path_for(key)

    def test_absolute_paths_are_refused(self, storage, tmp_path):
        with pytest.raises(MediaError):
            storage.path_for(str(tmp_path.parent / "outside.txt"))

    def test_failed_write_leaves_no_partial_file(self, storage, monkeypatch):
        import app.media.storage as module

        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr(module.os, "replace", fail)
        with pytest.raises(OSError):
            storage.save_bytes("generated/x.jpg", b"data")
        assert list((storage.root / "generated").iterdir()) == []


def _png_declaring_size(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims huge dimensions, like a decompression bomb."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload)
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\0")) + chunk(b"IEND", b"")


class TestUploadValidation:
    def test_accepts_png_and_reports_dimensions(self):
        image = validate_upload_image(png_bytes((50, 40)), **LIMITS)
        assert (image.mime_type, image.extension, image.width, image.height) == ("image/png", "png", 50, 40)

    def test_rejects_empty_oversized_and_non_image(self):
        for data, code in [(b"", "EMPTY_UPLOAD"), (b"x" * 2_000_000, "UPLOAD_TOO_LARGE"), (b"<script>", "INVALID_IMAGE")]:
            with pytest.raises(MediaError) as caught:
                validate_upload_image(data, **LIMITS)
            assert caught.value.code == code

    def test_rejects_disallowed_format_even_if_it_is_an_image(self):
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buffer, format="GIF")
        with pytest.raises(MediaError) as caught:
            validate_upload_image(buffer.getvalue(), **LIMITS)
        assert caught.value.code == "UNSUPPORTED_IMAGE_TYPE"

    @pytest.mark.parametrize("side", [5_000, 50_000])
    def test_rejects_decompression_bombs_from_the_header(self, side):
        with pytest.raises(MediaError) as caught:
            validate_upload_image(_png_declaring_size(side, side), **LIMITS)
        assert caught.value.code == "IMAGE_TOO_LARGE"


SLIDES = [SlideExport(asset_id=f"a{n}", slide_number=n, alt_text=f"Alt {n}", data=b"jpeg") for n in (1, 2, 3, 4)]


class TestPlatformAdapters:
    def test_registry(self):
        assert supported_platforms() == ["facebook", "instagram"]

    def test_instagram_package(self):
        payload = {"caption": "Caption", "hashtags": ["#a", "#b"], "call_to_action": "Look"}
        files = get_adapter("instagram").package_files(payload, SLIDES)
        assert set(files) == {
            "caption.txt", "hashtags.txt", "alt_text.json",
            "slide_01.jpg", "slide_02.jpg", "slide_03.jpg", "slide_04.jpg",
        }
        assert files["hashtags.txt"].decode() == "#a #b\n"
        assert json.loads(files["alt_text.json"])["slide_02.jpg"] == "Alt 2"

    def test_instagram_finalize_links_slides_in_order(self):
        result = get_adapter("instagram").finalize_payload({"caption": "c"}, SLIDES)
        assert result["carousel_slide_ids"] == ["a1", "a2", "a3", "a4"]
        assert result["alt_text"]["3"] == "Alt 3"

    def test_facebook_package_layouts(self):
        adapter = get_adapter("facebook")
        standalone = adapter.package_files({"post_text": "Post"}, SLIDES)
        assert "image_01.jpg" in standalone and standalone["post.txt"].decode() == "Post\n"
        assert "images/image_04.jpg" in adapter.package_files({"post_text": "Post"}, SLIDES, combined=True)

    def test_facebook_finalize_links_images(self):
        assert get_adapter("facebook").finalize_payload({}, SLIDES)["image_asset_ids"] == ["a1", "a2", "a3", "a4"]

    def test_slide_bytes_pass_through_unchanged(self):
        data = {f: hashlib.sha256(b).hexdigest() for f, b in get_adapter("facebook").package_files({"post_text": "P"}, SLIDES).items()}
        assert data["image_01.jpg"] == hashlib.sha256(b"jpeg").hexdigest()
