import pytest

from stamp.fetch import URLError, extract_title, host_of, normalize_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com", "https://example.com/"),
        ("HTTPS://Example.COM", "https://example.com/"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://example.com/a#section-2", "https://example.com/a"),
        ("https://example.com/a?utm_source=x&id=7&utm_medium=y", "https://example.com/a?id=7"),
        ("https://example.com/a?fbclid=abc", "https://example.com/a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?b=2&a=1"),
        ("  https://example.com/path/  ", "https://example.com/path/"),
        ("//example.com/x", "https://example.com/x"),
        ("https://example.com/a?q=caf%C3%A9", "https://example.com/a?q=caf%C3%A9"),
    ],
)
def test_normalize(raw, expected):
    assert normalize_url(raw) == expected


def test_normalize_is_idempotent():
    for raw in ("Example.com/A?utm_x=1&k=v#frag", "https://a.b.c:8080/d/e?f=g"):
        once = normalize_url(raw)
        assert normalize_url(once) == once


def test_rejects_other_schemes_and_empty():
    with pytest.raises(URLError):
        normalize_url("ftp://example.com/file")
    with pytest.raises(URLError):
        normalize_url("")
    with pytest.raises(URLError):
        normalize_url("https:///no-host")


def test_host_of_drops_www():
    assert host_of("https://www.example.com/x") == "example.com"
    assert host_of("https://blog.example.com/x") == "blog.example.com"


def test_extract_title():
    html = b"<html><head><meta charset='utf-8'><title>\n  Caf\xc3\xa9 &amp; Co  </title></head><body>x</body></html>"
    assert extract_title(html, "text/html") == "Caf\u00e9 & Co"


def test_extract_title_falls_back_to_og_title():
    html = b'<html><head><meta property="og:title" content="Open Graph Title"></head><body></body></html>'
    assert extract_title(html) == "Open Graph Title"


def test_extract_title_none_for_non_html():
    assert extract_title(b"\x89PNG\r\n\x1a\n....", "image/png") is None
    assert extract_title(b"just some text", "text/plain") is None
    assert extract_title(b"<html><head></head><body>no title</body></html>") is None
