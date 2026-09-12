"""Fetching pages and tidying URLs."""

from __future__ import annotations

import gzip
import re
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from . import __version__

USER_AGENT = f"stamp/{__version__} (+https://github.com/loki-inu/stamp)"
DEFAULT_TIMEOUT = 30
MAX_BYTES = 50 * 1024 * 1024

# Query parameters that only exist to follow the reader around.
_TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|igshid|yclid|_hsenc|_hsmi|ref_src|s_cid)$",
    re.IGNORECASE,
)
_DEFAULT_PORTS = {"http": "80", "https": "443"}


class URLError(ValueError):
    pass


def normalize_url(raw: str) -> str:
    """Canonical form of a URL, so the same page gets the same name.

    Adds ``https://`` when the scheme is missing, lowercases scheme and host,
    drops default ports, fragments and tracking parameters, and gives an
    empty path a single slash. The order of remaining query parameters is
    preserved; it may be meaningful.
    """
    url = raw.strip()
    if not url:
        raise URLError("empty URL")
    if "://" not in url:
        if url.startswith("//"):
            url = "https:" + url
        else:
            url = "https://" + url
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise URLError(f"unsupported scheme: {scheme!r} (only http and https)")
    host = (parts.hostname or "").lower()
    if not host:
        raise URLError(f"no host in URL: {raw!r}")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    netloc = host
    if parts.port is not None and str(parts.port) != _DEFAULT_PORTS[scheme]:
        netloc = f"{host}:{parts.port}"
    if parts.username:
        cred = parts.username + (f":{parts.password}" if parts.password else "")
        netloc = f"{cred}@{netloc}"
    path = parts.path or "/"
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)],
        safe="/:@,;~",
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


@dataclass
class Fetched:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes


def fetch(url: str, timeout: float = DEFAULT_TIMEOUT) -> Fetched:
    """GET ``url`` and return the exact bytes the server sent (decompressed)."""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en;q=0.9, *;q=0.5",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise URLError(f"response larger than {MAX_BYTES} bytes; refusing to stamp it")
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            try:
                body = zlib.decompress(body)
            except zlib.error:
                body = zlib.decompress(body, -zlib.MAX_WBITS)
        return Fetched(
            requested_url=url,
            final_url=resp.geturl(),
            status=resp.status,
            content_type=resp.headers.get("Content-Type", "application/octet-stream"),
            body=body,
        )


# -------------------------------------------------------------- previews

PREVIEW_TIMEOUT = 15
PREVIEW_MAX_BYTES = 12 * 1024 * 1024


def fetch_preview(url: str, timeout: float = PREVIEW_TIMEOUT) -> tuple[bytes, str]:
    """GET a page's preview image; returns ``(bytes, content_type)``.

    Raises on any failure. Callers treat a missing preview as ordinary; a
    stamp is never refused because a picture did not arrive.
    """
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
            "Accept-Language": "en;q=0.9, *;q=0.5",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read(PREVIEW_MAX_BYTES + 1)
        if len(body) > PREVIEW_MAX_BYTES:
            raise URLError(f"preview image larger than {PREVIEW_MAX_BYTES} bytes")
        if not body:
            raise URLError("empty preview image")
        return body, resp.headers.get("Content-Type", "application/octet-stream")


# ------------------------------------------------------------- page meta

DESCRIPTION_MAX = 600
_MIN_PARAGRAPH = 80
_MAX_PARAGRAPHS = 60
_SKIP_TEXT_IN = frozenset({"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside"})
_META_KEYS = {
    "og:title": "og_title",
    "twitter:title": "tw_title",
    "og:description": "og_description",
    "twitter:description": "tw_description",
    "description": "description",
    "og:image": "og_image",
    "og:image:url": "og_image",
    "og:image:secure_url": "og_image_secure",
    "twitter:image": "tw_image",
    "twitter:image:src": "tw_image",
    "og:site_name": "site_name",
}


@dataclass
class PageMeta:
    """What a page says about itself, best effort."""

    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    site_name: str | None = None


class _MetaParser(HTMLParser):
    """Reads the head for titles and meta tags, then the body for a paragraph."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.link_image: str | None = None
        self.paragraph: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._p_parts: list[str] | None = None
        self._paragraphs_seen = 0
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag in _SKIP_TEXT_IN:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = {k.lower(): v for k, v in attrs}
            key = _META_KEYS.get((a.get("property") or a.get("name") or "").strip().lower())
            content = " ".join((a.get("content") or "").split())
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "link" and self.link_image is None:
            a = {k.lower(): v for k, v in attrs}
            if "image_src" in (a.get("rel") or "").lower().split() and a.get("href"):
                self.link_image = a["href"].strip()
        elif tag == "p" and self.paragraph is None and not self._skip_depth:
            self._p_parts = []
        elif tag == "br" and self._p_parts is not None:
            self._p_parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TEXT_IN:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TEXT_IN:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "p" and self._p_parts is not None:
            text = " ".join("".join(self._p_parts).split())
            self._p_parts = None
            self._paragraphs_seen += 1
            if len(text) >= _MIN_PARAGRAPH:
                self.paragraph = text
                self._done = True
            elif self._paragraphs_seen >= _MAX_PARAGRAPHS:
                self._done = True

    def handle_data(self, data: str) -> None:
        if self._done or self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        elif self._p_parts is not None:
            self._p_parts.append(data)


def _charset_of(content_type: str, body: bytes) -> str:
    m = re.search(r"charset=[\"']?([\w-]+)", content_type, re.IGNORECASE)
    if m:
        return m.group(1)
    head = body[:4096]
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", head, re.IGNORECASE)
    if m:
        return m.group(1).decode("ascii", "replace")
    return "utf-8"


def _looks_like_html(body: bytes, content_type: str) -> bool:
    ct = content_type.split(";")[0].strip().lower()
    if ct in ("text/html", "application/xhtml+xml"):
        return True
    head = body[:65536].lower()
    return body[:5].lower() in (b"<!doc", b"<html") or b"<title" in head or b"<meta" in head


def _decode(body: bytes, content_type: str) -> str:
    chunk = body[:768 * 1024]
    try:
        return chunk.decode(_charset_of(content_type, body), errors="replace")
    except LookupError:
        return chunk.decode("utf-8", errors="replace")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-–") + "…"


def extract_meta(body: bytes, content_type: str = "text/html", base_url: str | None = None) -> PageMeta:
    """Title, description and preview image URL from HTML bytes.

    The description is the first of ``og:description``, the meta
    description, ``twitter:description`` and the first paragraph of body
    text that is long enough to say something. The image is the first of
    ``og:image``, ``twitter:image`` and ``<link rel=image_src>``, made
    absolute against ``base_url``. Anything missing is ``None``.
    """
    if not body or not _looks_like_html(body, content_type):
        return PageMeta()
    parser = _MetaParser()
    try:
        parser.feed(_decode(body, content_type))
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup should never sink a stamp
        pass
    m = parser.meta

    title = " ".join("".join(parser.title_parts).split()) or m.get("og_title") or m.get("tw_title")
    description = m.get("og_description") or m.get("description") or m.get("tw_description") or parser.paragraph
    if description:
        description = _clip(description, DESCRIPTION_MAX)

    image_url = None
    for candidate in (m.get("og_image_secure"), m.get("og_image"), m.get("tw_image"), parser.link_image):
        if not candidate or candidate.lower().startswith("data:"):
            continue
        absolute = urljoin(base_url, candidate) if base_url else candidate
        try:
            image_url = normalize_url(absolute)
        except URLError:
            continue
        break

    return PageMeta(title=title or None, description=description or None, image_url=image_url, site_name=m.get("site_name"))


def extract_title(body: bytes, content_type: str = "text/html") -> str | None:
    """Best-effort page title from HTML bytes, or ``None``."""
    return extract_meta(body, content_type).title
