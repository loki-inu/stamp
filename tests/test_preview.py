import io
import struct
import zlib

import pytest

from stamp import preview
from stamp.preview import PREVIEW_H, PREVIEW_W, RAW_EMBED_MAX, image_size, prepare, sniff_mime


def tiny_png(w: int = 4, h: int = 3, rgb=(200, 30, 30)) -> bytes:
    """A valid PNG built by hand, so these tests need no Pillow."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_sniff_and_size_from_headers():
    png = tiny_png(640, 480)
    assert sniff_mime(png) == "image/png"
    assert image_size(png, "image/png") == (640, 480)
    gif = b"GIF89a" + struct.pack("<HH", 12, 34) + b"\0" * 10
    assert sniff_mime(gif) == "image/gif"
    assert image_size(gif, "image/gif") == (12, 34)
    assert sniff_mime(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert sniff_mime(b"<!doctype html>") is None
    assert sniff_mime(b"") is None


def test_without_pillow_small_pictures_are_embedded_as_they_are(monkeypatch):
    monkeypatch.setattr(preview, "HAVE_PIL", False)
    png = tiny_png(160, 200)
    got = prepare(png, "image/png")
    assert got is not None
    assert got.data == png and got.mime == "image/png" and got.ext == "png"
    assert (got.width, got.height) == (160, 200)
    # A favicon-sized picture would only be blown up and blur: refused.
    assert prepare(tiny_png(32, 32), "image/png") is None


def test_without_pillow_large_or_unknown_pictures_are_skipped(monkeypatch):
    monkeypatch.setattr(preview, "HAVE_PIL", False)
    assert prepare(b"", "image/png") is None
    assert prepare(b"<html>not a picture</html>", "text/html") is None
    huge = tiny_png() + b"\0" * RAW_EMBED_MAX
    assert prepare(huge, "image/png") is None


@pytest.mark.skipif(not preview.HAVE_PIL, reason="Pillow not installed")
def test_with_pillow_pictures_become_small_grey_jpegs():
    from PIL import Image

    got = prepare(tiny_png(1200, 630, (10, 200, 50)), "image/png")
    assert got is not None and got.mime == "image/jpeg" and got.ext == "jpg"
    assert (got.width, got.height) == (PREVIEW_W, PREVIEW_H)
    assert sniff_mime(got.data) == "image/jpeg"
    assert len(got.data) < 40 * 1024
    with Image.open(io.BytesIO(got.data)) as im:
        assert im.size == (PREVIEW_W, PREVIEW_H)
        assert im.mode == "L"


@pytest.mark.skipif(not preview.HAVE_PIL, reason="Pillow not installed")
def test_with_pillow_tall_pictures_are_shown_whole_on_white():
    from PIL import Image

    got = prepare(tiny_png(300, 600, (0, 0, 0)), "image/png")
    assert got is not None
    with Image.open(io.BytesIO(got.data)) as im:
        # The picture sits in the middle; the sides are paper-white.
        assert im.getpixel((2, PREVIEW_H // 2)) > 240
        assert im.getpixel((PREVIEW_W // 2, PREVIEW_H // 2)) < 20


@pytest.mark.skipif(not preview.HAVE_PIL, reason="Pillow not installed")
def test_with_pillow_transparency_lands_on_white():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (600, 340), (0, 0, 0, 0)).save(buf, format="PNG")
    got = prepare(buf.getvalue(), "image/png")
    assert got is not None
    with Image.open(io.BytesIO(got.data)) as im:
        assert im.getpixel((PREVIEW_W // 2, PREVIEW_H // 2)) > 240


@pytest.mark.skipif(not preview.HAVE_PIL, reason="Pillow not installed")
def test_with_pillow_junk_is_not_a_picture():
    assert prepare(b"\xff\xd8\xff definitely not a jpeg", "image/jpeg") is None
    assert prepare(tiny_png(2, 2), "image/png") is None  # too small to mean anything
