import pytest

from stamp.store import Album

PAGE = b"<!doctype html><html><head><title>  A page\n that mattered </title></head><body>hello</body></html>"


@pytest.fixture
def album(tmp_path, monkeypatch):
    home = tmp_path / "album"
    monkeypatch.setenv("STAMP_HOME", str(home))
    return Album(home)


@pytest.fixture
def stamped(album):
    stamp, created = album.add(
        "https://example.com/",
        PAGE,
        content_type="text/html; charset=utf-8",
        title="A page that mattered",
        fetched_at="2026-01-02T03:04:05Z",
    )
    assert created
    return stamp
