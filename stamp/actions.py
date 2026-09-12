"""The one thing stamp does, as a function: fetch a page and stamp it.

Shared by the command line and the local server so that both make exactly
the same stamp for a URL.
"""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass, field

from . import preview as preview_mod
from .fetch import URLError, extract_meta, fetch, fetch_preview, normalize_url
from .preview import Preview
from .store import Album, Stamp


class FetchFailed(Exception):
    """The page could not be fetched; ``str(e)`` says why, for a person."""

    def __init__(self, url: str, reason: str, status: int | None = None) -> None:
        super().__init__(f"could not fetch {url}: {reason}")
        self.url = url
        self.reason = reason
        self.status = status


@dataclass
class Outcome:
    stamp: Stamp
    created: bool
    notes: list[str] = field(default_factory=list)  # things worth telling the user, none fatal


def stamp_url(
    album: Album,
    raw_url: str,
    *,
    title: str | None = None,
    description: str | None = None,
    want_preview: bool = True,
    timeout: float = 30,
) -> Outcome:
    """Fetch ``raw_url`` and file a stamp for it in ``album``.

    Raises :class:`URLError` for a URL that cannot be stamped at all and
    :class:`FetchFailed` when the server does not hand over the page. A
    missing preview picture is never an error.
    """
    url = normalize_url(raw_url)
    try:
        got = fetch(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise FetchFailed(url, f"{e.code} {e.reason}", status=e.code) from e
    except urllib.error.URLError as e:
        raise FetchFailed(url, str(e.reason)) from e
    except (URLError, TimeoutError, OSError, ValueError) as e:
        raise FetchFailed(url, str(e)) from e

    meta = extract_meta(got.body, got.content_type, got.final_url or url)
    notes: list[str] = []
    preview: Preview | None = None
    kind: str | None = None
    source: str | None = None
    if want_preview and not album.has(got.body):
        preview, kind, source = _find_preview(meta.image_url, meta.icon_url, timeout=min(timeout, 20), notes=notes)

    stamp, created = album.add(
        url,
        got.body,
        content_type=got.content_type,
        title=title or meta.title,
        requested_url=raw_url if raw_url != url else None,
        final_url=got.final_url,
        status=got.status,
        description=description or meta.description,
        preview=preview,
        preview_source=source,
        preview_kind=kind,
    )
    return Outcome(stamp=stamp, created=created, notes=notes if created else [])


def _find_preview(
    image_url: str | None, icon_url: str | None, *, timeout: float, notes: list[str]
) -> tuple[Preview | None, str | None, str | None]:
    """The page's picture if it has one, else its icon if that is big enough."""
    candidates = [(image_url, "image"), (icon_url, "icon")]
    for url, kind in candidates:
        if not url:
            continue
        if kind == "icon" and not preview_mod.HAVE_PIL and url.lower().split("?")[0].endswith(".ico"):
            continue  # nothing here can read an .ico without Pillow
        try:
            data, content_type = fetch_preview(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - the picture is a nicety, the stamp is the point
            notes.append(f"{kind} not fetched from {url}: {getattr(e, 'reason', e)}")
            continue
        got = preview_mod.prepare(data, content_type)
        if got is not None:
            return got, kind, url
        if kind == "image" and not preview_mod.HAVE_PIL:
            notes.append("preview skipped: install Pillow (pip install 'stamp-philately[preview]') to shrink large pictures")
    if image_url or icon_url:
        notes.append("no usable preview picture; the stamp shows an empty slot")
    return None, None, None
