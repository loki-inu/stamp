"""``stamp serve``: the album in a browser, and one-click stamping.

A small server on the loopback interface only. It shows the album page
live, takes URLs from a form or from a bookmarklet, and serves the sheet
ready to print. Nothing here is reachable from other machines, and every
request that makes a stamp must carry the token printed at start-up, so
that a web page you happen to be reading cannot stamp things into your
album behind your back.
"""

from __future__ import annotations

import json
import re
import secrets
import sys
import threading
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .actions import FetchFailed, stamp_url
from .fetch import URLError
from .store import Album, Ambiguous, NotFound, Stamp
from .svg import PAPER_SIZES_MM, human_size, render_album, render_sheet, render_sheet_page

DEFAULT_PORT = 7878
_STAMP_FILE = re.compile(r"^/stamps/([0-9a-f]{64})\.svg$")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class StampServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, album: Album, host: str = "127.0.0.1", port: int = DEFAULT_PORT, *, token: str | None = None, timeout: float = 30) -> None:
        super().__init__((host, port), _Handler)
        self.album = album
        self.token = token or secrets.token_urlsafe(9)
        self.timeout = timeout
        self.lock = threading.Lock()  # one stamp at a time, so album numbers stay unique

    @property
    def url(self) -> str:
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}"

    def bookmarklet(self) -> str:
        """A ``javascript:`` URL that stamps the page you are looking at."""
        add = f"{self.url}/add?popup=1&token={self.token}&url="
        return (
            "javascript:(function(){window.open("
            f"'{add}'+encodeURIComponent(location.href),'stamp',"
            "'width=460,height=760,menubar=no,toolbar=no,location=no');})();"
        )


class _Handler(BaseHTTPRequestHandler):
    server: StampServer  # type: ignore[assignment]
    server_version = f"stamp/{__version__}"
    sys_version = ""

    # ------------------------------------------------------------ plumbing

    def log_message(self, fmt: str, *args: object) -> None:
        # Only stamping is worth a line in the terminal.
        if self.path.startswith("/add"):
            sys.stderr.write(f"stamp: {fmt % args}\n")

    def _send(self, status: int, body: str | bytes, content_type: str = "text/html; charset=utf-8", extra: dict[str, str] | None = None) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _host_ok(self) -> bool:
        """Only answer when addressed as localhost, so DNS rebinding gets nothing."""
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):
            host = host[1:].split("]", 1)[0]
        elif host.count(":") == 1:
            host = host.rsplit(":", 1)[0]
        return host in _LOCAL_HOSTS

    def _wants_json(self, query: dict[str, list[str]]) -> bool:
        return query.get("format", [""])[0] == "json" or "application/json" in (self.headers.get("Accept") or "")

    # -------------------------------------------------------------- routes

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, _page("Refused", "<p>This album only answers to localhost.</p>"))
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/":
            return self._album(query)
        if path == "/add":
            return self._add(query.get("url", [""])[0], query.get("token", [""])[0], query)
        if m := _STAMP_FILE.match(path):
            return self._stamp_file(m.group(1))
        if path == "/sheet":
            return self._sheet(query, page=True)
        if path == "/sheet.svg":
            return self._sheet(query, page=False)
        if path == "/api/stamps":
            return self._api_stamps()
        if path == "/favicon.ico":
            return self._send(HTTPStatus.NOT_FOUND, b"", "image/x-icon")
        return self._send(HTTPStatus.NOT_FOUND, _page("Not found", f"<p>Nothing at <code>{escape(path)}</code>.</p>"))

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, _page("Refused", "<p>This album only answers to localhost.</p>"))
        parts = urlsplit(self.path)
        if parts.path != "/add":
            return self._send(HTTPStatus.NOT_FOUND, _page("Not found", "<p>POST only to <code>/add</code>.</p>"))
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 64 * 1024)).decode("utf-8", "replace")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        query = parse_qs(parts.query)
        if ctype == "application/json":
            try:
                data = json.loads(raw or "{}")
            except ValueError:
                data = {}
            form = {k: [str(v)] for k, v in data.items() if v is not None}
            query.setdefault("format", ["json"])
        else:
            form = parse_qs(raw)
        form.update(query)
        return self._add(form.get("url", [""])[0], form.get("token", [""])[0], form)

    # ------------------------------------------------------------- handlers

    def _album(self, query: dict[str, list[str]]) -> None:
        stamps = self.server.album.stamps()
        added = query.get("added", [None])[0]
        html = render_album(stamps, toolbar=_toolbar(self.server, added), highlight=added)
        self._send(HTTPStatus.OK, html)

    def _add(self, url: str, token: str, query: dict[str, list[str]]) -> None:
        popup = query.get("popup", ["0"])[0] == "1"
        as_json = self._wants_json(query)
        if not secrets.compare_digest(token, self.server.token):
            return self._respond(HTTPStatus.FORBIDDEN, "Refused", "The request did not carry this album's token. Drag a fresh bookmarklet from the album page.", None, popup, as_json)
        if not url.strip():
            return self._respond(HTTPStatus.BAD_REQUEST, "No URL", "Give me a URL to stamp.", None, popup, as_json)
        try:
            with self.server.lock:
                got = stamp_url(self.server.album, url, timeout=self.server.timeout)
        except URLError as e:
            return self._respond(HTTPStatus.BAD_REQUEST, "Not a page I can stamp", str(e), None, popup, as_json)
        except FetchFailed as e:
            return self._respond(HTTPStatus.BAD_GATEWAY, "Could not fetch", str(e), None, popup, as_json)
        heading = "Stamped" if got.created else "Already in the album"
        detail = "" if got.created else f"The same bytes were filed on {escape(got.stamp.date)}."
        self._respond(HTTPStatus.OK, heading, detail, got.stamp, popup, as_json, created=got.created, notes=got.notes)

    def _respond(self, status: int, heading: str, detail: str, stamp: Stamp | None, popup: bool, as_json: bool, *, created: bool = False, notes: list[str] | None = None) -> None:
        if as_json:
            body: dict[str, object] = {"ok": stamp is not None, "message": heading, "detail": detail}
            if stamp is not None:
                body.update(_stamp_json(stamp, self.server.url), created=created, notes=notes or [])
            return self._send(status, json.dumps(body, ensure_ascii=False, indent=2), "application/json; charset=utf-8")
        if stamp is None:
            return self._send(status, _page(heading, f"<p>{escape(detail)}</p>" + _back_links(popup)))
        self._send(status, _result_page(stamp, heading, detail, popup, notes or []))

    def _stamp_file(self, sha256: str) -> None:
        path = self.server.album.svg_path(sha256)
        if not path.is_file():
            return self._send(HTTPStatus.NOT_FOUND, _page("Not found", "<p>No such stamp.</p>"))
        self._send(HTTPStatus.OK, path.read_bytes(), "image/svg+xml")

    def _sheet(self, query: dict[str, list[str]], page: bool) -> None:
        album = self.server.album
        paper = query.get("paper", ["a4"])[0].lower()
        if paper not in PAPER_SIZES_MM:
            paper = "a4"
        try:
            stamps = [album.find(h) for h in query.get("h", [])] or album.stamps()[:8]
        except (NotFound, Ambiguous) as e:
            return self._send(HTTPStatus.NOT_FOUND, _page("Not found", f"<p>{escape(str(e))}</p>"))
        if not stamps:
            return self._send(HTTPStatus.OK, _page("Nothing to print", "<p>The album is empty.</p>" + _back_links(False)))
        stamps = stamps[:8]
        previews = {s.sha256: p for s in stamps if (p := album.load_preview(s)) is not None}
        title = query.get("title", [None])[0]
        svg = render_sheet(stamps, paper=paper, title=title, previews=previews)
        if page:
            return self._send(HTTPStatus.OK, render_sheet_page(svg, paper=paper, title=title, count=len(stamps)))
        self._send(HTTPStatus.OK, svg, "image/svg+xml")

    def _api_stamps(self) -> None:
        stamps = [_stamp_json(s, self.server.url) for s in self.server.album.stamps()]
        self._send(HTTPStatus.OK, json.dumps({"count": len(stamps), "stamps": stamps}, ensure_ascii=False, indent=2), "application/json; charset=utf-8")


# ------------------------------------------------------------------ pages

def _stamp_json(s: Stamp, base: str) -> dict[str, object]:
    return {
        "sha256": s.sha256,
        "short": s.short,
        "url": s.url,
        "title": s.title,
        "description": s.description,
        "host": s.host,
        "fetched_at": s.fetched_at,
        "size": s.size,
        "number": s.number,
        "content_type": s.content_type,
        "preview_kind": s.preview_kind,
        "svg": f"{base}/stamps/{s.sha256}.svg",
        "qr": s.qr_payload,
    }


_PAGE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #1c1a17; color: #e9e2d3; font: 15px/1.5 Georgia, 'Times New Roman', serif; }
main { max-width: 520px; margin: 0 auto; padding: 28px 24px 40px; }
h1 { font-size: 22px; font-weight: 600; letter-spacing: 3px; text-transform: uppercase; margin: 0 0 6px; }
p { margin: 8px 0; color: #cfc6b4; }
p.detail { color: #a79f8f; font-style: italic; }
figure { margin: 18px 0; text-align: center; }
figure img { width: 100%; max-width: 300px; filter: drop-shadow(0 4px 10px rgba(0,0,0,.55)); }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 14px 0; font: 13px/1.5 ui-monospace, Menlo, Consolas, monospace; }
dt { color: #a79f8f; letter-spacing: 1px; text-transform: uppercase; font-size: 11px; padding-top: 2px; }
dd { margin: 0; color: #e9e2d3; overflow-wrap: anywhere; }
nav { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 20px; }
nav a, nav button { color: #f1ebdd; background: #2b2824; border: 1px solid #4a443a; border-radius: 3px; padding: 7px 14px;
  text-decoration: none; font: 13px ui-monospace, Menlo, Consolas, monospace; letter-spacing: 1px; cursor: pointer; }
nav a:hover, nav button:hover { background: #3a352d; }
ul.notes { margin: 10px 0 0; padding-left: 18px; color: #a79f8f; font-size: 13px; }
code { font: 13px ui-monospace, Menlo, Consolas, monospace; color: #b9b09c; }
"""


def _page(heading: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8"><title>{escape(heading)} — stamp</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{_PAGE_CSS}</style></head>\n"
        f"<body><main><h1>{escape(heading)}</h1>{body}</main></body></html>\n"
    )


def _back_links(popup: bool) -> str:
    close = '<button type="button" onclick="window.close()">Close</button>' if popup else ""
    return f'<nav><a href="/" target="{"_blank" if popup else "_self"}">Album</a>{close}</nav>'


def _result_page(stamp: Stamp, heading: str, detail: str, popup: bool, notes: list[str]) -> str:
    target = "_blank" if popup else "_self"
    notes_html = "".join(f"<li>{escape(n)}</li>" for n in notes)
    body = (
        (f'<p class="detail">{detail}</p>' if detail else "")
        + f'<figure><a href="/stamps/{stamp.sha256}.svg" target="{target}"><img src="/stamps/{stamp.sha256}.svg" alt="{escape(stamp.label)}"></a></figure>'
        + "<dl>"
        + f"<dt>title</dt><dd>{escape(stamp.label)}</dd>"
        + f'<dt>url</dt><dd><a href="{escape(stamp.url)}" target="_blank" rel="noopener" style="color:inherit">{escape(stamp.url)}</a></dd>'
        + f"<dt>fetched</dt><dd>{escape(stamp.fetched_at)}</dd>"
        + f"<dt>sha-256</dt><dd>{stamp.sha256}</dd>"
        + f"<dt>size</dt><dd>{escape(human_size(stamp.size))}</dd>"
        + (f"<dt>no.</dt><dd>{stamp.number:03d}</dd>" if stamp.number else "")
        + "</dl>"
        + (f'<ul class="notes">{notes_html}</ul>' if notes_html else "")
        + f'<nav><a href="/?added={stamp.sha256}#{stamp.short}" target="{target}">Album</a>'
        + f'<a href="/sheet" target="{target}">Print sheet</a>'
        + ('<button type="button" onclick="window.close()">Close</button>' if popup else "")
        + "</nav>"
    )
    return _page(heading, body)


_TOOLBAR_CSS = """
.tools { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 16px 48px; background: #242119; border-bottom: 1px solid #3a352d; }
.tools form { display: flex; gap: 8px; flex: 1 1 360px; }
.tools input[type=url] { flex: 1; padding: 8px 12px; background: #1c1a17; color: #e9e2d3; border: 1px solid #4a443a; border-radius: 3px;
  font: 14px ui-monospace, Menlo, Consolas, monospace; }
.tools button, .tools a.btn { padding: 8px 14px; background: #f1ebdd; color: #1c1a17; border: 1px solid #a79f8f; border-radius: 3px;
  font: 13px ui-monospace, Menlo, Consolas, monospace; font-weight: 600; letter-spacing: 1px; text-decoration: none; cursor: pointer; }
.tools a.btn.quiet { background: #2b2824; color: #f1ebdd; border-color: #4a443a; font-weight: 400; }
.tools a.mark { color: #f1ebdd; background: #3a352d; border: 1px dashed #a79f8f; border-radius: 3px; padding: 8px 14px;
  font: 13px ui-monospace, Menlo, Consolas, monospace; text-decoration: none; cursor: grab; }
.tools .hint { color: #a79f8f; font-size: 13px; font-style: italic; }
.flash { padding: 10px 48px; background: #2f3a2b; color: #dfe9d3; font-size: 14px; border-bottom: 1px solid #3a352d; }
figure.new img { outline: 3px solid #e2c15c; outline-offset: 6px; border-radius: 2px; }
"""


def _toolbar(server: StampServer, added: str | None) -> str:
    flash = ""
    if added:
        try:
            s = server.album.get(added)
            flash = f'<div class="flash">Stamped just now: <b>{escape(s.label)}</b> — <code>{s.short}</code></div>'
        except (NotFound, ValueError):
            flash = ""
    return (
        f"<style>{_TOOLBAR_CSS}</style>"
        '<div class="tools">'
        '<form method="post" action="/add">'
        f'<input type="hidden" name="token" value="{escape(server.token)}">'
        '<input type="url" name="url" placeholder="https://… a page that mattered" required autofocus>'
        '<button type="submit">Stamp it</button></form>'
        f'<a class="mark" href="{escape(server.bookmarklet(), quote=True)}" title="Drag me to your bookmarks bar">Stamp this page</a>'
        '<span class="hint">← drag to your bookmarks bar for one-click stamping</span>'
        '<a class="btn quiet" href="/sheet">Print sheet</a>'
        "</div>" + flash
    )


# --------------------------------------------------------------- running

def serve(album: Album, port: int = DEFAULT_PORT, *, open_browser: bool = False, timeout: float = 30) -> int:
    """Run the server until interrupted. Returns an exit code."""
    import webbrowser

    try:
        server = StampServer(album, port=port, timeout=timeout)
    except OSError as e:
        print(f"stamp: cannot listen on 127.0.0.1:{port}: {e.strerror or e}", file=sys.stderr)
        return 1
    album.ensure()
    print(f"stamp album at {server.url}   (Ctrl-C to stop)", flush=True)
    print("one-click stamping: drag the “Stamp this page” link from that page to your bookmarks bar", flush=True)
    print(f"token for scripts:  {server.token}   e.g. curl -X POST {server.url}/add -d url=https://example.com -d token=…", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


__all__ = ["DEFAULT_PORT", "StampServer", "serve"]
