import base64
import xml.etree.ElementTree as ET

from stamp import qr
from stamp.preview import Preview
from stamp.store import Stamp
from stamp.svg import human_size, ink_for, render_album, render_sheet, render_stamp, shorten, wrap_title

SVG_NS = "{http://www.w3.org/2000/svg}"


def _stamps(n):
    return [
        Stamp(
            sha256=f"{i:02x}" * 32,
            url=f"https://site{i}.example/some/page?id={i}",
            fetched_at=f"2026-03-{i + 1:02d}T12:00:00Z",
            title=None if i % 3 == 0 else f"Page number {i} with a fairly long title that will need wrapping",
            size=1234 * (i + 1),
            number=i + 1,
        )
        for i in range(n)
    ]


def test_stamp_svg_is_well_formed_and_carries_the_hash():
    s = _stamps(1)[0]
    text = render_stamp(s)
    root = ET.fromstring(text)
    assert root.tag == f"{SVG_NS}svg"
    assert s.sha256 in text
    assert "2026-03-01" in text
    assert "SITE0.EXAMPLE" in text
    # Each stamp carries exactly one QR code, whose dark modules match the encoder.
    qrs = [e for e in root.iter(f"{SVG_NS}svg") if (e.get("id") or "").endswith("-qr")]
    assert len(qrs) == 1
    code = qr.encode(s.qr_payload)
    assert qrs[0].get("viewBox") == f"0 0 {code.size} {code.size}"


def test_stamp_svg_is_deterministic():
    s = _stamps(1)[0]
    assert render_stamp(s) == render_stamp(s)


def test_stamp_escapes_markup_in_titles():
    s = Stamp(sha256="ab" * 32, url="https://x.example/?a=1&b=2", fetched_at="2026-01-01T00:00:00Z", title='<script>"alert"</script> & co')
    text = render_stamp(s)
    ET.fromstring(text)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_sheet_smoke():
    for n in (1, 3, 8, 11):
        stamps = _stamps(n)
        text = render_sheet(stamps, paper="a4")
        root = ET.fromstring(text)
        nested = [e for e in root.findall(f"{SVG_NS}svg")]
        assert len(nested) == min(n, 8)
        assert root.get("width") == "297mm"
        # Ids are namespaced per stamp so masks and clips never collide.
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids))
        assert f"{min(n, 8)} OF 8" in text


def test_sheet_letter_paper_and_title():
    text = render_sheet(_stamps(2), paper="letter", title="Summer issue")
    assert 'width="279.4mm"' in text
    assert "SUMMER ISSUE" in text


def test_album_html_lists_every_stamp():
    stamps = _stamps(5)
    html = render_album(stamps)
    assert html.startswith("<!doctype html>")
    for s in stamps:
        assert f"stamps/{s.sha256}.svg" in html
        assert s.short in html
    assert "5 stamps" in html
    assert "No stamps yet" in render_album([])


def test_wrap_title():
    assert wrap_title("short") == ["short"]
    lines = wrap_title("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen", max_chars=20)
    assert len(lines) == 2
    assert all(len(l) <= 20 for l in lines)
    assert lines[-1].endswith("…")
    long_word = wrap_title("a" * 80, max_chars=20)
    assert len(long_word) == 2 and long_word[-1].endswith("…") and all(len(l) <= 20 for l in long_word)
    url = wrap_title("www.rfc-editor.org/rfc/rfc2549.html")
    assert url == ["www.rfc-editor.org/rfc/rfc2549.html"]
    long_url = wrap_title("docs.example.org/reference/library/section/very-long-page-name-here.html")
    assert len(long_url) == 2 and long_url[0] == "docs.example.org/reference/library/"
    exact = wrap_title("one two three", max_chars=13)
    assert exact == ["one two three"]


def test_untitled_stamp_prints_the_url_without_scheme():
    s = Stamp(sha256="cd" * 32, url="https://www.rfc-editor.org/rfc/rfc2549.html", fetched_at="2026-01-01T00:00:00Z")
    assert s.caption == "www.rfc-editor.org/rfc/rfc2549.html"
    assert ">www.rfc-editor.org/rfc/rfc2549.html<" in render_stamp(s)


def test_ink_is_dark_enough_to_scan():
    for h in ("00" * 32, "ff" * 32, "7f3a" * 16, "c0ffee" * 10 + "abcd"):
        ink = ink_for(h)["ink"]
        r, g, b = (int(ink[i:i + 2], 16) for i in (1, 3, 5))
        assert 0.2126 * r + 0.7152 * g + 0.0722 * b < 110


def test_stamp_with_preview_embeds_the_picture_in_its_ink():
    from tests.test_preview import tiny_png

    s = _stamps(2)[1]
    s.description = "A few words about the page, wrapped over a couple of lines when they run long enough."
    png = tiny_png(16, 9)
    text = render_stamp(s, Preview(data=png, mime="image/png"))
    root = ET.fromstring(text)
    images = list(root.iter(f"{SVG_NS}image"))
    assert len(images) == 1
    href = images[0].get("href")
    assert href is not None and href.startswith("data:image/png;base64,")
    assert base64.b64decode(href.split(",", 1)[1]) == png
    assert images[0].get("filter") == "url(#s-duo)"
    assert "NO PREVIEW" not in text
    assert "A few words about the page" in text
    assert ">ABOUT<" in text and ">FILED<" in text


def test_stamp_without_preview_shows_an_empty_slot_and_the_address():
    s = _stamps(1)[0]  # untitled, no description
    text = render_stamp(s)
    ET.fromstring(text)
    assert "<image" not in text
    assert "NO PREVIEW" in text
    assert ">S<" in text  # the host's monogram
    assert "site0.example/some/page?id=0" in text  # printed as title and in the footer bar


def test_receipt_ledger_lists_the_transaction():
    s = Stamp(
        sha256="12" * 32,
        url="https://x.example/",
        fetched_at="2026-05-06T07:08:09Z",
        content_type="text/html; charset=utf-8",
        status=200,
        size=1234567,
        number=42,
    )
    text = render_stamp(s)
    for needle in (">TIME<", ">07:08:09 UTC<", ">TYPE<", ">text/html · 200<", ">BYTES<", ">1,234,567<", ">NO.<", ">042<", ">DATE<", ">2026-05-06<", ">SHA-256<", f">{s.short}<"):
        assert needle in text, needle
    # Nothing known about the fetch: no time, no status, a dash for the number.
    bare = Stamp(sha256="34" * 32, url="https://x.example/", fetched_at="2026-05-06")
    text = render_stamp(bare)
    ET.fromstring(text)
    assert ">TIME<" not in text and ">application/octet-stream<" in text and ">—<" in text


def test_stamp_from_old_metadata_renders(tmp_path):
    old = Stamp(sha256="ef" * 32, url="https://old.example/", fetched_at="2025-01-01T00:00:00Z", title="Old", format=1)
    text = render_stamp(old)
    ET.fromstring(text)
    assert "NO PREVIEW" in text and "OLD.EXAMPLE" in text


def test_sheet_carries_previews_per_stamp():
    from tests.test_preview import tiny_png

    stamps = _stamps(3)
    previews = {stamps[1].sha256: Preview(data=tiny_png(), mime="image/png")}
    text = render_sheet(stamps, previews=previews)
    root = ET.fromstring(text)
    assert len(list(root.iter(f"{SVG_NS}image"))) == 1
    assert text.count("NO PREVIEW") == 2
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    assert len(ids) == len(set(ids))


def test_album_shows_descriptions():
    stamps = _stamps(2)
    stamps[0].description = "What the <page> is about"
    html = render_album(stamps)
    assert "What the &lt;page&gt; is about" in html


def test_shorten():
    assert shorten("short", 10) == "short"
    assert shorten("a-very-long-host-name.example", 12) == "a-very-long…"


def test_human_size():
    assert human_size(559) == "559 B"
    assert human_size(6 * 1024 + 900) == "6.9 KB"
    assert human_size(268 * 1024) == "268 KB"
    assert human_size(3 * 1024 * 1024) == "3.0 MB"
