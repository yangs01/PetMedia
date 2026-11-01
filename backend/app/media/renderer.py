"""Composes final slides with Pillow.

Text is drawn here, not by the image model, so it is always readable and spelled
correctly. Product images are the operator's real uploads, placed unmodified
apart from scaling.

The default font is Aileron, which ships inside Pillow and needs no system font.
Pillow bundles only its regular weight, so headlines are thickened with a stroke.
"""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.core.exceptions import MediaError
from app.media.specs import CAROUSEL_SPEC, MediaSpec

WHITE = (255, 255, 255)
INK = (34, 38, 46)
MUTED = (84, 90, 102)
PANEL = (255, 255, 255)
JPEG_QUALITIES = (92, 88, 82, 76, 68, 60)


@dataclass(frozen=True)
class SlideRenderInput:
    headline: str
    supporting_text: str
    layout: str  # "cover" or "content"
    brand_name: str
    background: bytes | None = None
    product_image: bytes | None = None
    logo: bytes | None = None


def _load_font(size: int, font_path: Path | None) -> ImageFont.FreeTypeFont:
    if font_path:
        try:
            return ImageFont.truetype(str(font_path), size)
        except OSError as error:
            raise MediaError(f"Could not load the font at FONT_PATH: {font_path.name}.", code="FONT_ERROR") from error
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            # A single word wider than the line is broken by characters.
            while draw.textlength(word, font=font) > max_width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


def _ellipsize(draw: ImageDraw.ImageDraw, line: str, font, max_width: int) -> str:
    candidate = line.rstrip()
    while candidate and draw.textlength(f"{candidate}...", font=font) > max_width:
        candidate = candidate[:-1].rstrip()
    return f"{candidate}..."


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_height: int,
    max_size: int,
    min_size: int,
    font_path: Path | None,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Use the largest size that fits; at the minimum size, truncate with an ellipsis."""
    size = max_size
    while True:
        font = _load_font(size, font_path)
        line_height = int(size * 1.25)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) * line_height <= max_height:
            return font, lines, line_height
        if size <= min_size:
            keep = max(1, max_height // line_height)
            kept = lines[:keep]
            kept[-1] = _ellipsize(draw, kept[-1], font, max_width)
            return font, kept, line_height
        size = max(min_size, size - 4)


def _draw_lines(draw, lines, font, *, x, y, line_height, fill, stroke=0) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
        y += line_height
    return y


def _open_rgb(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        return ImageOps.exif_transpose(image).convert("RGBA").convert("RGB")


def _background(data: bytes | None, spec: MediaSpec) -> Image.Image:
    if data is None:
        return Image.new("RGB", (spec.width, spec.height), (232, 226, 215))
    return ImageOps.fit(_open_rgb(data), (spec.width, spec.height), Image.Resampling.LANCZOS)


def _place_logo(canvas: Image.Image, logo: bytes | None, spec: MediaSpec) -> None:
    if not logo:
        return
    with Image.open(io.BytesIO(logo)) as image:
        mark = image.convert("RGBA")
    mark.thumbnail((180, 90), Image.Resampling.LANCZOS)
    canvas.paste(mark, (spec.width - spec.safe_margin - mark.width, spec.safe_margin), mark)


def _render_cover(slide: SlideRenderInput, spec: MediaSpec, font_path: Path | None) -> Image.Image:
    canvas = _background(slide.background, spec)
    # A translucent panel keeps text legible over any generated image.
    panel_top = int(spec.height * 0.52)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle((0, panel_top, spec.width, spec.height), fill=(20, 22, 28, 190))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    margin = spec.safe_margin
    width = spec.width - 2 * margin

    font, lines, line_height = _fit_text(
        draw, slide.headline, max_width=width, max_height=330, max_size=84, min_size=44, font_path=font_path
    )
    y = _draw_lines(draw, lines, font, x=margin, y=panel_top + 50, line_height=line_height, fill=WHITE, stroke=1)
    if slide.supporting_text:
        font, lines, line_height = _fit_text(
            draw, slide.supporting_text, max_width=width, max_height=130, max_size=40, min_size=26, font_path=font_path
        )
        _draw_lines(draw, lines, font, x=margin, y=y + 20, line_height=line_height, fill=(225, 228, 232))
    draw.text((margin, spec.height - margin), slide.brand_name, font=_load_font(32, font_path), fill=WHITE, anchor="ls")
    _place_logo(canvas, slide.logo, spec)
    return canvas


def _render_content(slide: SlideRenderInput, spec: MediaSpec, font_path: Path | None) -> Image.Image:
    # Softened background: slide text and any product photo stay the focus.
    canvas = _background(slide.background, spec).filter(ImageFilter.GaussianBlur(6))
    canvas = ImageEnhance.Brightness(canvas).enhance(1.05)
    draw = ImageDraw.Draw(canvas)
    margin = spec.safe_margin
    has_product = slide.product_image is not None

    panel_top = int(spec.height * (0.56 if has_product else 0.44))
    panel_bottom = spec.height - margin
    draw.rounded_rectangle((margin - 30, panel_top, spec.width - margin + 30, panel_bottom), radius=28, fill=PANEL)

    if has_product:
        photo = _open_rgb(slide.product_image)
        photo_area = (spec.width - 2 * margin, panel_top - margin - 40)
        photo = ImageOps.contain(photo, photo_area, Image.Resampling.LANCZOS)
        frame_x = (spec.width - photo.width) // 2
        frame_y = margin + (photo_area[1] - photo.height) // 2
        draw.rounded_rectangle(
            (frame_x - 16, frame_y - 16, frame_x + photo.width + 16, frame_y + photo.height + 16), radius=16, fill=WHITE
        )
        canvas.paste(photo, (frame_x, frame_y))

    text_x = margin + 10
    text_width = spec.width - 2 * margin - 20
    available = panel_bottom - panel_top - 150
    headline_height = int(available * (0.42 if slide.supporting_text else 0.9))
    font, lines, line_height = _fit_text(
        draw, slide.headline, max_width=text_width, max_height=headline_height, max_size=68, min_size=38, font_path=font_path
    )
    y = _draw_lines(draw, lines, font, x=text_x, y=panel_top + 44, line_height=line_height, fill=INK, stroke=1)
    if slide.supporting_text:
        remaining = panel_bottom - y - 100
        font, lines, line_height = _fit_text(
            draw, slide.supporting_text, max_width=text_width, max_height=remaining, max_size=40, min_size=26, font_path=font_path
        )
        _draw_lines(draw, lines, font, x=text_x, y=y + 16, line_height=line_height, fill=MUTED)
    draw.text((text_x, panel_bottom - 34), slide.brand_name, font=_load_font(28, font_path), fill=MUTED, anchor="ls")
    _place_logo(canvas, slide.logo, spec)
    return canvas


def encode_jpeg(image: Image.Image, *, max_bytes: int) -> bytes:
    """Encode as baseline-compatible RGB JPEG, lowering quality only as needed for the limit."""
    for quality in JPEG_QUALITIES:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()
    raise MediaError("The rendered image exceeds the output size limit.", code="OUTPUT_TOO_LARGE")


def render_slide(
    slide: SlideRenderInput,
    *,
    spec: MediaSpec = CAROUSEL_SPEC,
    font_path: Path | None = None,
    max_bytes: int = 8_000_000,
) -> bytes:
    """Render one slide to JPEG bytes. CPU-bound: call through ``asyncio.to_thread``."""
    render = _render_cover if slide.layout == "cover" else _render_content
    return encode_jpeg(render(slide, spec, font_path), max_bytes=max_bytes)
