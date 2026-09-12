"""Command line: ``stamp add | list | show | verify | sheet | album | diff | redraw | serve``."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from . import __version__
from .actions import FetchFailed, stamp_url
from .fetch import URLError, decode_text, visible_text
from .store import Album, Ambiguous, NotFound, Stamp, StampError
from .svg import PAPER_SIZES_MM, render_album, render_sheet, render_sheet_page


def _say(*parts: object) -> None:
    print(*parts)


def _err(msg: str) -> None:
    print(f"stamp: {msg}", file=sys.stderr)


# --------------------------------------------------------------- commands

def cmd_add(album: Album, args: argparse.Namespace) -> int:
    try:
        got = stamp_url(
            album,
            args.url,
            title=args.title,
            description=args.description,
            want_preview=not args.no_preview,
            timeout=args.timeout,
        )
    except URLError as e:
        _err(str(e))
        return 2
    except FetchFailed as e:
        _err(str(e))
        return 1
    for note in got.notes:
        _err(note)
    stamp = got.stamp
    if got.created:
        _say(f"stamped  {stamp.short}  {stamp.label}")
    else:
        _say(f"already in the album as {stamp.short} (same bytes, {stamp.date})")
    _say(f"         {album.svg_path(stamp.sha256)}")
    return 0


def cmd_list(album: Album, args: argparse.Namespace) -> int:
    stamps = album.stamps()
    if not stamps:
        _say("The album is empty. Try:  stamp add https://example.com")
        return 0
    for s in stamps:
        line = f"{s.date}  {s.short}  {s.label}"
        if s.title and args.urls:
            line += f"  <{s.url}>"
        _say(line)
    return 0


def cmd_show(album: Album, args: argparse.Namespace) -> int:
    s = album.find(args.hash)
    _say(f"stamp     {album.svg_path(s.sha256)}")
    _say(f"bytes     {album.object_path(s.sha256)}")
    _say(f"metadata  {album.meta_path(s.sha256)}")
    _say("")
    _say(f"title         {s.title or '—'}")
    _say(f"url           {s.url}")
    if s.final_url:
        _say(f"resolved to   {s.final_url}")
    _say(f"about         {s.description or '—'}")
    preview = album.preview_path(s)
    if preview is not None:
        _say(f"preview       {preview}")
        if s.preview_source:
            _say(f"preview from  {s.preview_source}")
    else:
        _say("preview       — (none)")
    _say(f"fetched       {s.fetched_at}")
    _say(f"sha256        {s.sha256}")
    _say(f"content-type  {s.content_type}")
    _say(f"size          {s.size} bytes")
    if s.number:
        _say(f"number        {s.number}")
    return 0


def cmd_verify(album: Album, args: argparse.Namespace) -> int:
    s = album.find(args.hash)
    if album.verify(s):
        _say(f"ok        {s.short}  bytes still hash to sha256:{s.sha256}")
        return 0
    _say(f"MISMATCH  {s.short}  stored bytes no longer hash to sha256:{s.sha256}")
    return 1


def cmd_sheet(album: Album, args: argparse.Namespace) -> int:
    stamps = album.stamps()
    if args.hashes:
        stamps = [album.find(h) for h in args.hashes]
    if not stamps:
        _err("nothing to print; the album is empty")
        return 1
    out = Path(args.out) if args.out else album.home / "sheet.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    stamps = stamps[:8]
    previews = {s.sha256: p for s in stamps if (p := album.load_preview(s)) is not None}
    svg = render_sheet(stamps, paper=args.paper, title=args.title, previews=previews)
    out.write_text(svg, encoding="utf-8")
    page = out.with_suffix(".html")
    page.write_text(render_sheet_page(svg, paper=args.paper, title=args.title, count=len(stamps)), encoding="utf-8")
    n = len(stamps)
    _say(f"sheet of {n} stamp{'s' if n != 1 else ''} ({args.paper.upper()}, landscape) -> {out}")
    _say(f"print-ready page                          -> {page}")
    return 0


def cmd_diff(album: Album, args: argparse.Namespace) -> int:
    new = album.find(args.hashes[0])
    if len(args.hashes) > 1:
        old = album.find(args.hashes[1])
    else:
        earlier = [s for s in album.stamps() if s.url == new.url and _order(s) < _order(new)]
        if not earlier:
            _err(f"no earlier stamp of {new.url} to compare {new.short} with")
            return 2
        old = earlier[0]  # stamps() is newest first, so this is the one just before
    if _order(old) > _order(new):
        old, new = new, old

    def lines(s: Stamp) -> list[str]:
        body = album.read_bytes(s)
        text = visible_text(body, s.content_type) if args.text else decode_text(body, s.content_type)
        return text.splitlines(keepends=True)

    a, b = lines(old), lines(new)
    out = list(
        difflib.unified_diff(a, b, fromfile=f"{old.short}  {old.fetched_at}  {old.url}", tofile=f"{new.short}  {new.fetched_at}  {new.url}", n=args.context)
    )
    for line in out:
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
    added = sum(1 for l in out[2:] if l.startswith("+"))
    removed = sum(1 for l in out[2:] if l.startswith("-"))
    what = "visible text" if args.text else "bytes"
    if not out:
        _say(f"same {what}: {old.short} ({old.date}) and {new.short} ({new.date})")
        return 0
    _say(f"--- {added} line{'s' if added != 1 else ''} added, {removed} removed ({what}) between {old.short} ({old.date}) and {new.short} ({new.date})")
    return 1


def _order(s: Stamp) -> tuple[str, int]:
    return (s.fetched_at, s.number)


def cmd_serve(album: Album, args: argparse.Namespace) -> int:
    from .serve import serve

    return serve(album, port=args.port, open_browser=args.open, timeout=args.timeout)


def cmd_redraw(album: Album, args: argparse.Namespace) -> int:
    stamps = album.stamps()
    if args.hashes:
        stamps = [album.find(h) for h in args.hashes]
    if not stamps:
        _say("The album is empty; nothing to redraw.")
        return 0
    for s in stamps:
        _say(f"redrawn  {s.short}  {album.redraw(s)}")
    return 0


def cmd_album(album: Album, args: argparse.Namespace) -> int:
    album.ensure()
    out = Path(args.out) if args.out else album.home / "album.html"
    stamps = album.stamps()
    out.write_text(render_album(stamps, title=args.title), encoding="utf-8")
    _say(f"album of {len(stamps)} stamp{'s' if len(stamps) != 1 else ''} -> {out}")
    if args.out and out.resolve().parent != album.home.resolve():
        _say(f"note: the page links to stamps/ relative to itself; keep it next to {album.stamps_dir}")
    return 0


# ----------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stamp",
        description="Postage stamps for the web. Snapshot a page, get a printable stamp, keep an album.",
        epilog="The album lives in $STAMP_HOME, or ~/.stamp when that is unset.",
    )
    parser.add_argument("--version", action="version", version=f"stamp {__version__}")
    parser.add_argument("--home", metavar="DIR", help="album directory (overrides $STAMP_HOME)")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("add", help="fetch a URL and add a stamp for it")
    p.add_argument("url")
    p.add_argument("--title", help="use this title instead of the page's own")
    p.add_argument("--description", help="use this description instead of the page's own")
    p.add_argument("--no-preview", action="store_true", help="do not fetch the page's preview picture")
    p.add_argument("--timeout", type=float, default=30, help="seconds to wait for the server (default 30)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="list the stamps in the album, newest first")
    p.add_argument("--urls", action="store_true", help="also show the URL for stamps with a title")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="where a stamp lives and what it knows")
    p.add_argument("hash", help="a hash or an unambiguous prefix of one")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", help="re-hash the stored bytes; exit 1 on mismatch")
    p.add_argument("hash", help="a hash or an unambiguous prefix of one")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("sheet", help="compose up to eight recent stamps into a printable sheet")
    p.add_argument("hashes", nargs="*", metavar="hash", help="specific stamps to print (default: the newest eight)")
    p.add_argument("--out", metavar="FILE", help="where to write the SVG (default: $STAMP_HOME/sheet.svg)")
    p.add_argument("--paper", choices=sorted(PAPER_SIZES_MM), default="a4", help="paper size (default a4)")
    p.add_argument("--title", help="heading printed on the sheet")
    p.set_defaults(func=cmd_sheet)

    p = sub.add_parser("album", help="write a static album.html gallery of every stamp")
    p.add_argument("--out", metavar="FILE", help="where to write the page (default: $STAMP_HOME/album.html)")
    p.add_argument("--title", default="Stamp album", help="page title")
    p.set_defaults(func=cmd_album)

    p = sub.add_parser("diff", help="what changed between two stamps of a page; exit 1 when they differ")
    p.add_argument("hashes", nargs="+", metavar="hash", help="a stamp, or two; one stamp is compared with the previous stamp of the same URL")
    p.add_argument("--text", action="store_true", help="compare the visible text rather than the raw bytes")
    p.add_argument("-U", "--context", type=int, default=2, metavar="N", help="lines of context (default 2)")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("serve", help="open the album in a browser and stamp pages with one click")
    p.add_argument("--port", type=int, default=7878, help="port on 127.0.0.1 (default 7878)")
    p.add_argument("--open", action="store_true", help="open the album page in your browser")
    p.add_argument("--timeout", type=float, default=30, help="seconds to wait for a page (default 30)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("redraw", help="draw stamps again in the current design; bytes and metadata stay put")
    p.add_argument("hashes", nargs="*", metavar="hash", help="specific stamps to redraw (default: all)")
    p.set_defaults(func=cmd_redraw)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    album = Album(args.home)
    try:
        return args.func(album, args)
    except Ambiguous as e:
        _err(str(e))
        return 2
    except NotFound as e:
        _err(f"no stamp matches {str(e)!r}")
        return 2
    except StampError as e:
        _err(str(e))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
