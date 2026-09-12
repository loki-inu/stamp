from stamp.fetch import DESCRIPTION_MAX, extract_meta, extract_title, visible_text


def _page(head: str = "", body: str = "") -> bytes:
    return f"<!doctype html><html><head><title>T</title>{head}</head><body>{body}</body></html>".encode()


def test_description_prefers_open_graph():
    body = _page(
        '<meta name="description" content="meta says this">'
        '<meta property="og:description" content="  og says\n this ">'
        '<meta name="twitter:description" content="twitter says this">',
        "<p>" + "body paragraph " * 20 + "</p>",
    )
    assert extract_meta(body).description == "og says this"


def test_description_falls_back_to_meta_then_twitter():
    assert extract_meta(_page('<meta name="description" content="plain meta">')).description == "plain meta"
    assert extract_meta(_page('<meta name="twitter:description" content="tw">')).description == "tw"
    # MDN-style: open graph keys in name= rather than property=.
    assert extract_meta(_page('<meta name="og:description" content="named og">')).description == "named og"


def test_description_falls_back_to_first_meaningful_paragraph():
    long = "The Penny Black was the world's first adhesive postage stamp used in a public postal system."
    body = _page(
        "",
        "<nav><p>" + "navigation text that is long enough to count but lives in the nav " * 3 + "</p></nav>"
        '<p class="mw-empty-elt"></p><p>Short.</p>'
        "<script><p>" + "scripted " * 30 + "</p></script>"
        f"<p>{long[:40]}<b>{long[40:60]}</b><a href='#'>{long[60:]}</a></p>"
        "<p>" + "later paragraph " * 10 + "</p>",
    )
    assert extract_meta(body).description == long


def test_no_description_when_nothing_says_anything():
    assert extract_meta(_page("", "<p>Too short.</p>")).description is None
    assert extract_meta(b"", "text/html").description is None
    assert extract_meta(b"\x89PNG\r\n\x1a\n" + b"\0" * 64, "image/png") == extract_meta(b"")


def test_long_description_is_clipped_at_a_word():
    text = "word " * 300
    got = extract_meta(_page(f'<meta property="og:description" content="{text}">')).description
    assert got is not None and len(got) <= DESCRIPTION_MAX and got.endswith("word…")


def test_image_url_is_resolved_and_prioritised():
    body = _page(
        '<meta name="twitter:image" content="/tw.png">'
        '<meta property="og:image" content="//cdn.example.org/og.jpg?utm_source=x&v=2">'
        '<link rel="image_src" href="/link.png">'
    )
    m = extract_meta(body, base_url="https://site.example/some/page")
    assert m.image_url == "https://cdn.example.org/og.jpg?v=2"

    only_twitter = extract_meta(_page('<meta name="twitter:image:src" content="img/tw.png">'), base_url="https://site.example/a/b")
    assert only_twitter.image_url == "https://site.example/a/img/tw.png"

    only_link = extract_meta(_page('<link rel="icon image_src" href="/l.png">'), base_url="https://site.example/")
    assert only_link.image_url == "https://site.example/l.png"


def test_image_url_skips_data_uris_and_junk():
    body = _page('<meta property="og:image" content="data:image/png;base64,AAAA"><meta name="twitter:image" content="ftp://x/y.png">')
    assert extract_meta(body, base_url="https://site.example/").image_url is None
    assert extract_meta(_page()).image_url is None


def test_secure_url_beats_plain_og_image():
    body = _page(
        '<meta property="og:image" content="http://site.example/plain.jpg">'
        '<meta property="og:image:secure_url" content="https://site.example/secure.jpg">'
    )
    assert extract_meta(body).image_url == "https://site.example/secure.jpg"


def test_title_and_site_name():
    body = _page('<meta property="og:site_name" content="Site">')
    m = extract_meta(body)
    assert m.title == "T" and m.site_name == "Site"
    assert extract_title(body) == "T"
    untitled = b'<html><head><meta property="og:title" content="From OG"></head><body></body></html>'
    assert extract_title(untitled) == "From OG"
    assert extract_title(b"%PDF-1.7 not html at all", "application/pdf") is None


def test_icon_url_prefers_the_largest_raster_icon():
    body = _page(
        '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32">'
        '<link rel="icon" type="image/svg+xml" href="/icon.svg">'
        '<link rel="icon" href="/icon-192.png" sizes="192x192">'
        '<link rel="apple-touch-icon" href="/apple.png">'
    )
    m = extract_meta(body, base_url="https://site.example/x/")
    assert m.icon_url == "https://site.example/icon-192.png"
    assert m.image_url is None

    touch_only = extract_meta(_page('<link rel="apple-touch-icon" href="touch.png">'), base_url="https://site.example/a/")
    assert touch_only.icon_url == "https://site.example/a/touch.png"
    svg_only = extract_meta(_page('<link rel="icon" type="image/svg+xml" href="/icon.svg">'), base_url="https://site.example/")
    assert svg_only.icon_url is None
    assert extract_meta(_page()).icon_url is None


def test_visible_text_reads_like_the_page():
    body = _page(
        "<style>p{color:red}</style>",
        "<h1>Heading</h1><p>First <b>bold</b> paragraph.</p><script>var x = 1;</script>"
        "<ul><li>one</li><li>two</li></ul><div>tail</div>",
    )
    assert visible_text(body) == "T\nHeading\nFirst bold paragraph.\none\ntwo\ntail\n"
    assert visible_text(b"just some text\n", "text/plain") == "just some text\n"


def test_malformed_markup_does_not_raise():
    body = b"<!doctype html><html><head><title>Broken</title><meta property=og:description content=unquoted<p>" + b"<<<>>>" * 100
    m = extract_meta(body)
    assert m.title == "Broken"
