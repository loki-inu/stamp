"""A local window onto the album.

``stamp gui`` serves the album on 127.0.0.1 and opens it. The Mac app
loads the same address in its own window. Nothing listens anywhere else,
and every mutation has to present a token that only this page was given.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from ..cli import FileError, file_page
from ..store import Album, Ambiguous, NotFound, Stamp, StampError
from ..svg import human_size, render_sheet

_STATIC = files("stamp.gui").joinpath("static")
_MEDIA = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8"}
_MAX_BODY = 64 * 1024


class AlbumHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, album: Album, token: str, port: int) -> None:
        self.album = album
        self.token = token
        self.lock = threading.RLock()
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server: AlbumHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    # ------------------------------------------------------------- requests

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._text(421, "wrong host")
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._html()
            return
        if path == "/favicon.ico":
            self._static("favicon.png", "image/png")
            return
        if path in ("/app.css", "/app.js"):
            self._static(path[1:])
            return
        if path == "/api/album":
            self._album()
            return
        if path == "/sheet.svg":
            self._sheet_file()
            return
        if path == "/print":
            self._print_page()
            return
        if path.startswith("/media/") and path.endswith(".svg"):
            self._stamp_svg(path[len("/media/"):-len(".svg")])
            return
        self._text(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._json(421, {"ok": False, "error": "wrong host"})
            return
        if not self._header_token_ok():
            self._json(403, {"ok": False, "error": "refused"})
            return
        origin = self.headers.get("Origin")
        if origin and origin != self._origin():
            self._json(403, {"ok": False, "error": "refused"})
            return
        path = urlsplit(self.path).path
        body = self._body()
        if body is None:
            return
        routes = {
            "/api/add": self._add,
            "/api/verify": self._verify,
            "/api/sheet": self._sheet,
            "/api/reveal": self._reveal,
            "/api/open": self._open,
            "/api/redraw": self._redraw,
        }
        route = routes.get(path)
        if route is None:
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            route(body)
        except FileError as e:
            self._json(400 if e.code == 2 else 502, {"ok": False, "error": str(e)})
        except Ambiguous as e:
            self._json(409, {"ok": False, "error": str(e)})
        except NotFound as e:
            self._json(404, {"ok": False, "error": f"no stamp matches {str(e)!r}"})
        except StampError as e:
            self._json(400, {"ok": False, "error": str(e)})

    # -------------------------------------------------------------- guards

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _origin(self) -> str:
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def _header_token_ok(self) -> bool:
        return self.headers.get("X-Stamp-Token") == self.server.token

    def _query_token_ok(self) -> bool:
        got = parse_qs(urlsplit(self.path).query).get("t", [""])[0]
        if len(got) != len(self.server.token):
            return False
        return secrets.compare_digest(got, self.server.token)

    def _body(self) -> dict | None:
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > _MAX_BODY:
            self._json(413, {"ok": False, "error": "request too large"})
            return None
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "expected JSON"})
            return None
        if not isinstance(data, dict):
            self._json(400, {"ok": False, "error": "expected a JSON object"})
            return None
        return data

    # ------------------------------------------------------------- responses

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _text(self, status: int, text: str) -> None:
        self._send(status, text.encode(), "text/plain; charset=utf-8")

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _html(self) -> None:
        page = _STATIC.joinpath("index.html").read_text(encoding="utf-8")
        page = page.replace("{{TOKEN}}", self.server.token).replace("{{VERSION}}", __version__)
        self._send(200, page.encode(), "text/html; charset=utf-8")

    def _static(self, name: str, content_type: str | None = None) -> None:
        ext = name.rsplit(".", 1)[-1]
        data = _STATIC.joinpath(name).read_bytes()
        self._send(200, data, content_type or _MEDIA[ext])

    def _album(self) -> None:
        if not (self._header_token_ok() or self._query_token_ok()):
            self._json(403, {"ok": False, "error": "refused"})
            return
        with self.server.lock:
            stamps = self.server.album.stamps()
        self._json(200, {
            "ok": True,
            "version": __version__,
            "home": str(self.server.album.home),
            "count": len(stamps),
            "stamps": [_public(s) for s in stamps],
        })

    def _stamp_svg(self, sha: str) -> None:
        if not self._query_token_ok() or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            self._text(404, "not found")
            return
        path = self.server.album.svg_path(sha)
        if not path.is_file():
            self._text(404, "not found")
            return
        self._send(200, path.read_bytes(), "image/svg+xml")

    def _sheet_file(self) -> None:
        if not self._query_token_ok():
            self._text(404, "not found")
            return
        path = self.server.album.home / "sheet.svg"
        if not path.is_file():
            self._text(404, "not found")
            return
        self._send(200, path.read_bytes(), "image/svg+xml")

    def _print_page(self) -> None:
        if not self._query_token_ok():
            self._text(404, "not found")
            return
        token = self.server.token
        page = (
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>Stamp sheet</title><style>"
            "html,body{margin:0;background:#fff}"
            "img{width:100%;height:auto;display:block}"
            "@page{size:A4 landscape;margin:8mm}"
            "</style></head><body>"
            f"<img src=\"/sheet.svg?t={token}\" alt=\"Sheet of stamps\">"
            "</body></html>"
        )
        self._send(200, page.encode(), "text/html; charset=utf-8")

    # ------------------------------------------------------------- actions

    def _add(self, body: dict) -> None:
        url = body.get("url")
        if not isinstance(url, str) or not url.strip():
            self._json(400, {"ok": False, "error": "give an address to file"})
            return
        title = body.get("title") or None
        description = body.get("description") or None
        if title is not None and not isinstance(title, str):
            self._json(400, {"ok": False, "error": "title must be text"})
            return
        if description is not None and not isinstance(description, str):
            self._json(400, {"ok": False, "error": "description must be text"})
            return
        try:
            timeout = float(body.get("timeout") or 30)
        except (TypeError, ValueError):
            timeout = 30.0
        timeout = min(max(timeout, 1.0), 120.0)
        with self.server.lock:
            filed = file_page(
                self.server.album,
                url,
                title=title,
                description=description,
                no_preview=bool(body.get("no_preview")),
                timeout=timeout,
            )
        stamp = filed.stamp
        self._json(200, {
            "ok": True,
            "created": filed.created,
            "notice": filed.notice,
            "stamp": _public(stamp),
            "message": (
                f"Filed {stamp.label}" if filed.created
                else f"Already in the album as {stamp.short} (same bytes, {stamp.date})"
            ),
        })

    def _verify(self, body: dict) -> None:
        stamp = self._find(body)
        if stamp is None:
            return
        with self.server.lock:
            ok = self.server.album.verify(stamp)
        self._json(200, {
            "ok": True,
            "match": ok,
            "short": stamp.short,
            "sha256": stamp.sha256,
            "message": (
                f"Bytes still hash to {stamp.short}" if ok
                else f"Stored bytes no longer hash to {stamp.short}"
            ),
        })

    def _sheet(self, body: dict) -> None:
        paper = body.get("paper") or "a4"
        if paper not in ("a4", "letter"):
            self._json(400, {"ok": False, "error": "paper must be a4 or letter"})
            return
        title = body.get("title") if isinstance(body.get("title"), str) else None
        hashes = body.get("hashes") or []
        if not isinstance(hashes, list):
            self._json(400, {"ok": False, "error": "hashes must be a list"})
            return
        with self.server.lock:
            album = self.server.album
            if hashes:
                stamps = [album.find(str(h)) for h in hashes]
            else:
                stamps = album.stamps()
            if not stamps:
                self._json(400, {"ok": False, "error": "nothing to print; the album is empty"})
                return
            stamps = stamps[:8]
            previews = {s.sha256: p for s in stamps if (p := album.load_preview(s)) is not None}
            out = album.home / "sheet.svg"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_sheet(stamps, paper=paper, title=title, previews=previews), encoding="utf-8")
        self._json(200, {
            "ok": True,
            "count": len(stamps),
            "paper": paper,
            "path": str(out),
            "url": f"/sheet.svg?t={self.server.token}",
        })

    def _reveal(self, body: dict) -> None:
        what = body.get("what") or "album"
        album = self.server.album
        if what == "album":
            album.ensure()
            path: Path = album.home
        elif what == "sheet":
            path = album.home / "sheet.svg"
        elif what == "stamp":
            stamp = self._find(body)
            if stamp is None:
                return
            path = album.svg_path(stamp.sha256)
        else:
            self._json(400, {"ok": False, "error": "nothing to reveal"})
            return
        if what != "album" and not path.is_file():
            self._json(404, {"ok": False, "error": "that file is not in the album yet"})
            return
        opened = _reveal_in_finder(path if path.is_dir() else path)
        self._json(200, {"ok": True, "path": str(path), "opened": opened})

    def _open(self, body: dict) -> None:
        url = body.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https"):
            self._json(400, {"ok": False, "error": "not a web address"})
            return
        webbrowser.open(url)
        self._json(200, {"ok": True})

    def _redraw(self, body: dict) -> None:
        hashes = body.get("hashes") or []
        with self.server.lock:
            album = self.server.album
            stamps = [album.find(str(h)) for h in hashes] if hashes else album.stamps()
            paths = [str(album.redraw(s)) for s in stamps]
        self._json(200, {"ok": True, "count": len(paths)})

    def _find(self, body: dict) -> Stamp | None:
        prefix = body.get("hash")
        if not isinstance(prefix, str) or not prefix.strip():
            self._json(400, {"ok": False, "error": "give a hash"})
            return None
        with self.server.lock:
            return self.server.album.find(prefix)


def _public(stamp: Stamp) -> dict:
    return {
        "sha256": stamp.sha256,
        "short": stamp.short,
        "url": stamp.url,
        "host": stamp.host,
        "title": stamp.title,
        "label": stamp.label,
        "caption": stamp.caption,
        "description": stamp.description,
        "date": stamp.date,
        "fetched_at": stamp.fetched_at,
        "content_type": stamp.content_type.split(";")[0].strip(),
        "size": stamp.size,
        "size_label": human_size(stamp.size),
        "number": stamp.number,
        "status": stamp.status,
        "svg": f"/media/{stamp.sha256}.svg",
    }


def _reveal_in_finder(path: Path) -> bool:
    """Show ``path`` in the Finder. Elsewhere, just report the path."""
    if sys.platform != "darwin":
        return False
    import subprocess
    subprocess.run(["open", "-R", str(path)], check=False)
    return True


def serve(
    album: Album,
    *,
    port: int = 0,
    open_browser: bool = False,
    endpoint_file: Path | None = None,
) -> None:
    """Serve ``album`` on 127.0.0.1 until interrupted."""
    token = secrets.token_hex(16)
    httpd = AlbumHTTPServer(album, token, port)
    bound = httpd.server_address[1]
    url = f"http://127.0.0.1:{bound}/"
    if endpoint_file is not None:
        endpoint_file.write_text(url)
    # One machine-readable line on stdout for the Mac app, then a note for a person.
    print(f"STAMP_GUI {url}", flush=True)
    print(f"stamp: album at {url}  (album directory {album.home})", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="stamp.gui", description="Open the stamp album in a window.")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--home", metavar="DIR")
    parser.add_argument("--endpoint-file", type=Path, help="write the album address here once listening")
    args = parser.parse_args(argv)
    serve(
        Album(args.home),
        port=args.port,
        open_browser=not args.no_open,
        endpoint_file=args.endpoint_file,
    )
    return 0
