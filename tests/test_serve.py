import json
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest

from stamp import actions
from stamp.fetch import Fetched
from stamp.serve import StampServer
from tests.conftest import PAGE
from tests.test_cli import RICH_PAGE
from tests.test_preview import tiny_png


@pytest.fixture
def server(album, monkeypatch):
    def _fetch(url, timeout=30):
        if "missing" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body = RICH_PAGE if "rich" in url else PAGE
        return Fetched(requested_url=url, final_url=url, status=200, content_type="text/html; charset=utf-8", body=body)

    monkeypatch.setattr(actions, "fetch", _fetch)
    monkeypatch.setattr(actions, "fetch_preview", lambda url, timeout=15: (tiny_png(600, 340), "image/png"))
    srv = StampServer(album, port=0, token="secret-token")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _get(srv, path, headers=None, method="GET", data=None):
    req = urllib.request.Request(srv.url + path, headers=headers or {}, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_album_page_carries_form_and_bookmarklet(server, album):
    status, headers, body = _get(server, "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    text = body.decode()
    assert 'name="token" value="secret-token"' in text
    assert "Stamp this page" in text and "javascript:(function()" in text
    assert server.bookmarklet().startswith("javascript:") and "token=secret-token" in server.bookmarklet()
    assert "No stamps yet" in text


def test_print_page_stamps_nothing_by_itself(server, album):
    """The printer page is inert HTML; its script calls /add with the token."""
    assert "/print?popup=1&token=secret-token&url=" in server.bookmarklet()
    status, headers, body = _get(server, "/print?popup=1&token=secret-token&url=" + quote("https://example.com/rich", safe=""))
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    text = body.decode()
    assert '"url": "https://example.com/rich"' in text and '"token": "secret-token"' in text
    assert "Printing your stamp" in text and "fetch('/add'" in text and "window.close()" in text
    assert album.stamps() == []  # merely opening the page files nothing

    # Script tags in a URL cannot break out of the embedded JSON.
    status, _, body = _get(server, "/print?token=x&url=" + quote("https://e.example/</script><script>alert(1)</script>", safe=""))
    assert status == 200 and b"</script><script>alert" not in body


def test_add_needs_the_token(server, album):
    status, _, body = _get(server, "/add?url=https://example.com/&token=wrong")
    assert status == 403 and b"token" in body
    assert album.stamps() == []
    status, _, _ = _get(server, "/add?url=https://example.com/")
    assert status == 403


def test_add_via_bookmarklet_url(server, album):
    url = quote("https://example.com/rich", safe="")
    status, _, body = _get(server, f"/add?popup=1&token=secret-token&url={url}")
    assert status == 200
    text = body.decode()
    assert "<h1>Stamped</h1>" in text and "Close</button>" in text
    (stamp,) = album.stamps()
    assert stamp.title == "A page with a picture" and stamp.preview is not None
    assert f"/stamps/{stamp.sha256}.svg" in text

    # The same page again is reported as already filed, not refetched for a picture.
    status, _, body = _get(server, f"/add?token=secret-token&url={url}")
    assert status == 200 and b"Already in the album" in body
    assert len(album.stamps()) == 1


def test_add_via_form_post_and_json(server, album):
    data = b"url=https%3A%2F%2Fexample.com%2F&token=secret-token"
    status, _, body = _get(server, "/add", headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST", data=data)
    assert status == 200 and b"<h1>Stamped</h1>" in body

    payload = json.dumps({"url": "https://example.com/rich", "token": "secret-token"}).encode()
    status, headers, body = _get(server, "/add", headers={"Content-Type": "application/json"}, method="POST", data=payload)
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    got = json.loads(body)
    assert got["ok"] is True and got["created"] is True and got["title"] == "A page with a picture"
    assert got["svg"].endswith(f"/stamps/{got['sha256']}.svg")
    assert len(album.stamps()) == 2


def test_add_failures_are_reported_not_fatal(server, album):
    status, _, body = _get(server, "/add?token=secret-token&url=" + quote("https://example.com/missing", safe=""))
    assert status == 502 and b"404" in body
    status, _, body = _get(server, "/add?token=secret-token&url=" + quote("ftp://example.com/", safe=""))
    assert status == 400 and b"unsupported scheme" in body
    status, _, body = _get(server, "/add?token=secret-token&url=", headers={"Accept": "application/json"})
    assert status == 400 and json.loads(body)["ok"] is False
    assert album.stamps() == []
    # The server is still alive.
    assert _get(server, "/")[0] == 200


def test_stamp_files_sheet_and_api(server, album):
    _get(server, "/add?token=secret-token&url=" + quote("https://example.com/rich", safe=""))
    (stamp,) = album.stamps()
    status, headers, body = _get(server, f"/stamps/{stamp.sha256}.svg")
    assert status == 200 and headers["Content-Type"] == "image/svg+xml" and body.startswith(b"<?xml")
    assert _get(server, "/stamps/../../etc/passwd")[0] == 404
    assert _get(server, "/stamps/zz.svg")[0] == 404
    assert _get(server, "/nowhere")[0] == 404

    status, headers, body = _get(server, "/sheet")
    assert status == 200 and b"@page { size: 297mm 210mm" in body and b"<svg" in body
    status, headers, body = _get(server, "/sheet.svg?paper=letter")
    assert status == 200 and headers["Content-Type"] == "image/svg+xml" and b'width="279.4mm"' in body
    status, _, body = _get(server, f"/sheet?h={stamp.short}&title=Mine")
    assert status == 200 and b"MINE" in body

    status, headers, body = _get(server, "/api/stamps")
    got = json.loads(body)
    assert got["count"] == 1 and got["stamps"][0]["sha256"] == stamp.sha256 and got["stamps"][0]["preview_kind"] == "image"

    status, _, body = _get(server, f"/?added={stamp.sha256}")
    assert status == 200 and b'class="new"' in body and b"Stamped just now" in body


def test_refuses_other_hosts(server):
    status, _, body = _get(server, "/", headers={"Host": "evil.example"})
    assert status == 403 and b"localhost" in body
    status, _, _ = _get(server, "/", headers={"Host": "localhost:1234"})
    assert status == 200
    status, _, _ = _get(server, "/", headers={"Host": "[::1]:1234"})
    assert status == 200


@pytest.mark.skipif(sys.platform == "win32", reason="Windows lets a second socket bind an in-use port")
def test_cli_serve_reports_a_busy_port(server, album, capsys):
    from stamp import cli

    port = server.server_address[1]
    assert cli.main(["serve", "--port", str(port)]) == 1
    assert "cannot listen" in capsys.readouterr().err
