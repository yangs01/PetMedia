"""File storage and upload validation.

The database holds only keys relative to the storage root. The ``Storage``
interface is the seam for moving to object storage later.
"""

import io
import os
import warnings
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.core.exceptions import MediaError, MediaFileMissingError

STORAGE_FOLDERS = ("products", "generated", "exports", "brands")
ALLOWED_IMAGE_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}


class Storage(Protocol):
    def save_bytes(self, key: str, data: bytes) -> str: ...
    def read_bytes(self, key: str) -> bytes: ...
    def path_for(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def ensure_layout(self) -> None:
        for folder in STORAGE_FOLDERS:
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        """Resolve a key, refusing anything that points outside the storage root."""
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise MediaError("Invalid storage path.", code="INVALID_STORAGE_PATH")
        return path

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def save_bytes(self, key: str, data: bytes) -> str:
        """Write through a temporary file so a crash never leaves a partial file at ``key``."""
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temp_path.write_bytes(data)
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        return key

    def read_bytes(self, key: str) -> bytes:
        path = self.path_for(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise MediaFileMissingError("A stored media file is missing.", details={"key": key}) from error


class ValidatedImage:
    def __init__(self, mime_type: str, extension: str, width: int, height: int) -> None:
        self.mime_type = mime_type
        self.extension = extension
        self.width = width
        self.height = height


def validate_upload_image(data: bytes, *, max_bytes: int, max_pixels: int) -> ValidatedImage:
    """Trust the file's content, never its name or declared type."""
    if not data:
        raise MediaError("The uploaded file is empty.", code="EMPTY_UPLOAD")
    if len(data) > max_bytes:
        raise MediaError(
            f"The uploaded file exceeds the {max_bytes}-byte limit.",
            code="UPLOAD_TOO_LARGE",
            details={"max_bytes": max_bytes},
        )
    try:
        # Reading the header does not decode pixels, so a decompression bomb
        # is rejected on its declared size before it can use any memory.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image_format, width, height = image.format, image.width, image.height
                if image_format not in ALLOWED_IMAGE_FORMATS:
                    raise MediaError(
                        "Only JPEG, PNG and WebP images are accepted.",
                        code="UNSUPPORTED_IMAGE_TYPE",
                        details={"detected_format": image_format},
                    )
                if width * height > max_pixels:
                    raise MediaError("The image dimensions are too large.", code="IMAGE_TOO_LARGE")
                image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise MediaError("The image dimensions are too large.", code="IMAGE_TOO_LARGE") from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise MediaError("The uploaded file is not a valid image.", code="INVALID_IMAGE") from error
    mime_type, extension = ALLOWED_IMAGE_FORMATS[image_format]
    return ValidatedImage(mime_type, extension, width, height)
