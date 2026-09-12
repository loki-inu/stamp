import urllib.error

import pytest

from stamp import cli
from stamp.fetch import Fetched
from tests.conftest import PAGE


RICH_PAGE = (
    b"<!doctype html><html><head><title>A page with a picture</title>"
    b'<meta property="og:description" content="Words the page uses about itself.">'
    b'<meta property="og:image" content="/pictures/card.png">'
    b"</head><body><p>hello</p></body></html>"
)


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    def _fetch(url, timeout=30):
        calls.append(url)
        if "missing" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "rich" in url:
            body = RICH_PAGE
        else:
            body = PAGE if "other" not in url else PAGE.replace(b"hello", b"goodbye")
        return Fetched(requested_url=url, final_url=url, status=200, content_type="text/html; charset=utf-8", body=body)

    monkeypatch.setattr(cli, "fetch", _fetch)
    return calls


@pytest.fixture
def fake_preview(monkeypatch):
    """Serves a small PNG for any preview URL; set ``state['fail']`` to break it."""
    from tests.test_preview import tiny_png

    state = {"calls": [], "fail": False}

    def _fetch_preview(url, timeout=15):
        state["calls"].append(url)
        if state["fail"]:
            raise urllib.error.URLError("connection refused")
        return tiny_png(600, 340), "image/png"

    monkeypatch.setattr(cli, "fetch_preview", _fetch_preview)
    return state


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


def test_add_files_preview_and_description(album, fake_fetch, fake_preview, capsys):
    assert cli.main(["add", "https://example.com/rich"]) == 0
    assert fake_preview["calls"] == ["https://example.com/pictures/card.png"]
    (stamp,) = album.stamps()
    assert stamp.title == "A page with a picture"
    assert stamp.description == "Words the page uses about itself."
    assert stamp.preview_source == "https://example.com/pictures/card.png"
    assert stamp.preview is not None and album.preview_path(stamp).is_file()
    svg = album.svg_path(stamp.sha256).read_text()
    assert "data:image/" in svg and "Words the page uses" in svg and "NO PREVIEW" not in svg

    assert cli.main(["show", stamp.short]) == 0
    out = capsys.readouterr().out
    assert "Words the page uses about itself." in out
    assert str(album.preview_path(stamp)) in out
    assert "https://example.com/pictures/card.png" in out
    assert cli.main(["verify", stamp.short]) == 0


def test_add_survives_a_broken_preview(album, fake_fetch, fake_preview, capsys):
    fake_preview["fail"] = True
    assert cli.main(["add", "https://example.com/rich"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("stamped")
    assert "no usable preview" in out
    assert "preview not fetched" in err
    (stamp,) = album.stamps()
    assert stamp.preview is None and stamp.preview_source is None
    assert stamp.description == "Words the page uses about itself."
    assert "NO PREVIEW" in album.svg_path(stamp.sha256).read_text()
    assert album.verify(stamp)


def test_add_without_pillow_falls_back_gracefully(album, fake_fetch, fake_preview, monkeypatch, capsys):
    from stamp import preview as preview_mod

    monkeypatch.setattr(preview_mod, "HAVE_PIL", False)
    assert cli.main(["add", "https://example.com/rich"]) == 0
    (stamp,) = album.stamps()
    # A small PNG is embedded as it came, without Pillow.
    assert stamp.preview is not None and stamp.preview.endswith(".preview.png")
    assert "data:image/png;base64," in album.svg_path(stamp.sha256).read_text()


def test_add_no_preview_flag_and_overrides(album, fake_fetch, fake_preview):
    assert cli.main(["add", "--no-preview", "--description", "My own words", "https://example.com/rich"]) == 0
    assert fake_preview["calls"] == []
    (stamp,) = album.stamps()
    assert stamp.preview is None and stamp.description == "My own words"


def test_add_does_not_refetch_a_preview_for_known_bytes(album, fake_fetch, fake_preview):
    assert cli.main(["add", "https://example.com/rich"]) == 0
    assert cli.main(["add", "https://example.com/rich"]) == 0
    assert len(fake_preview["calls"]) == 1


def test_pages_without_pictures_get_no_preview(album, fake_fetch, fake_preview):
    assert cli.main(["add", "https://example.com/"]) == 0
    assert fake_preview["calls"] == []
    (stamp,) = album.stamps()
    assert stamp.preview is None and stamp.description is None


def test_sheet_carries_previews(album, fake_fetch, fake_preview):
    cli.main(["add", "https://example.com/rich"])
    cli.main(["add", "https://example.com/"])
    assert cli.main(["sheet"]) == 0
    text = (album.home / "sheet.svg").read_text()
    assert text.count("<image ") == 1
    assert text.count("NO PREVIEW") == 1


def test_redraw(album, fake_fetch, fake_preview, capsys):
    cli.main(["add", "https://example.com/rich"])
    cli.main(["add", "https://example.com/"])
    for s in album.stamps():
        album.svg_path(s.sha256).write_text("stale")
    assert cli.main(["redraw"]) == 0
    assert capsys.readouterr().out.count("redrawn") == 2
    for s in album.stamps():
        svg = album.svg_path(s.sha256).read_text()
        assert svg.startswith("<?xml") and s.sha256 in svg
    rich = next(s for s in album.stamps() if s.preview)
    assert "data:image/" in album.svg_path(rich.sha256).read_text()
    assert cli.main(["redraw", rich.short[:6]]) == 0
    assert capsys.readouterr().out.count("redrawn") == 1
    assert cli.main(["redraw", "deadbeef"]) == 2


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
