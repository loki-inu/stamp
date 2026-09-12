import urllib.error

import pytest

from stamp import cli
from stamp.fetch import Fetched
from tests.conftest import PAGE


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    def _fetch(url, timeout=30):
        calls.append(url)
        if "missing" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body = PAGE if "other" not in url else PAGE.replace(b"hello", b"goodbye")
        return Fetched(requested_url=url, final_url=url, status=200, content_type="text/html; charset=utf-8", body=body)

    monkeypatch.setattr(cli, "fetch", _fetch)
    return calls


def test_add_list_show_verify(album, fake_fetch, capsys):
    assert cli.main(["add", "Example.com/?utm_source=x"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("stamped  ")
    assert "A page that mattered" in out
    assert fake_fetch == ["https://example.com/"]

    (stamp,) = album.stamps()
    short = stamp.short
    assert short in out

    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert short in out and "A page that mattered" in out

    assert cli.main(["show", short[:6]]) == 0
    out = capsys.readouterr().out
    assert str(album.svg_path(stamp.sha256)) in out
    assert "https://example.com/" in out
    assert stamp.sha256 in out

    assert cli.main(["verify", short]) == 0
    assert capsys.readouterr().out.startswith("ok")


def test_add_twice_is_idempotent(album, fake_fetch, capsys):
    assert cli.main(["add", "https://example.com/"]) == 0
    assert cli.main(["add", "https://example.com/"]) == 0
    assert "already in the album" in capsys.readouterr().out
    assert len(album.stamps()) == 1
    assert cli.main(["add", "https://example.com/other"]) == 0
    assert len(album.stamps()) == 2


def test_verify_exit_codes(album, fake_fetch, capsys):
    cli.main(["add", "https://example.com/"])
    (stamp,) = album.stamps()
    obj = album.object_path(stamp.sha256)
    obj.write_bytes(b"something else entirely")
    assert cli.main(["verify", stamp.short]) == 1
    assert "MISMATCH" in capsys.readouterr().out
    assert cli.main(["verify", "deadbeef"]) == 2


def test_add_errors(album, fake_fetch, capsys):
    assert cli.main(["add", "ftp://example.com/"]) == 2
    assert "unsupported scheme" in capsys.readouterr().err
    assert cli.main(["add", "https://example.com/missing"]) == 1
    assert "404" in capsys.readouterr().err
    assert album.stamps() == []


def test_sheet_and_album(album, fake_fetch, tmp_path, capsys):
    cli.main(["add", "https://example.com/"])
    cli.main(["add", "https://example.com/other"])
    assert cli.main(["sheet"]) == 0
    assert (album.home / "sheet.svg").is_file()
    out = tmp_path / "custom.svg"
    assert cli.main(["sheet", "--out", str(out), "--paper", "letter"]) == 0
    assert out.read_text().count('<svg x="') == 2  # one nested svg per stamp
    assert cli.main(["album"]) == 0
    html = (album.home / "album.html").read_text()
    for s in album.stamps():
        assert s.sha256 in html


def test_sheet_of_named_stamps(album, fake_fetch):
    cli.main(["add", "https://example.com/"])
    cli.main(["add", "https://example.com/other"])
    first = album.stamps()[-1]
    assert cli.main(["sheet", first.short[:5]]) == 0
    text = (album.home / "sheet.svg").read_text()
    assert text.count('<svg x="') == 1
    assert first.sha256 in text


def test_empty_album_messages(album, capsys):
    assert cli.main(["list"]) == 0
    assert "empty" in capsys.readouterr().out
    assert cli.main(["sheet"]) == 1
    assert cli.main(["album"]) == 0
    assert "No stamps yet" in (album.home / "album.html").read_text()


def test_home_flag_beats_env(tmp_path, fake_fetch, monkeypatch):
    monkeypatch.setenv("STAMP_HOME", str(tmp_path / "env-home"))
    other = tmp_path / "flag-home"
    assert cli.main(["--home", str(other), "add", "https://example.com/"]) == 0
    assert (other / "objects").is_dir()
    assert not (tmp_path / "env-home").exists()


def test_module_entry_point():
    import runpy
    import sys

    argv = sys.argv
    sys.argv = ["stamp", "--version"]
    try:
        with pytest.raises(SystemExit) as e:
            runpy.run_module("stamp", run_name="__main__")
        assert e.value.code == 0
    finally:
        sys.argv = argv
