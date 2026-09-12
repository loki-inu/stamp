# stamp

**Postage stamps for the web.**

`stamp add URL` fetches a page, files the bytes away under their SHA-256, and
prints a small postage stamp for it. The stamp is laid out like an identity
card for the page: the host and a FILED chip across the top, the page's own
preview picture, its title in large type, a few lines about what it is, then
a receipt of the fetch: time, type, bytes and album number as line items,
with the date and short hash as the total, beside a QR code that carries the
full hash. Stamps collect in a local album. When you have a few, print a
sheet of eight and cut along the perforations. `stamp serve` puts the album
in your browser and gives you a bookmarklet, so stamping the page you are
reading is one click.

<p align="center">
  <img src="docs/example-sheet.svg" alt="A landscape sheet of eight web stamps: NPR, NASA, two Wikipedia articles, an RFC, MDN, Project Gutenberg and PEP 20, each with its preview picture, description and QR code" width="100%">
</p>

This is philately, not archiving. It is not a crawler, not a bulk mirror, and
not a notary. It is a stamp album for the pages that mattered to you: the post
that changed your mind, the docs you lived in for a year, the page a friend
made, the front page on the morning something happened.

## Install

Python 3.11 or newer. The standard library does the fetching, hashing,
drawing and QR codes. [Pillow](https://python-pillow.org/) is optional: with
it, each page's preview picture is shrunk to a small greyscale JPEG and
printed on the stamp; without it, only pictures that are already small are
embedded and the rest get an empty "NO PREVIEW" slot.

```sh
pip install 'stamp-philately[preview] @ git+https://github.com/loki-inu/stamp'
```

Leave off `[preview]` for the pure standard-library install.

Or, for hacking on it:

```sh
git clone https://github.com/loki-inu/stamp
cd stamp
pip install -e '.[dev]'
pytest
```

## Quickstart

```sh
$ stamp add https://peps.python.org/pep-0020/
stamped  335ce9a69a87  PEP 20 – The Zen of Python | peps.python.org
         ~/.stamp/stamps/335ce9a69a87…d1.svg

$ stamp add en.wikipedia.org/wiki/Penny_Black
stamped  b7334ca03759  Penny Black - Wikipedia
         ~/.stamp/stamps/b7334ca03759…71.svg

$ stamp list
2026-09-12  b7334ca03759  Penny Black - Wikipedia
2026-09-12  335ce9a69a87  PEP 20 – The Zen of Python | peps.python.org

$ stamp verify 335c
ok        335ce9a69a87  bytes still hash to sha256:335ce9a69a87…

$ stamp sheet --paper letter
sheet of 2 stamps (LETTER, landscape) -> ~/.stamp/sheet.svg
print-ready page                          -> ~/.stamp/sheet.html

$ stamp album
album of 2 stamps -> ~/.stamp/album.html

$ stamp serve
stamp album at http://127.0.0.1:7878   (Ctrl-C to stop)
one-click stamping: drag the “Stamp this page” link from that page to your bookmarks bar
```

Open `sheet.html` and print it; open `album.html` to browse the collection.
Both are plain files that work from `file://` with no server. Or run
`stamp serve` and use the album page's form and bookmarklet instead.

## Stamping from the browser

`stamp serve` starts a small server on `127.0.0.1` only. The album page it
serves has a box to paste a URL into and a **Stamp this page** link: drag
that to your bookmarks bar, and clicking it on any page opens a small window
in which a receipt printer fetches the page and the new stamp slides out of
the slot. There is a **Print sheet** button, and the album page marks the
stamp you just added.

Every request that makes a stamp must carry a token that the server prints
when it starts and bakes into the bookmarklet, so a web page you happen to be
on cannot slip things into your album. The server refuses requests that are
not addressed to localhost. There is a small JSON API for your own scripts:

```sh
curl -X POST http://127.0.0.1:7878/add -d url=https://example.com -d token=…
curl http://127.0.0.1:7878/api/stamps
```

## Printing

`stamp sheet` writes `sheet.svg` and, beside it, `sheet.html`, which pins
the page size with `@page` so a browser prints the sheet at exactly A4 or
Letter with no margins. Print it at 100% on full-sheet label paper (A4 label
sheets, or Avery 8165 and the like for Letter), then cut along the
perforations. `stamp serve` has the same page at `/sheet`.

## What changed?

The same URL stamped on two days gives two stamps when the bytes differ.
`stamp diff HASH` shows what changed against the previous stamp of the same
page, as a unified diff of the raw bytes; `stamp diff --text HASH` compares
the visible text instead, which tells you whether the *page* changed or only
its plumbing. Give it two hashes to compare any pair. It exits 1 when they
differ, like `diff`.

<p align="center">
  <img src="docs/example-stamp.svg" alt="One stamp for peps.python.org: the Python logo in olive ink, the title PEP 20 – The Zen of Python, a three-line description, a receipt of time, type, bytes and number, the date and short hash in bold, and a QR code" width="300">
  &nbsp;&nbsp;
  <img src="docs/example-stamp-no-preview.svg" alt="One stamp for rfc-editor.org, a page with no title or picture: an empty ruled photo slot with a large R monogram and a NO PREVIEW tag, the URL in place of a title" width="300">
</p>

Left: a page that describes itself with Open Graph tags. Right: a page that
offers nothing but bytes, so the stamp shows its address and an empty slot.

## Commands

| Command | What it does |
| --- | --- |
| `stamp add URL [--title T] [--description D] [--no-preview]` | Fetch the URL, store the bytes and metadata, fetch the page's preview picture, print a stamp. Same bytes twice gives the same stamp once. |
| `stamp list [--urls]` | Every stamp, newest first: date, short hash, title or URL. |
| `stamp show HASH` | Paths to the stamp, the bytes, the metadata and the preview picture, plus what it knows about the page. |
| `stamp verify HASH` | Re-hash the stored bytes. Exit 0 when they still match, 1 when they do not. |
| `stamp sheet [HASH…] [--out F] [--paper a4\|letter] [--title T]` | Lay up to eight stamps out on a landscape sheet, as `sheet.svg` plus a print-ready `sheet.html`. Defaults to the newest eight. |
| `stamp album [--out F]` | Write a static `album.html` gallery of every stamp. |
| `stamp serve [--port N] [--open]` | Serve the album on localhost with a form, a bookmarklet, the print page and a JSON API. |
| `stamp diff HASH [HASH] [--text]` | What changed between two stamps of a page, or between a stamp and the previous one of the same URL. |
| `stamp redraw [HASH…]` | Draw stamps again in the current design. Bytes, hashes and metadata are untouched; use it after upgrading. |

`HASH` may be any unambiguous prefix, the full hash, or the `stamp:sha256:…`
string a QR code scans to.

## The album on disk

Everything lives in one directory, `~/.stamp` by default, or wherever
`$STAMP_HOME` (or `--home`) points. Nothing else is written anywhere, nothing
phones home, and there is no account to make. The only requests `stamp add`
makes are for the page itself and, when the page names one, its preview
picture.

```
~/.stamp/
  objects/<sha256>              the bytes exactly as the server sent them
  stamps/<sha256>.json          url, fetched_at (UTC), sha256, title, description, content-type, size, preview
  stamps/<sha256>.svg           the stamp
  stamps/<sha256>.preview.jpg   the page's preview picture, shrunk (only when it had one)
  sheet.svg, sheet.html         the last sheet, and its print-ready page
  album.html                    the gallery
```

Stamps are content-addressed: the name of a stamp is the SHA-256 of the page
bytes. The same page fetched again with identical bytes is the same stamp; a
page that changed gets a new one, which is exactly what a collector wants. The
store is plain files, so `rsync`, `git` or a USB stick are all fine ways to
carry an album around. Albums written by earlier versions read fine; run
`stamp redraw` to give old stamps the current design.

## Anatomy of a stamp

Each stamp is printed in a single ink chosen from its hash, so a sheet has
some variety and the same page always comes out in the same colour. The
layout is fixed, like a card, so the eye knows where to find things.

- **Host** across the top in letter-spaced capitals, and a **FILED** chip.
  FILED means the bytes are filed in your album under their hash; it claims
  nothing about the page's truth or provenance.
- **Preview**: the picture the page advertises for sharing (`og:image`,
  `twitter:image` or `<link rel=image_src>`), printed as a duotone in the
  stamp's ink. A page with no picture but a decent-sized icon
  (`apple-touch-icon` or a large `rel=icon`) gets that, tagged **SITE ICON**.
  Pages with neither get a ruled empty slot with the host's monogram and a
  **NO PREVIEW** tag.
- **Title** of the page in large type, or the URL when a page has no title.
- **About**: two or three lines from `og:description`, the meta description,
  or the first real paragraph of the page; failing all of those, the address.
- Below a serrated tear line, the **receipt**: line items with dotted
  leaders for the time of the fetch (UTC), the content type and HTTP status,
  the exact byte count and the stamp's **number** in your album; then a rule
  and the total row, the **date** (`YYYY-MM-DD`, UTC) and the **SHA-256**
  short hash (first twelve hex digits), in bold.
- **QR code** encoding `stamp:sha256:<full hash>`, so a printed stamp can be
  looked up again.
- A **footer bar** with the address and a hash-derived set of bars.

Stamps are SVG, so they scale to any size and print crisply. The only raster
in one is the preview picture, embedded as a small JPEG so the stamp is a
single self-contained file. A sheet uses nested SVGs, so each stamp on it is
the same drawing you would get on its own.

## Regenerating the examples

The pictures in this README are made from live pages by

```sh
sh docs/make-examples.sh
```

which stamps eight public pages into a throwaway album, writes
`docs/example-sheet.svg`, and copies out `docs/example-stamp.svg` (PEP 20)
and `docs/example-stamp-no-preview.svg` (an RFC with no metadata).

## What it is not

`stamp` keeps the bytes a server handed it over plain HTTP(S) at one moment in
time, plus one picture the page pointed at. It fetches as itself, without
your cookies, so it sees the public page and not your logged-in view, and
two people stamping the same page get the same hash. It does not run scripts, render
pages, save WARC files, fetch stylesheets, or witness anything. A stamp says
*I was here, and this is what I saw*; it is a keepsake, not evidence, and
makes no claim to be proof of anything in any forum. For bulk archiving, use
an archiver.

## License

MIT. See [LICENSE](LICENSE).
