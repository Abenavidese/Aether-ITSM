"""
Validation for images users attach (webhook tickets and the employee chat).

Only an inline data URI is accepted — a plain URL would be fetched by
whichever model provider receives it, i.e. an attacker-chosen URL requested
on our behalf. Beyond the URI shape, the decoded bytes must really be the
declared format (magic bytes) and fit the size cap, so a renamed HTML/SVG
file or a padded payload never reaches a model or the job queue.
"""
import base64
import binascii
import re

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# base64 grows data by 4/3; the prefix is a few dozen chars.
MAX_IMAGE_DATA_URI_CHARS = MAX_IMAGE_BYTES * 4 // 3 + 64

_DATA_URI = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$")


def _matches_format(fmt: str, data: bytes) -> bool:
    if fmt == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if fmt == "jpeg":
        return data.startswith(b"\xff\xd8\xff")
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def validate_image_data_uri(value: str | None) -> str | None:
    """Returns `value` unchanged if it is a real png/jpeg/webp image, raises ValueError otherwise."""
    if value is None:
        return None
    match = _DATA_URI.fullmatch(value)
    if not match:
        raise ValueError("image must be a data:image/(png|jpeg|webp);base64 URI")
    fmt, encoded = match.groups()
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image is not valid base64") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    if not _matches_format(fmt, data):
        raise ValueError(f"image content is not a real {fmt} file")
    return value
