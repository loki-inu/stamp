"""Fetching pages and tidying URLs."""

from __future__ import annotations

import gzip
import re
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
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


# ---------------------------------------------------------------- titles

class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.og_title: str | None = None
        self._in_title = False
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and self.og_title is None:
            a = dict(attrs)
            if (a.get("property") or a.get("name") or "").lower() in ("og:title", "twitter:title"):
                content = (a.get("content") or "").strip()
                if content:
                    self.og_title = content
        elif tag == "body":
            self._done = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._in_title and not self._done:
            self.title_parts.append(data)


def _charset_of(content_type: str, body: bytes) -> str:
    m = re.search(r"charset=[\"']?([\w-]+)", content_type, re.IGNORECASE)
    if m:
        return m.group(1)
    head = body[:4096]
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", head, re.IGNORECASE)
    if m:
        return m.group(1).decode("ascii", "replace")
    return "utf-8"


def extract_title(body: bytes, content_type: str = "text/html") -> str | None:
    """Best-effort page title from HTML bytes, or ``None``."""
    if body[:5].lower() not in (b"<!doc", b"<html") and b"<title" not in body[:65536].lower():
        return None
    try:
        text = body[:512 * 1024].decode(_charset_of(content_type, body), errors="replace")
    except LookupError:
        text = body[:512 * 1024].decode("utf-8", errors="replace")
    parser = _TitleParser()
    try:
        parser.feed(text)
    except Exception:  # noqa: BLE001 - malformed markup should never sink a stamp
        pass
    title = " ".join("".join(parser.title_parts).split())
    if not title and parser.og_title:
        title = " ".join(parser.og_title.split())
    return title or None
