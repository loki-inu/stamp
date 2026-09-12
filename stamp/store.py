"""The album: a content-addressed store of snapshots and their stamps.

Layout under ``$STAMP_HOME`` (default ``~/.stamp``)::

    objects/<sha256>              the bytes exactly as fetched
    stamps/<sha256>.json          metadata
    stamps/<sha256>.svg           the stamp
    stamps/<sha256>.preview.jpg   the page's preview picture, shrunk (when it had one)
    sheet.svg, album.html         outputs of ``stamp sheet`` / ``stamp album``
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .fetch import host_of
from .preview import Preview, sniff_mime

# 1: url, title, hash, size. 2: adds description, preview, preview_source.
# Stamps written by either version read and draw fine; missing fields are None.
FORMAT_VERSION = 2
SHORT_HASH_LEN = 12
_HEX = re.compile(r"^[0-9a-f]+$")


class StampError(Exception):
    pass


class NotFound(StampError):
    pass


class Ambiguous(StampError):
    def __init__(self, prefix: str, matches: list[str]) -> None:
        super().__init__(prefix)
        self.prefix = prefix
        self.matches = matches

    def __str__(self) -> str:
        shown = ", ".join(m[:SHORT_HASH_LEN] for m in self.matches[:6])
        more = "" if len(self.matches) <= 6 else f", … ({len(self.matches)} total)"
        return f"{self.prefix!r} matches several stamps: {shown}{more}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_home() -> Path:
    env = os.environ.get("STAMP_HOME")
    return Path(env).expanduser() if env else Path.home() / ".stamp"


@dataclass
class Stamp:
    sha256: str
    url: str
    fetched_at: str
    title: str | None = None
    content_type: str = "application/octet-stream"
    size: int = 0
    requested_url: str | None = None
    final_url: str | None = None
    status: int | None = None
    number: int = 0
    description: str | None = None
    preview: str | None = None  # file name under stamps/, e.g. "<sha256>.preview.jpg"
    preview_source: str | None = None  # where the picture came from
    format: int = FORMAT_VERSION
    extra: dict = field(default_factory=dict)

    @property
    def short(self) -> str:
        return self.sha256[:SHORT_HASH_LEN]

    @property
    def host(self) -> str:
        return host_of(self.url)

    @property
    def date(self) -> str:
        return self.fetched_at[:10]

    @property
    def label(self) -> str:
        return self.title or self.url

    @property
    def address(self) -> str:
        """The URL as printed: without its scheme."""
        return re.sub(r"^https?://", "", self.url)

    @property
    def caption(self) -> str:
        """What the stamp prints in large type: the title, or the address."""
        return self.title or self.address

    @property
    def about(self) -> str:
        """The description block: the page's own words, or its address."""
        return self.description or self.address

    @property
    def qr_payload(self) -> str:
        return f"stamp:sha256:{self.sha256}"

    def to_json(self) -> str:
        d = asdict(self)
        extra = d.pop("extra")
        d.update(extra)
        return json.dumps(d, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Stamp":
        d = json.loads(text)
        known = {k: d.pop(k) for k in list(d) if k in cls.__dataclass_fields__ and k != "extra"}
        return cls(extra=d, **known)


class Album:
    def __init__(self, home: Path | str | None = None) -> None:
        self.home = Path(home).expanduser() if home else default_home()
        self.objects = self.home / "objects"
        self.stamps_dir = self.home / "stamps"

    # ------------------------------------------------------------ paths

    def ensure(self) -> None:
        self.objects.mkdir(parents=True, exist_ok=True)
        self.stamps_dir.mkdir(parents=True, exist_ok=True)

    def object_path(self, sha256: str) -> Path:
        return self.objects / sha256

    def meta_path(self, sha256: str) -> Path:
        return self.stamps_dir / f"{sha256}.json"

    def svg_path(self, sha256: str) -> Path:
        return self.stamps_dir / f"{sha256}.svg"

    def preview_path(self, stamp: Stamp) -> Path | None:
        if not stamp.preview or "/" in stamp.preview or stamp.preview.startswith("."):
            return None
        return self.stamps_dir / stamp.preview

    # ---------------------------------------------------------- reading

    def load_preview(self, stamp: Stamp) -> Preview | None:
        """The stamp's preview picture from disk, or ``None`` when it has none."""
        p = self.preview_path(stamp)
        if p is None or not p.is_file():
            return None
        data = p.read_bytes()
        mime = sniff_mime(data)
        return Preview(data=data, mime=mime) if mime else None

    def stamps(self) -> list[Stamp]:
        """All stamps, newest first."""
        if not self.stamps_dir.is_dir():
            return []
        out = []
        for p in self.stamps_dir.glob("*.json"):
            try:
                out.append(Stamp.from_json(p.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                continue
        out.sort(key=lambda s: (s.fetched_at, s.number), reverse=True)
        return out

    def has(self, body: bytes) -> bool:
        """True when these exact bytes already have a stamp."""
        return self.meta_path(sha256_hex(body)).is_file()

    def get(self, sha256: str) -> Stamp:
        p = self.meta_path(sha256)
        if not p.is_file():
            raise NotFound(sha256)
        return Stamp.from_json(p.read_text(encoding="utf-8"))

    def find(self, prefix: str) -> Stamp:
        """Look a stamp up by any unambiguous prefix of its hash."""
        prefix = prefix.strip().lower()
        if prefix.startswith("stamp:sha256:"):
            prefix = prefix[len("stamp:sha256:"):]
        elif prefix.startswith("sha256:"):
            prefix = prefix[len("sha256:"):]
        if not prefix or not _HEX.match(prefix):
            raise NotFound(prefix)
        if not self.stamps_dir.is_dir():
            raise NotFound(prefix)
        matches = sorted(p.stem for p in self.stamps_dir.glob(f"{prefix}*.json"))
        if not matches:
            raise NotFound(prefix)
        if len(matches) > 1:
            raise Ambiguous(prefix, matches)
        return self.get(matches[0])

    def read_bytes(self, stamp: Stamp) -> bytes:
        p = self.object_path(stamp.sha256)
        if not p.is_file():
            raise NotFound(stamp.sha256)
        return p.read_bytes()

    def verify(self, stamp: Stamp) -> bool:
        """True when the stored bytes still hash to the stamp's name."""
        try:
            return sha256_hex(self.read_bytes(stamp)) == stamp.sha256
        except NotFound:
            return False

    # ---------------------------------------------------------- writing

    def add(
        self,
        url: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        title: str | None = None,
        requested_url: str | None = None,
        final_url: str | None = None,
        status: int | None = None,
        fetched_at: str | None = None,
        description: str | None = None,
        preview: Preview | None = None,
        preview_source: str | None = None,
    ) -> tuple[Stamp, bool]:
        """File ``body`` under its hash and write a stamp for it.

        Returns ``(stamp, created)``; ``created`` is False when identical
        bytes were already in the album, in which case the existing stamp is
        returned untouched. Same page, same bytes, same stamp.

        ``preview`` is the page's picture, already shrunk; it is filed next
        to the stamp and drawn on it. ``description`` is what the page says
        about itself.
        """
        from .svg import render_stamp

        self.ensure()
        digest = sha256_hex(body)
        if self.meta_path(digest).is_file():
            return self.get(digest), False

        obj = self.object_path(digest)
        if not obj.is_file():
            _atomic_write(obj, body)

        preview_name = None
        if preview is not None:
            preview_name = f"{digest}.preview.{preview.ext}"
            _atomic_write(self.stamps_dir / preview_name, preview.data)

        stamp = Stamp(
            sha256=digest,
            url=url,
            fetched_at=fetched_at or utcnow_iso(),
            title=title,
            content_type=content_type,
            size=len(body),
            requested_url=requested_url,
            final_url=final_url if final_url != url else None,
            status=status,
            number=self._next_number(),
            description=description,
            preview=preview_name,
            preview_source=preview_source if preview_name else None,
        )
        _atomic_write(self.svg_path(digest), render_stamp(stamp, preview).encode("utf-8"))
        _atomic_write(self.meta_path(digest), stamp.to_json().encode("utf-8"))
        return stamp, True

    def redraw(self, stamp: Stamp) -> Path:
        """Draw the stamp again from its metadata and filed preview.

        Used after upgrading, so an older album takes on the current design;
        the bytes, hash and metadata are untouched.
        """
        from .svg import render_stamp

        self.ensure()
        path = self.svg_path(stamp.sha256)
        _atomic_write(path, render_stamp(stamp, self.load_preview(stamp)).encode("utf-8"))
        return path

    def _next_number(self) -> int:
        return max((s.number for s in self.stamps()), default=0) + 1


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
