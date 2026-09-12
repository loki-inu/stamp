import xml.etree.ElementTree as ET

from stamp import qr
from stamp.store import Stamp
from stamp.svg import human_size, ink_for, render_album, render_sheet, render_stamp, wrap_title

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
        assert f"{min(n, 8)} of 8" in text


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
    assert len(long_url) == 2 and long_url[0] == "docs.example.org/reference/library/s"
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


def test_human_size():
    assert human_size(559) == "559 B"
    assert human_size(6 * 1024 + 900) == "6.9 KB"
    assert human_size(268 * 1024) == "268 KB"
    assert human_size(3 * 1024 * 1024) == "3.0 MB"
