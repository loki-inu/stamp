import hashlib
import json

import pytest

from stamp.store import Album, Ambiguous, NotFound, Stamp, sha256_hex
from tests.conftest import PAGE


def test_hash_is_stable_and_matches_hashlib(album, stamped):
    expected = hashlib.sha256(PAGE).hexdigest()
    assert stamped.sha256 == expected == sha256_hex(PAGE)
    assert album.object_path(stamped.sha256).read_bytes() == PAGE
    assert album.verify(stamped)

    # A second album over the same bytes names them identically.
    other = Album(album.home.parent / "another")
    again, created = other.add("https://elsewhere.example/", PAGE)
    assert created
    assert again.sha256 == expected


def test_same_bytes_same_stamp(album, stamped):
    again, created = album.add("https://example.com/", PAGE, title="A page that mattered")
    assert not created
    assert again.sha256 == stamped.sha256
    assert again.fetched_at == stamped.fetched_at
    assert len(album.stamps()) == 1


def test_different_bytes_different_stamp(album, stamped):
    other, created = album.add("https://example.com/", PAGE + b"\n<!-- edited -->")
    assert created
    assert other.sha256 != stamped.sha256
    assert other.number == stamped.number + 1
    assert [s.sha256 for s in album.stamps()][0] == other.sha256  # newest first


def test_files_are_written(album, stamped):
    assert album.svg_path(stamped.sha256).is_file()
    meta = json.loads(album.meta_path(stamped.sha256).read_text())
    assert meta["sha256"] == stamped.sha256
    assert meta["url"] == "https://example.com/"
    assert meta["fetched_at"] == "2026-01-02T03:04:05Z"
    assert meta["title"] == "A page that mattered"
    assert meta["content_type"].startswith("text/html")
    assert meta["size"] == len(PAGE)
    svg = album.svg_path(stamped.sha256).read_text()
    assert svg.startswith("<?xml")
    assert stamped.sha256 in svg
    assert "2026-01-02" in svg


def test_metadata_roundtrip_keeps_unknown_fields():
    s = Stamp.from_json(json.dumps({"sha256": "ab" * 32, "url": "https://x.example/", "fetched_at": "2026-01-01T00:00:00Z", "future_field": 1}))
    assert s.extra == {"future_field": 1}
    assert json.loads(s.to_json())["future_field"] == 1


def test_find_by_prefix(album, stamped):
    assert album.find(stamped.sha256[:6]).sha256 == stamped.sha256
    assert album.find(stamped.sha256).sha256 == stamped.sha256
    assert album.find("stamp:sha256:" + stamped.sha256).sha256 == stamped.sha256
    assert album.find(stamped.sha256[:8].upper()).sha256 == stamped.sha256
    with pytest.raises(NotFound):
        album.find("0000000000")
    with pytest.raises(NotFound):
        album.find("not-hex")


def test_find_ambiguous(album, monkeypatch):
    # Force two stamps that share a prefix by writing metadata directly.
    album.ensure()
    for h in ("a" * 64, "a" * 63 + "b"):
        album.meta_path(h).write_text(Stamp(sha256=h, url="https://x.example/", fetched_at="2026-01-01T00:00:00Z").to_json())
    with pytest.raises(Ambiguous) as e:
        album.find("aaaa")
    assert "matches several" in str(e.value)


def test_verify_fails_on_tamper(album, stamped):
    obj = album.object_path(stamped.sha256)
    obj.write_bytes(obj.read_bytes() + b" ")
    assert album.verify(stamped) is False


def test_verify_fails_when_bytes_missing(album, stamped):
    album.object_path(stamped.sha256).unlink()
    assert album.verify(stamped) is False


def test_empty_album(tmp_path):
    a = Album(tmp_path / "nothing")
    assert a.stamps() == []
    with pytest.raises(NotFound):
        a.find("abcd")
