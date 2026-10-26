"""The album window: the local server the Mac app and ``stamp gui`` share."""

import json
import re
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from stamp import __version__
from stamp.fetch import Fetched
from stamp.gui import AlbumHTTPServer
from tests.conftest import PAGE


@pytest.fixture
def httpd(album):
    server = AlbumHTTPServer(album, "ab" * 16, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


@pytest.fixture
def client(httpd):
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(method, path, body=None, *, token=httpd.token, host=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {}
        if token is not None and method != "GET":
            headers["X-Stamp-Token"] = token
        if method == "GET" and path.startswith("/api/") and token is not None:
            headers["X-Stamp-Token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"
        if host is not None:
            headers["Host"] = host
        req = Request(base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req) as resp:
                raw = resp.read()
                return resp.status, raw, resp.headers
        except HTTPError as e:
            return e.code, e.read(), e.headers

    return call


def test_page_carries_a_token_and_the_version(client):
    status, raw, headers = client("GET", "/", token=None)
    assert status == 200
    page = raw.decode()
    assert __version__ in page
    assert re.search(r'name="stamp-token" content="[0-9a-f]{32}"', page)
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert client("GET", "/favicon.ico", token=None)[0] == 200
    status, css, _ = client("GET", "/app.css", token=None)
    assert status == 200 and b".toolbar" in css
    status, js, _ = client("GET", "/app.js", token=None)
    assert status == 200 and b"stampNative" in js


def test_album_requires_the_token_and_lists_stamps(album, client, httpd):
    status, raw, _ = client("GET", "/api/album", token=None)
    assert status == 403
    status, raw, _ = client("GET", "/api/album", token="nope")
    assert status == 403

    album.add(
        "https://example.com/", PAGE,
        title="A page that mattered", content_type="text/html", fetched_at="2026-01-02T03:04:05Z",
    )
    status, raw, _ = client("GET", "/api/album")
    body = json.loads(raw)
    assert status == 200 and body["count"] == 1
    stamp = body["stamps"][0]
    assert stamp["label"] == "A page that mattered"
    assert stamp["svg"].endswith(".svg")
    status, svg, _ = client("GET", stamp["svg"] + "?t=" + httpd.token, token=None)
    assert status == 200 and svg.startswith(b"<?xml") and stamp["sha256"].encode() in svg
    # No token, no picture, and a path that tries to leave the album is not a stamp.
    assert client("GET", stamp["svg"], token=None)[0] == 404
    assert client("GET", "/media/../../etc/passwd.svg?t=" + httpd.token, token=None)[0] == 404


def test_add_verify_sheet_and_redraw(album, client, monkeypatch):
    def _fetch(url, timeout=30):
        return Fetched(requested_url=url, final_url=url, status=200, content_type="text/html", body=PAGE)

    monkeypatch.setattr("stamp.cli.fetch", _fetch)
    status, raw, _ = client("POST", "/api/add", {"url": "Example.com/hello?utm_source=x"})
    body = json.loads(raw)
    assert status == 200 and body["created"] is True
    assert body["stamp"]["url"] == "https://example.com/hello"
    short = body["stamp"]["short"]

    status, raw, _ = client("POST", "/api/add", {"url": "https://example.com/hello"})
    again = json.loads(raw)
    assert again["created"] is False and again["stamp"]["short"] == short

    status, raw, _ = client("POST", "/api/verify", {"hash": short[:6]})
    assert json.loads(raw)["match"] is True

    obj = album.object_path(body["stamp"]["sha256"])
    obj.write_bytes(obj.read_bytes() + b" ")
    status, raw, _ = client("POST", "/api/verify", {"hash": short})
    checked = json.loads(raw)
    assert status == 200 and checked["match"] is False and "no longer" in checked["message"]

    status, raw, _ = client("POST", "/api/sheet", {"paper": "letter"})
    sheet = json.loads(raw)
    assert sheet["count"] == 1 and sheet["paper"] == "letter"
    assert (album.home / "sheet.svg").is_file()
    status, svg, _ = client("GET", sheet["url"], token=None)
    assert status == 200 and b"<svg" in svg

    album.svg_path(body["stamp"]["sha256"]).write_text("stale")
    status, raw, _ = client("POST", "/api/redraw", {})
    assert json.loads(raw)["count"] == 1
    assert album.svg_path(body["stamp"]["sha256"]).read_text().startswith("<?xml")


def test_add_reports_a_bad_address_and_a_dead_host(client, monkeypatch):
    status, raw, _ = client("POST", "/api/add", {"url": "ftp://example.com/x"})
    assert status == 400 and b"unsupported scheme" in raw

    import urllib.error

    def _fetch(url, timeout=30):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr("stamp.cli.fetch", _fetch)
    status, raw, _ = client("POST", "/api/add", {"url": "https://example.com/missing"})
    assert status == 502 and b"404" in raw


def test_refuses_other_hosts_missing_tokens_and_cross_origin(client):
    assert client("GET", "/", host="evil.example")[0] == 421
    assert client("POST", "/api/verify", {"hash": "ab"}, token=None)[0] == 403
    status, raw, _ = client("POST", "/api/sheet", {})
    assert status == 400 and b"empty" in raw
    status, raw, _ = client("POST", "/api/open", {"url": "file:///etc/passwd"})
    assert status == 400


def test_reveal_reports_the_path_without_opening_anything(album, client):
    album.add("https://example.com/", PAGE, title="A page that mattered", content_type="text/html")
    status, raw, _ = client("POST", "/api/reveal", {"what": "album"})
    body = json.loads(raw)
    assert status == 200 and body["opened"] is False
    assert body["path"] == str(album.home)
    stamp = album.stamps()[0]
    status, raw, _ = client("POST", "/api/reveal", {"what": "stamp", "hash": stamp.short})
    assert json.loads(raw)["path"] == str(album.svg_path(stamp.sha256))


def test_open_uses_the_browser(client, monkeypatch):
    opened = []
    monkeypatch.setattr("stamp.gui.webbrowser.open", lambda url: opened.append(url))
    status, raw, _ = client("POST", "/api/open", {"url": "https://example.com/a"})
    assert status == 200 and opened == ["https://example.com/a"]


def test_endpoint_file_and_module(tmp_path):
    home = tmp_path / "album"
    endpoint = tmp_path / "endpoint"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "stamp.gui",
            "--no-open", "--home", str(home), "--endpoint-file", str(endpoint),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line.startswith("STAMP_GUI http://127.0.0.1:")
        assert endpoint.read_text().strip() == line.removeprefix("STAMP_GUI ").strip()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_static_files_travel_with_the_package():
    from importlib.resources import files

    assert files("stamp.gui").joinpath("static/index.html").is_file()
    assert "{{TOKEN}}" in files("stamp.gui").joinpath("static/index.html").read_text(encoding="utf-8")
