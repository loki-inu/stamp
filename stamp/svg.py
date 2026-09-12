"""Drawing stamps, sheets of stamps, and the album page.

Everything here is plain SVG text. A stamp is laid out like an identity
card crossed with a till receipt: the issuing host and a FILED chip along
the top, the page's own preview picture in a panel, its title in large
type, a few lines about it, then a grid of date, hash, size and number
beside a QR code, and a solid footer bar carrying the address. Each stamp
is printed in a single ink chosen from its hash; the picture is printed in
that ink too, as a duotone.
"""

from __future__ import annotations

import base64
import colorsys
from datetime import datetime, timezone
from html import escape
from typing import Iterable, Sequence

from . import __version__, qr
from .preview import Preview
from .store import Stamp

# Stamp geometry, in user units.
W, H = 300, 400
PERF_R = 5.4
FRAME = 15  # inset of the card's rule from the perforated edge
MARGIN = 27  # inset of the content
PAPER = "#fbf8f1"
SERIF = "'Iowan Old Style','Palatino Linotype',Palatino,'Book Antiqua',Georgia,'Times New Roman',serif"
MONO = "'SF Mono',Menlo,Consolas,'Liberation Mono','DejaVu Sans Mono',monospace"

# The preview panel. Its shape matches preview.PREVIEW_W × PREVIEW_H.
PANEL = (MARGIN, 60, W - 2 * MARGIN, 139)
QR_SIZE = 63

PAPER_SIZES_MM = {"a4": (297.0, 210.0), "letter": (279.4, 215.9)}
MM_TO_PX = 96 / 25.4


# ---------------------------------------------------------------- palette

def ink_for(sha256: str) -> dict[str, str]:
    """A single printing ink and its tints, derived from the hash."""
    b = bytes.fromhex(sha256[:16])
    hue = b[0] / 255
    sat = 0.30 + (b[1] / 255) * 0.32
    light = 0.18 + (b[2] / 255) * 0.08

    def hexcolor(h: float, s: float, light_: float) -> str:
        r, g, bl = colorsys.hls_to_rgb(h, light_, s)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(bl * 255))

    return {
        "ink": hexcolor(hue, sat, light),
        "mid": hexcolor(hue, sat * 0.9, 0.48),
        "tint": hexcolor(hue, sat * 0.8, 0.80),
        "wash": hexcolor(hue, sat * 0.6, 0.94),
    }


def _rgb(hexcolor: str) -> tuple[float, float, float]:
    return tuple(int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


# -------------------------------------------------------------- utilities

def _esc(s: str) -> str:
    return escape(s, quote=True)


def _fmt(n: float) -> str:
    return f"{n:.2f}".rstrip("0").rstrip(".")


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB" if n >= 10 * 1024 else f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def shorten(text: str, max_chars: int) -> str:
    """Cut ``text`` to ``max_chars`` with an ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip(" ,.;:-/") + "…"


_BREAK_AFTER = ("/", "?&=", "-_", ".,;:")


def _split_long(word: str, max_chars: int) -> list[tuple[str, bool]]:
    """Cut an unbroken run (a URL, mostly) into pieces of at most ``max_chars``.

    Cuts fall after a slash where there is one, else after other
    punctuation, else wherever the line ends. Each piece is flagged with
    whether it continues the previous one without a space.
    """
    pieces: list[tuple[str, bool]] = []
    rest = word
    while len(rest) > max_chars:
        cut = 0
        for chars in _BREAK_AFTER:
            cut = max(rest.rfind(c, 1, max_chars) + 1 for c in chars)
            if cut >= max_chars // 3:
                break
        if cut < max_chars // 3:
            cut = max_chars
        pieces.append((rest[:cut], bool(pieces)))
        rest = rest[cut:]
    if rest:
        pieces.append((rest, bool(pieces)))
    return pieces


def wrap_title(text: str, max_chars: int = 36, max_lines: int = 2) -> list[str]:
    """Greedy word wrap with an ellipsis when the text will not fit."""
    words: list[tuple[str, bool]] = []
    for w in text.split():
        words.extend(_split_long(w, max_chars))
    lines: list[str] = []
    cur = ""
    truncated = False
    for w, glued in words:
        candidate = f"{cur}{w}" if glued else f"{cur} {w}".strip()
        if len(candidate) <= max_chars:
            cur = candidate
            continue
        lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            truncated = True
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if truncated and lines:
        last = lines[-1]
        if len(last) > max_chars - 1:
            last = last[: max_chars - 1]
        lines[-1] = last.rstrip(" ,.;:-/") + "…"
    return lines


def _perforations(w: float, h: float) -> list[tuple[float, float]]:
    nx = max(4, round(w / 14.2))
    ny = max(4, round(h / 14.2))
    pts = []
    for i in range(nx + 1):
        x = w * i / nx
        pts.append((x, 0.0))
        pts.append((x, h))
    for j in range(1, ny):
        y = h * j / ny
        pts.append((0.0, y))
        pts.append((w, y))
    return pts


def _text(
    x: float,
    y: float,
    s: str,
    size: float,
    family: str = MONO,
    fill: str = "#000",
    *,
    weight: str | None = None,
    style: str | None = None,
    anchor: str | None = None,
    spacing: float | None = None,
    opacity: float | None = None,
) -> str:
    attrs = [f'x="{_fmt(x)}"', f'y="{_fmt(y)}"', f'font-family="{family}"', f'font-size="{_fmt(size)}"', f'fill="{fill}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if style:
        attrs.append(f'font-style="{style}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if spacing is not None:
        attrs.append(f'letter-spacing="{_fmt(spacing)}"')
    if opacity is not None:
        attrs.append(f'opacity="{_fmt(opacity)}"')
    return f'<text {" ".join(attrs)}>{_esc(s)}</text>'


def _label(x: float, y: float, s: str, ink: str) -> str:
    """A tiny field label in the manner of an identity card."""
    return _text(x, y, s, 6.2, MONO, ink, weight="600", spacing=1.5, opacity=0.72)


# ------------------------------------------------------------- the parts

def _qr_svg(payload: str, p: str, x: float, y: float, size: float, color: str) -> str:
    code = qr.encode(payload, ecl=qr.ECL_M)
    n = code.size
    d = []
    for yy in range(n):
        run_start = None
        for xx in range(n + 1):
            dark = xx < n and code.dark(xx, yy)
            if dark and run_start is None:
                run_start = xx
            elif not dark and run_start is not None:
                d.append(f"M{run_start} {yy}h{xx - run_start}v1h-{xx - run_start}z")
                run_start = None
    return (
        f'<svg id="{p}-qr" x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(size)}" height="{_fmt(size)}" '
        f'viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
        f'<rect width="{n}" height="{n}" fill="{PAPER}"/>'
        f'<path d="{"".join(d)}" fill="{color}"/></svg>'
    )


def _duotone_filter(p: str, ink: str) -> str:
    """Maps a picture's luminance onto paper (light) → ink (dark)."""
    ir, ig, ib = _rgb(ink)
    pr, pg, pb = _rgb(PAPER)
    rows = []
    for i_c, p_c in ((ir, pr), (ig, pg), (ib, pb)):
        d = p_c - i_c
        rows.append(f"{_fmt(d * 0.2126)} {_fmt(d * 0.7152)} {_fmt(d * 0.0722)} 0 {_fmt(i_c)}")
    rows.append("0 0 0 1 0")
    return (
        f'<filter id="{p}-duo" color-interpolation-filters="sRGB" x="0" y="0" width="100%" height="100%">'
        f'<feColorMatrix type="matrix" values="{"  ".join(rows)}"/></filter>'
    )


def _tag(right: float, bottom: float, text: str, ink: str) -> str:
    """A small outlined tag, anchored by its bottom-right corner."""
    tag_w, tag_h = 10 + 3.75 * len(text) + 1.2 * (len(text) - 1), 12
    tx, ty = right - tag_w, bottom - tag_h
    return (
        f'<rect x="{_fmt(tx)}" y="{_fmt(ty)}" width="{_fmt(tag_w)}" height="{tag_h}" fill="{PAPER}" '
        f'stroke="{ink}" stroke-width="0.7"/>'
        + _text(tx + tag_w / 2, ty + 8.6, text, 6.2, MONO, ink, weight="600", anchor="middle", spacing=1.2)
    )


def _preview_panel(stamp: Stamp, preview: Preview | None, p: str, pal: dict[str, str]) -> str:
    x, y, w, h = PANEL
    ink = pal["ink"]
    out = []
    if preview is not None:
        uri = f"data:{preview.mime};base64,{base64.b64encode(preview.data).decode('ascii')}"
        # A picture smaller than the panel (a raw-embedded icon, without
        # Pillow) sits in the middle at a modest size instead of being blown up.
        small = preview.width and preview.height and preview.width < w * 1.5 and preview.height < h * 1.5
        if small:
            iw, ih = preview.width / 1.5, preview.height / 1.5  # type: ignore[operator]
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{PAPER}"/>')
            out.append(
                f'<image x="{_fmt(x + (w - iw) / 2)}" y="{_fmt(y + (h - ih) / 2)}" width="{_fmt(iw)}" height="{_fmt(ih)}" '
                f'preserveAspectRatio="xMidYMid meet" filter="url(#{p}-duo)" href="{uri}"/>'
            )
        else:
            out.append(
                f'<image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice" '
                f'clip-path="url(#{p}-panel)" filter="url(#{p}-duo)" href="{uri}"/>'
            )
        if stamp.preview_kind == "icon":
            out.append(_tag(x + w - 6, y + h - 6, "SITE ICON", ink))
    else:
        # An empty photo slot: ruled paper, a monogram of the host, and a tag.
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{pal["wash"]}"/>')
        rules = []
        yy = y + 6.0
        while yy < y + h - 3:
            rules.append(f"M{x + 4} {_fmt(yy)}H{x + w - 4}")
            yy += 5.0
        out.append(f'<path d="{"".join(rules)}" stroke="{ink}" stroke-width="0.45" opacity="0.22"/>')
        letter = next((c for c in stamp.host.upper() if c.isalnum()), "?")
        out.append(
            _text(x + w / 2, y + h / 2 + 27, letter, 78, SERIF, ink, weight="700", anchor="middle", opacity=0.16)
        )
        out.append(_tag(x + w - 6, y + h - 6, "NO PREVIEW", ink))
    # Frame and corner brackets, like the mount around an identity photograph.
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{ink}" stroke-width="1"/>')
    b, o = 6, 3.5
    for cx, cy, sx, sy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        out.append(
            f'<path d="M{_fmt(cx - sx * o)} {_fmt(cy - sy * o + sy * b)}v{_fmt(-sy * b)}h{_fmt(sx * b)}" '
            f'fill="none" stroke="{ink}" stroke-width="1.1"/>'
        )
    return "".join(out)


def _chip(x: float, y: float, text: str, ink: str) -> tuple[str, float]:
    """A small solid chip with a check mark; returns the markup and its width."""
    w = 16 + 5.6 * len(text) + 1.4 * (len(text) - 1)
    h = 15
    out = [f'<rect x="{_fmt(x - w)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{h}" rx="2" fill="{ink}"/>']
    cx = x - w + 5
    out.append(
        f'<path d="M{_fmt(cx)} {_fmt(y + 7.6)}l2.2 2.3 4.2-5" fill="none" stroke="{PAPER}" '
        f'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    out.append(_text(x - 6, y + 10.6, text, 7, MONO, PAPER, weight="700", anchor="end", spacing=1.4))
    return "".join(out), w


def _footer_bar(stamp: Stamp, ink: str) -> str:
    """A solid bar carrying the address and a hash-derived set of bars."""
    y0, y1 = H - FRAME - 16, H - FRAME
    out = [f'<rect x="{FRAME}" y="{y0}" width="{W - 2 * FRAME}" height="{y1 - y0}" fill="{ink}"/>']
    b = bytes.fromhex(stamp.sha256)
    # Bars read right to left so the address gets whatever room remains.
    xx = W - FRAME - 8.0
    bars = []
    for i in range(16):
        bw = 0.7 + (b[i] % 5) * 0.35
        xx -= bw
        bars.append(f'<rect x="{_fmt(xx)}" y="{y0 + 4}" width="{_fmt(bw)}" height="{y1 - y0 - 8}"/>')
        xx -= 1.1 + (b[16 + i] % 3) * 0.4
    out.append(f'<g fill="{PAPER}">{"".join(bars)}</g>')
    room = xx - 10 - (FRAME + 8)
    address = shorten(stamp.address, max(8, int(room / 4.35)))
    out.append(_text(FRAME + 8, y0 + 11, address, 7.2, MONO, PAPER, spacing=0.2, opacity=0.95))
    return "".join(out)


def _tear_line(y: float, ink: str) -> str:
    """A serrated edge across the card, with a notch at either side."""
    x0, x1 = FRAME, W - FRAME
    tooth = 3.0
    n = int((x1 - x0) / tooth)
    d = [f"M{x0} {_fmt(y + 1)}"]
    for i in range(n):
        d.append(f"l{_fmt(tooth / 2)} -2l{_fmt(tooth / 2)} 2")
    out = [f'<path d="{"".join(d)}" fill="none" stroke="{ink}" stroke-width="0.7" stroke-linejoin="round"/>']
    for nx in (x0, x1):
        out.append(f'<circle cx="{nx}" cy="{y}" r="3.2" fill="{PAPER}" stroke="{ink}" stroke-width="1.4"/>')
    return "".join(out)


def _ledger(stamp: Stamp, x0: float, x1: float, y: float, ink: str) -> str:
    """Receipt line items with dotted leaders, a rule, and the total row.

    The small items are the transaction: time, content type and status,
    byte count, album number. The total is what a collector reads first:
    the date and the short hash.
    """
    items: list[tuple[str, str]] = []
    if len(stamp.fetched_at) >= 19 and stamp.fetched_at[10] == "T":
        items.append(("TIME", f"{stamp.fetched_at[11:19]} UTC"))
    kind = stamp.content_type.split(";")[0].strip() or "unknown"
    items.append(("TYPE", f"{kind} · {stamp.status}" if stamp.status else kind))
    items.append(("BYTES", f"{stamp.size:,}"))
    items.append(("NO.", f"{stamp.number:03d}" if stamp.number else "—"))

    out = []
    room = x1 - x0
    yy = y + 8
    ry = y + 41  # the rule above the total row stays put however many items there are
    for label, value in items:
        value = shorten(value, max(6, int((room - 6.2 * len(label) - 14) / 4.45)))
        out.append(_label(x0, yy, label, ink))
        out.append(_text(x1, yy, value, 7.4, MONO, ink, anchor="end", opacity=0.92))
        lx0 = x0 + 5.1 * len(label) + 5
        lx1 = x1 - 4.45 * len(value) - 5
        if lx1 - lx0 > 6:
            out.append(
                f'<line x1="{_fmt(lx0)}" y1="{_fmt(yy - 1.6)}" x2="{_fmt(lx1)}" y2="{_fmt(yy - 1.6)}" '
                f'stroke="{ink}" stroke-width="0.7" stroke-dasharray="0.7 1.9" opacity="0.55"/>'
            )
        yy += 9.5
    out.append(f'<line x1="{x0}" y1="{_fmt(ry)}" x2="{x1}" y2="{_fmt(ry)}" stroke="{ink}" stroke-width="0.8" stroke-dasharray="2.2 1.8"/>')
    out.append(_label(x0, ry + 9, "DATE", ink))
    out.append(_text(x1, ry + 9, "SHA-256", 6.2, MONO, ink, weight="600", anchor="end", spacing=1.5, opacity=0.72))
    out.append(_text(x0, ry + 20.5, stamp.date, 11, MONO, ink, weight="700", spacing=0.3))
    out.append(_text(x1, ry + 20.5, stamp.short, 11, MONO, ink, weight="700", anchor="end", spacing=0.3))
    return "".join(out)


# ------------------------------------------------------------- the stamp

def stamp_body(stamp: Stamp, prefix: str = "s", preview: Preview | None = None) -> str:
    """The inner markup of one stamp, in a ``0 0 W H`` coordinate space.

    ``prefix`` namespaces the ids so several stamps can share a document.
    ``preview`` is the page's picture, if the album has one for it.
    """
    p = prefix
    pal = ink_for(stamp.sha256)
    ink = pal["ink"]
    left, right = MARGIN, W - MARGIN
    out: list[str] = []

    holes = _perforations(W, H)
    px, py, pw, ph = PANEL
    out.append("<defs>")
    out.append(f'<mask id="{p}-perf" maskUnits="userSpaceOnUse" x="-8" y="-8" width="{W + 16}" height="{H + 16}">')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fff"/>')
    out.append("".join(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{PERF_R}" fill="#000"/>' for cx, cy in holes))
    out.append("</mask>")
    out.append(f'<clipPath id="{p}-panel"><rect x="{px}" y="{py}" width="{pw}" height="{ph}"/></clipPath>')
    if preview is not None:
        out.append(_duotone_filter(p, ink))
    out.append("</defs>")

    # Paper with perforated edge, and a faint outline for each hole so the
    # perforation reads on white paper too.
    out.append(f'<g mask="url(#{p}-perf)"><rect x="0" y="0" width="{W}" height="{H}" fill="{PAPER}"/></g>')
    out.append('<g fill="none" stroke="#cfc8b8" stroke-width="0.6">')
    out.append("".join(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{PERF_R}"/>' for cx, cy in holes))
    out.append("</g>")

    # The card's rule.
    out.append(
        f'<rect x="{FRAME}" y="{FRAME}" width="{W - 2 * FRAME}" height="{H - 2 * FRAME}" fill="none" '
        f'stroke="{ink}" stroke-width="1.4"/>'
    )

    # Header: host, with a chip saying the bytes are filed, over a heavy rule.
    chip, chip_w = _chip(right, 26, "FILED", ink)
    out.append(chip)
    out.append(_label(left, 29, "HOST", ink))
    host_room = right - chip_w - 10 - left
    out.append(
        _text(left, 42, shorten(stamp.host.upper(), max(6, int(host_room / 8.0))), 11, MONO, ink, weight="700", spacing=1.8)
    )
    out.append(f'<line x1="{FRAME}" y1="52" x2="{W - FRAME}" y2="52" stroke="{ink}" stroke-width="1.4"/>')

    # The preview panel.
    out.append(_preview_panel(stamp, preview, p, pal))

    # Title, in large type.
    ty = py + ph + 21
    for line in wrap_title(stamp.caption, max_chars=32, max_lines=2):
        out.append(_text(left, ty, line, 15, SERIF, ink, weight="700"))
        ty += 18

    # About: what the page says about itself, or its address.
    ay = py + ph + 58
    out.append(_label(left, ay, "ABOUT", ink))
    out.append(f'<line x1="{left + 34}" y1="{ay - 2.4}" x2="{right}" y2="{ay - 2.4}" stroke="{ink}" stroke-width="0.5" opacity="0.5"/>')
    if stamp.description:
        lines = wrap_title(stamp.about, max_chars=60, max_lines=3)
        for i, line in enumerate(lines):
            out.append(_text(left, ay + 12 + i * 11, line, 9.2, SERIF, ink))
    else:
        for i, line in enumerate(wrap_title(stamp.about, max_chars=48, max_lines=3)):
            out.append(_text(left, ay + 12 + i * 11, line, 8.4, MONO, ink, opacity=0.9))

    # A serrated tear line, as on a till receipt, notched at the card's edge.
    out.append(_tear_line(298, ink))

    # The receipt: line items with leaders, a rule, and the total row.
    qx, qy = right - QR_SIZE, 305
    out.append(_ledger(stamp, left, qx - 12, 305, ink))
    out.append(_qr_svg(stamp.qr_payload, p, qx, qy, QR_SIZE, ink))

    out.append(_footer_bar(stamp, ink))
    return "".join(out)


def render_stamp(stamp: Stamp, preview: Preview | None = None) -> str:
    """A complete standalone SVG document for one stamp."""
    title = _esc(stamp.label)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="Stamp: {title}">\n'
        f"<title>{title}</title>\n"
        f"<desc>{_esc(stamp.url)} — fetched {_esc(stamp.fetched_at)} — sha256 {stamp.sha256}</desc>\n"
        f'<g id="stamp">{stamp_body(stamp, "s", preview)}</g>\n'
        "</svg>\n"
    )


# ------------------------------------------------------------- the sheet

def render_sheet(
    stamps: Sequence[Stamp],
    paper: str = "a4",
    title: str | None = None,
    previews: dict[str, Preview] | None = None,
) -> str:
    """Up to eight stamps on a landscape sheet, ready to print and cut.

    ``previews`` maps a stamp's hash to its picture, for those that have one.
    """
    stamps = list(stamps)[:8]
    previews = previews or {}
    wmm, hmm = PAPER_SIZES_MM[paper.lower()]
    pw, ph = wmm * MM_TO_PX, hmm * MM_TO_PX
    margin, gap, header, footer = 44.0, 22.0, 46.0, 30.0
    cols, rows = 4, 2

    scale_w = (pw - 2 * margin - (cols - 1) * gap) / (cols * W)
    scale_h = (ph - 2 * margin - header - footer - (rows - 1) * gap) / (rows * H)
    scale = min(scale_w, scale_h)
    sw, sh = W * scale, H * scale
    grid_w = cols * sw + (cols - 1) * gap
    grid_h = rows * sh + (rows - 1) * gap
    x0 = (pw - grid_w) / 2
    y0 = margin + header + (ph - 2 * margin - header - footer - grid_h) / 2

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    heading = title or "Stamp album · sheet of eight"
    ink = "#3b352c"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(wmm)}mm" height="{_fmt(hmm)}mm" '
        f'viewBox="0 0 {_fmt(pw)} {_fmt(ph)}" role="img" aria-label="{_esc(heading)}">\n',
        f"<title>{_esc(heading)}</title>\n",
        "<defs>"
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="125%">'
        '<feDropShadow dx="0" dy="1.6" stdDeviation="2.2" flood-color="#2a2318" flood-opacity="0.28"/>'
        "</filter>"
        '<pattern id="grain" width="6" height="6" patternUnits="userSpaceOnUse">'
        '<circle cx="1" cy="1" r="0.45" fill="#d9d0bf"/><circle cx="4" cy="4" r="0.35" fill="#d9d0bf"/>'
        "</pattern>"
        "</defs>\n",
        f'<rect width="{_fmt(pw)}" height="{_fmt(ph)}" fill="#efe9dd"/>',
        f'<rect width="{_fmt(pw)}" height="{_fmt(ph)}" fill="url(#grain)" opacity="0.6"/>',
        f'<rect x="{margin / 2}" y="{margin / 2}" width="{_fmt(pw - margin)}" height="{_fmt(ph - margin)}" '
        f'fill="none" stroke="{ink}" stroke-width="0.6" opacity="0.5"/>',
        f'<rect x="{margin / 2 + 4}" y="{margin / 2 + 4}" width="{_fmt(pw - margin - 8)}" '
        f'height="{_fmt(ph - margin - 8)}" fill="none" stroke="{ink}" stroke-width="0.3" opacity="0.5"/>',
        f'<text x="{_fmt(x0)}" y="{_fmt(margin + 24)}" font-family="{SERIF}" font-size="17" font-weight="600" '
        f'letter-spacing="3" fill="{ink}">{_esc(heading.upper())}</text>',
        f'<text x="{_fmt(x0 + grid_w)}" y="{_fmt(margin + 24)}" text-anchor="end" font-family="{MONO}" '
        f'font-size="10.5" letter-spacing="1" fill="{ink}" opacity="0.85">'
        f'{len(stamps)} OF 8 · PRINTED {today}</text>',
        f'<line x1="{_fmt(x0)}" y1="{_fmt(margin + 34)}" x2="{_fmt(x0 + grid_w)}" y2="{_fmt(margin + 34)}" '
        f'stroke="{ink}" stroke-width="0.7" opacity="0.7"/>',
    ]
    for i in range(cols * rows):
        c, r = i % cols, i // cols
        x = x0 + c * (sw + gap)
        y = y0 + r * (sh + gap)
        if i < len(stamps):
            s = stamps[i]
            out.append(
                f'<svg x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(sw)}" height="{_fmt(sh)}" '
                f'viewBox="-8 -8 {W + 16} {H + 16}" overflow="visible">'
                f"<title>{_esc(s.label)}</title><desc>{_esc(s.url)} — fetched {_esc(s.fetched_at)} — sha256 {s.sha256}</desc>"
                f'<g filter="url(#shadow)">{stamp_body(s, f"s{i}", previews.get(s.sha256))}</g></svg>'
            )
        else:
            out.append(
                f'<rect x="{_fmt(x + 6)}" y="{_fmt(y + 6)}" width="{_fmt(sw - 12)}" height="{_fmt(sh - 12)}" '
                f'fill="none" stroke="{ink}" stroke-width="0.6" stroke-dasharray="3 4" opacity="0.35"/>'
            )
    out.append(
        f'<text x="{_fmt(x0)}" y="{_fmt(ph - margin - 6)}" font-family="{MONO}" font-size="9" '
        f'letter-spacing="1" fill="{ink}" opacity="0.75">'
        "EACH CODE READS stamp:sha256:… — CHECK A STAMP WITH  stamp verify &lt;hash&gt;</text>"
    )
    out.append(
        f'<text x="{_fmt(x0 + grid_w)}" y="{_fmt(ph - margin - 6)}" text-anchor="end" font-family="{MONO}" '
        f'font-size="9" letter-spacing="1" fill="{ink}" opacity="0.75">STAMP {__version__} · '
        "GITHUB.COM/LOKI-INU/STAMP</text>"
    )
    out.append("\n</svg>\n")
    return "".join(out)


_SHEET_PAGE_CSS = """
@page { size: %(w)smm %(h)smm; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #2b2824; }
.bar { position: sticky; top: 0; display: flex; gap: 18px; align-items: center; padding: 12px 20px; background: #1c1a17;
  color: #cfc6b4; font: 13px/1.4 ui-monospace, Menlo, Consolas, monospace; border-bottom: 1px solid #3a352d; }
.bar b { color: #f1ebdd; letter-spacing: 2px; text-transform: uppercase; font-weight: 600; }
.bar span { color: #a79f8f; }
.bar button { margin-left: auto; padding: 7px 16px; border: 1px solid #a79f8f; border-radius: 3px; background: #f1ebdd;
  color: #1c1a17; font: inherit; font-weight: 600; letter-spacing: 1px; cursor: pointer; }
.bar button:hover { background: #fff; }
.page { width: %(w)smm; height: %(h)smm; margin: 28px auto; background: #fff; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
.page svg { display: block; width: %(w)smm; height: %(h)smm; }
@media print { html, body { background: #fff; } .bar { display: none; } .page { margin: 0; box-shadow: none; } }
"""


def render_sheet_page(sheet_svg: str, paper: str = "a4", title: str | None = None, count: int | None = None) -> str:
    """An HTML page that prints ``sheet_svg`` at exactly its paper size.

    Browsers print SVG files with their own idea of margins and scale; this
    wrapper pins the page size with ``@page`` so the sheet comes out at 100%
    on the paper it was drawn for. The SVG is inlined, so the page is one
    self-contained file that works from ``file://``.
    """
    wmm, hmm = PAPER_SIZES_MM[paper.lower()]
    heading = title or "Stamp album · sheet of eight"
    body = sheet_svg.split("?>", 1)[-1].strip() if sheet_svg.lstrip().startswith("<?xml") else sheet_svg
    counted = f"{count} stamp{'s' if count != 1 else ''} · " if count is not None else ""
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        f"<title>{_esc(heading)} — print</title>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<style>{_SHEET_PAGE_CSS % {'w': _fmt(wmm), 'h': _fmt(hmm)}}</style></head>\n"
        "<body>\n"
        f'<div class="bar"><b>{_esc(heading)}</b><span>{counted}{paper.upper()} landscape · print at 100%, no margins, '
        "on full-sheet label paper, then cut along the perforations</span>"
        '<button type="button" onclick="window.print()">Print</button></div>\n'
        f'<div class="page">{body}</div>\n'
        "</body></html>\n"
    )


# ------------------------------------------------------------- the album

_ALBUM_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #1c1a17; color: #e9e2d3; font: 15px/1.5 Georgia, 'Times New Roman', serif; }
header { padding: 40px 48px 24px; border-bottom: 1px solid #3a352d; display: flex; align-items: baseline; gap: 24px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 26px; font-weight: 600; letter-spacing: 3px; text-transform: uppercase; }
header p { margin: 0; color: #a79f8f; font-style: italic; }
main { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 40px 32px; padding: 40px 48px 64px; }
figure { margin: 0; text-align: center; }
figure a { display: inline-block; filter: drop-shadow(0 3px 6px rgba(0,0,0,.5)); transition: transform .15s ease; }
figure a:hover { transform: rotate(-1deg) scale(1.03); }
figure img { width: 100%; max-width: 260px; height: auto; display: block; }
figcaption { margin-top: 14px; font-size: 13px; color: #cfc6b4; }
figcaption b { display: block; font-weight: 600; color: #f1ebdd; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
figcaption a { color: #a79f8f; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
figcaption a:hover { color: #e9e2d3; text-decoration: underline; }
figcaption p { margin: 6px 0 4px; font-size: 12.5px; line-height: 1.4; color: #b9b09c; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
figcaption code { font: 12px/1 ui-monospace, Menlo, Consolas, monospace; color: #b9b09c; }
.empty { grid-column: 1 / -1; text-align: center; color: #a79f8f; padding: 80px 0; font-style: italic; }
footer { padding: 24px 48px 48px; color: #7f776a; font-size: 13px; border-top: 1px solid #3a352d; }
footer code { font: 12px ui-monospace, Menlo, Consolas, monospace; }
@media print { body { background: #fff; color: #222; } header, footer { display: none; } main { gap: 24px; } }
"""


def render_album(stamps: Iterable[Stamp], title: str = "Stamp album", *, toolbar: str = "", highlight: str | None = None) -> str:
    """A static, file://-friendly gallery of the album's stamps.

    ``toolbar`` is extra markup placed under the header (the local server
    puts its form and bookmarklet there); ``highlight`` is the hash of a
    stamp to single out.
    """
    stamps = list(stamps)
    cards = []
    for s in stamps:
        svg = f"stamps/{s.sha256}.svg"
        about = f"<p>{_esc(s.description)}</p>" if s.description else ""
        klass = ' class="new"' if s.sha256 == highlight else ""
        cards.append(
            f'<figure{klass} id="{s.short}">'
            f'<a href="{svg}" title="Open stamp"><img src="{svg}" alt="{_esc(s.label)}" loading="lazy"></a>'
            "<figcaption>"
            f"<b title=\"{_esc(s.label)}\">{_esc(s.label)}</b>"
            f'<a href="{_esc(s.url)}" title="{_esc(s.url)}">{_esc(s.host or s.url)}</a>'
            f"{about}"
            f"{_esc(s.date)} · <code>{s.short}</code> · {_esc(human_size(s.size))}"
            "</figcaption></figure>"
        )
    body = "".join(cards) if cards else '<p class="empty">No stamps yet. Try <code>stamp add https://example.com</code>.</p>'
    n = len(stamps)
    count = f"{n} stamp{'s' if n != 1 else ''}"
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        f"<title>{_esc(title)}</title>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<style>{_ALBUM_CSS}</style></head>\n"
        f"<body><header><h1>{_esc(title)}</h1><p>{count} · a personal collection of pages that mattered</p></header>\n"
        f"{toolbar}"
        f"<main>{body}</main>\n"
        f"<footer>Stamps are named by the SHA-256 of the bytes as fetched. "
        f"To check one against the original, run <code>stamp verify &lt;hash&gt;</code>. "
        f"Generated by stamp {__version__}.</footer>\n"
        "</body></html>\n"
    )
