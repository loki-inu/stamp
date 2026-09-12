"""Preparing a page's preview picture for the stamp.

The picture a page advertises (``og:image`` and friends) is shrunk to a
small greyscale JPEG so that it can be embedded in the stamp and filed in
the album without weighing either down. Shrinking needs Pillow, which is
optional::

    pip install 'stamp-philately[preview]'

Without Pillow, small PNG, JPEG, GIF and WebP pictures are embedded as
they came, and anything larger is skipped; the stamp then shows its
"no preview" slot instead.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass

try:  # optional dependency
    from PIL import Image, ImageOps

    HAVE_PIL = True
except ImportError:  # pragma: no cover - exercised by tests through monkeypatching
    Image = ImageOps = None  # type: ignore[assignment]
    HAVE_PIL = False

# Twice the size of the panel on the stamp, so it stays crisp when printed.
PREVIEW_W, PREVIEW_H = 496, 280
JPEG_QUALITY = 72
# Without Pillow we cannot shrink, so we only embed pictures that are already small.
RAW_EMBED_MAX = 320 * 1024
MAX_SOURCE_PIXELS = 40_000_000

_MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


@dataclass
class Preview:
    data: bytes
    mime: str
    width: int | None = None
    height: int | None = None

    @property
    def ext(self) -> str:
        return _MIME_EXT.get(self.mime, "img")


def sniff_mime(data: bytes) -> str | None:
    """The image type by magic number, or ``None`` for anything else."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_size(data: bytes, mime: str) -> tuple[int, int] | None:
    """Pixel dimensions read from the file header, for the common formats."""
    try:
        if mime == "image/png" and data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            return w, h
        if mime == "image/gif":
            w, h = struct.unpack("<HH", data[6:10])
            return w, h
        if mime == "image/jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + length
    except struct.error:
        return None
    return None


def prepare(data: bytes, content_type: str = "") -> Preview | None:
    """Turn fetched image bytes into something the stamp can carry.

    With Pillow: a ``PREVIEW_W`` × ``PREVIEW_H`` greyscale JPEG, cropped to
    fit. Without: the original bytes when they are a small, known raster.
    Returns ``None`` when the bytes are not a usable picture.
    """
    if not data:
        return None
    if HAVE_PIL:
        return _prepare_with_pillow(data)
    mime = sniff_mime(data)
    if mime is None or len(data) > RAW_EMBED_MAX:
        return None
    size = image_size(data, mime)
    return Preview(data=data, mime=mime, width=size[0] if size else None, height=size[1] if size else None)


def _prepare_with_pillow(data: bytes) -> Preview | None:
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > MAX_SOURCE_PIXELS or im.width < 8 or im.height < 8:
                return None
            im.load()
            # Transparent pictures (logos, mostly) go onto white paper, not black.
            if im.mode in ("RGBA", "LA", "P"):
                rgba = im.convert("RGBA")
                flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                flat.alpha_composite(rgba)
                im = flat
            grey = ImageOps.autocontrast(im.convert("L"), cutoff=1)
            target = PREVIEW_W / PREVIEW_H
            ratio = (grey.width / grey.height) / target
            if 0.7 <= ratio <= 1.45:
                # Near enough the panel's shape: crop to fill it, favouring the top.
                fitted = ImageOps.fit(grey, (PREVIEW_W, PREVIEW_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            else:
                # Tall or very wide pictures (covers, logos, banners) are shown
                # whole on white, which the stamp prints as paper.
                inner = ImageOps.contain(grey, (PREVIEW_W - 24, PREVIEW_H - 24), method=Image.Resampling.LANCZOS)
                fitted = Image.new("L", (PREVIEW_W, PREVIEW_H), 255)
                fitted.paste(inner, ((PREVIEW_W - inner.width) // 2, (PREVIEW_H - inner.height) // 2))
            out = io.BytesIO()
            fitted.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return Preview(data=out.getvalue(), mime="image/jpeg", width=PREVIEW_W, height=PREVIEW_H)
    except Exception:  # noqa: BLE001 - a broken picture is not a reason to refuse the stamp
        return None
