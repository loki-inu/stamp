"""Drawing stamps, sheets of stamps, and the album page.

Everything here is plain SVG text. Each stamp is engraved in a single ink
colour chosen from its hash, in the manner of classic definitive issues,
and carries a small landscape that is likewise drawn from the hash. No two
pages get the same picture.
"""

from __future__ import annotations

import colorsys
import math
from datetime import datetime, timezone
from html import escape
from typing import Iterable, Sequence

from . import __version__, qr
from .store import Stamp

# Stamp geometry, in user units.
W, H = 300, 380
PERF_R = 5.4
PAPER = "#fbf8f1"
SERIF = "'Iowan Old Style','Palatino Linotype',Palatino,'Book Antiqua',Georgia,'Times New Roman',serif"
MONO = "'SF Mono',Menlo,Consolas,'Liberation Mono','DejaVu Sans Mono',monospace"

PAPER_SIZES_MM = {"a4": (297.0, 210.0), "letter": (279.4, 215.9)}
MM_TO_PX = 96 / 25.4


# ---------------------------------------------------------------- palette

def ink_for(sha256: str) -> dict[str, str]:
    """A single printing ink and its tints, derived from the hash."""
    b = bytes.fromhex(sha256[:16])
    hue = b[0] / 255
    sat = 0.38 + (b[1] / 255) * 0.32
    light = 0.20 + (b[2] / 255) * 0.08

    def hexcolor(h: float, s: float, light_: float) -> str:
        r, g, bl = colorsys.hls_to_rgb(h, light_, s)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(bl * 255))

    return {
        "ink": hexcolor(hue, sat, light),
        "mid": hexcolor(hue, sat * 0.9, 0.48),
        "tint": hexcolor(hue, sat * 0.8, 0.80),
        "wash": hexcolor(hue, sat * 0.6, 0.93),
    }


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


def wrap_title(text: str, max_chars: int = 36, max_lines: int = 2) -> list[str]:
    """Greedy word wrap with an ellipsis when the title will not fit."""
    words: list[str] = []
    for w in text.split():
        # Unbroken runs (URLs, mostly) are cut into line-sized pieces.
        words.extend(w[i:i + max_chars] for i in range(0, len(w), max_chars))
    lines: list[str] = []
    cur = ""
    truncated = False
    for i, w in enumerate(words):
        candidate = f"{cur} {w}".strip()
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


# --------------------------------------------------------------- the art

def _landscape(sha256: str, p: str, x: float, y: float, w: float, h: float, pal: dict[str, str]) -> str:
    """A small engraved landscape whose every shape comes from the hash."""
    b = bytes.fromhex(sha256)
    ink, mid, tint, wash = pal["ink"], pal["mid"], pal["tint"], pal["wash"]
    out = [f'<g clip-path="url(#{p}-art)">']
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{wash}"/>')

    # Sky: engraved horizontal hatching that opens up towards the horizon.
    horizon = y + h * (0.50 + (b[3] / 255) * 0.18)
    yy = y + 3
    step = 2.4
    while yy < horizon - 4:
        t = (yy - y) / (horizon - y)
        out.append(
            f'<line x1="{x}" y1="{_fmt(yy)}" x2="{x + w}" y2="{_fmt(yy)}" '
            f'stroke="{ink}" stroke-width="0.5" opacity="{_fmt(0.34 * (1 - t) ** 1.6 + 0.03)}"/>'
        )
        yy += step
        step += 0.22

    # A sun or moon, with a halo of engraved rings.
    sun_x = x + w * (0.18 + (b[4] / 255) * 0.64)
    sun_y = y + (horizon - y) * (0.22 + (b[5] / 255) * 0.45)
    sun_r = 9 + (b[6] / 255) * 9
    for k, op in ((3.2, 0.10), (2.2, 0.16), (1.5, 0.24)):
        out.append(
            f'<circle cx="{_fmt(sun_x)}" cy="{_fmt(sun_y)}" r="{_fmt(sun_r * k)}" '
            f'fill="none" stroke="{ink}" stroke-width="0.6" opacity="{op}"/>'
        )
    out.append(
        f'<circle cx="{_fmt(sun_x)}" cy="{_fmt(sun_y)}" r="{_fmt(sun_r)}" fill="{PAPER}" '
        f'stroke="{ink}" stroke-width="1.1"/>'
    )
    out.append(
        f'<circle cx="{_fmt(sun_x)}" cy="{_fmt(sun_y)}" r="{_fmt(sun_r * 0.55)}" fill="none" '
        f'stroke="{ink}" stroke-width="0.5" opacity="0.5"/>'
    )

    # Birds.
    for i in range(b[7] % 4):
        bx = x + w * (0.1 + (b[8 + i] / 255) * 0.8)
        by = y + (horizon - y) * (0.15 + (b[12 + i] / 255) * 0.5)
        s = 3 + (b[16 + i] % 3)
        out.append(
            f'<path d="M{_fmt(bx - s)} {_fmt(by)} q{_fmt(s / 2)} {_fmt(-s * 0.7)} {_fmt(s)} 0 '
            f'q{_fmt(s / 2)} {_fmt(-s * 0.7)} {_fmt(s)} 0" fill="none" stroke="{ink}" '
            f'stroke-width="0.9" stroke-linecap="round"/>'
        )

    # Ridges, far to near, in deepening tints.
    layers = 4
    fills = (tint, mid, ink, ink)
    opacities = (0.55, 0.75, 0.86, 1.0)
    for li in range(layers):
        base = horizon + (y + h - horizon) * (li / layers) * 0.9
        amp = (h * 0.06) + (h * 0.16) * (1 - li / layers)
        seed = b[16 + li * 4: 20 + li * 4]
        n = 5 + seed[0] % 3
        pts = []
        for i in range(n + 1):
            px = x + w * i / n
            noise = (seed[(i + 1) % 4] / 255 - 0.5) * 2
            py = base - amp * (0.5 + 0.5 * math.sin(i * 1.7 + seed[3] / 40)) - amp * 0.6 * noise
            pts.append((px, min(max(py, y + 8), y + h)))
        d = f"M{_fmt(x - 2)} {_fmt(y + h + 2)} L{_fmt(pts[0][0] - 2)} {_fmt(pts[0][1])}"
        for i in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            cx = (x0 + x1) / 2
            d += f" C{_fmt(cx)} {_fmt(y0)} {_fmt(cx)} {_fmt(y1)} {_fmt(x1)} {_fmt(y1)}"
        d += f" L{_fmt(x + w + 2)} {_fmt(y + h + 2)} Z"
        out.append(f'<path d="{d}" fill="{fills[li]}" opacity="{opacities[li]}"/>')
        if li < layers - 1:
            out.append(f'<path d="{d}" fill="none" stroke="{ink}" stroke-width="0.6" opacity="0.6"/>')

    # Foreground hatching for the near ground.
    yy = y + h - 2
    while yy > horizon + (y + h - horizon) * 0.72:
        out.append(
            f'<line x1="{x}" y1="{_fmt(yy)}" x2="{x + w}" y2="{_fmt(yy)}" stroke="{PAPER}" '
            f'stroke-width="0.4" opacity="0.22"/>'
        )
        yy -= 3.1
    out.append("</g>")
    return "".join(out)


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


# ------------------------------------------------------------- the stamp

def stamp_body(stamp: Stamp, prefix: str = "s") -> str:
    """The inner markup of one stamp, in a ``0 0 W H`` coordinate space.

    ``prefix`` namespaces the ids so several stamps can share a document.
    """
    p = prefix
    pal = ink_for(stamp.sha256)
    ink = pal["ink"]
    out: list[str] = []

    holes = _perforations(W, H)
    out.append("<defs>")
    out.append(f'<mask id="{p}-perf" maskUnits="userSpaceOnUse" x="-8" y="-8" width="{W + 16}" height="{H + 16}">')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fff"/>')
    out.append("".join(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{PERF_R}" fill="#000"/>' for cx, cy in holes))
    out.append("</mask>")
    ax, ay, aw, ah = 26, 60, W - 52, 150
    out.append(f'<clipPath id="{p}-art"><rect x="{ax}" y="{ay}" width="{aw}" height="{ah}"/></clipPath>')
    out.append("</defs>")

    # Paper with perforated edge, and a faint outline for each hole so the
    # perforation reads on white paper too.
    out.append(f'<g mask="url(#{p}-perf)"><rect x="0" y="0" width="{W}" height="{H}" fill="{PAPER}"/></g>')
    out.append('<g fill="none" stroke="#cfc8b8" stroke-width="0.6">')
    out.append("".join(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{PERF_R}"/>' for cx, cy in holes))
    out.append("</g>")

    # Frames.
    out.append(f'<rect x="15" y="15" width="{W - 30}" height="{H - 30}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    out.append(f'<rect x="19" y="19" width="{W - 38}" height="{H - 38}" fill="none" stroke="{ink}" stroke-width="0.5"/>')
    for cx, cy in ((19, 19), (W - 19, 19), (19, H - 19), (W - 19, H - 19)):
        out.append(
            f'<path d="M{cx} {cy - 4.5}l4.5 4.5-4.5 4.5-4.5-4.5z" fill="{PAPER}" stroke="{ink}" stroke-width="0.9"/>'
        )

    # Issuing host, in letter-spaced capitals, with rules either side.
    host = stamp.host.upper()
    if len(host) > 30:
        host = host[:29] + "…"
    out.append(
        f'<text x="{W / 2}" y="46" text-anchor="middle" font-family="{SERIF}" font-size="12.5" '
        f'font-weight="600" letter-spacing="2.4" fill="{ink}">{_esc(host)}</text>'
    )
    rule_w = max(0.0, (W - 52 - 8.5 * len(host)) / 2 - 12)
    if rule_w > 10:
        out.append(f'<line x1="26" y1="42" x2="{_fmt(26 + rule_w)}" y2="42" stroke="{ink}" stroke-width="0.7"/>')
        out.append(f'<line x1="{_fmt(W - 26 - rule_w)}" y1="42" x2="{W - 26}" y2="42" stroke="{ink}" stroke-width="0.7"/>')

    # The picture.
    out.append(_landscape(stamp.sha256, p, ax, ay, aw, ah, pal))
    out.append(f'<rect x="{ax}" y="{ay}" width="{aw}" height="{ah}" fill="none" stroke="{ink}" stroke-width="1.1"/>')
    out.append(
        f'<rect x="{ax + 3}" y="{ay + 3}" width="{aw - 6}" height="{ah - 6}" fill="none" '
        f'stroke="{PAPER}" stroke-width="0.6" opacity="0.7"/>'
    )

    # Title.
    lines = wrap_title(stamp.caption)
    ty = ay + ah + 24
    for line in lines:
        out.append(
            f'<text x="{W / 2}" y="{ty}" text-anchor="middle" font-family="{SERIF}" font-size="13.5" '
            f'font-style="italic" fill="{ink}">{_esc(line)}</text>'
        )
        ty += 17
    if len(lines) < 2:
        ty += 17

    # Date, hash and denomination on the left; QR on the right.
    qr_size = 74
    qx, qy = W - 26 - qr_size, H - 30 - qr_size - 6
    lx = 28
    out.append(f'<line x1="{lx}" y1="{qy + 2}" x2="{qx - 12}" y2="{qy + 2}" stroke="{ink}" stroke-width="0.6"/>')
    out.append(
        f'<text x="{lx}" y="{qy + 24}" font-family="{SERIF}" font-size="19" font-weight="600" '
        f'letter-spacing="1" fill="{ink}">{_esc(stamp.date)}</text>'
    )
    out.append(
        f'<text x="{lx}" y="{qy + 40}" font-family="{SERIF}" font-size="8.5" letter-spacing="1.8" '
        f'fill="{ink}" opacity="0.8">SHA-256</text>'
    )
    out.append(
        f'<text x="{lx}" y="{qy + 55}" font-family="{MONO}" font-size="13" letter-spacing="0.6" '
        f'fill="{ink}">{stamp.short}</text>'
    )
    denom = human_size(stamp.size)
    number = f"No. {stamp.number}" if stamp.number else ""
    out.append(
        f'<text x="{lx}" y="{qy + 74}" font-family="{SERIF}" font-size="10.5" letter-spacing="0.8" '
        f'fill="{ink}" opacity="0.85">{_esc(" · ".join(x for x in (number, denom) if x))}</text>'
    )
    out.append(_qr_svg(stamp.qr_payload, p, qx, qy, qr_size, ink))
    return "".join(out)


def render_stamp(stamp: Stamp) -> str:
    """A complete standalone SVG document for one stamp."""
    title = _esc(stamp.label)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="Stamp: {title}">\n'
        f"<title>{title}</title>\n"
        f"<desc>{_esc(stamp.url)} — fetched {_esc(stamp.fetched_at)} — sha256 {stamp.sha256}</desc>\n"
        f'<g id="stamp">{stamp_body(stamp)}</g>\n'
        "</svg>\n"
    )


# ------------------------------------------------------------- the sheet

def render_sheet(stamps: Sequence[Stamp], paper: str = "a4", title: str | None = None) -> str:
    """Up to eight stamps on a landscape sheet, ready to print and cut."""
    stamps = list(stamps)[:8]
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
        f'<text x="{_fmt(x0 + grid_w)}" y="{_fmt(margin + 24)}" text-anchor="end" font-family="{SERIF}" '
        f'font-size="12" font-style="italic" fill="{ink}" opacity="0.85">'
        f'{len(stamps)} of 8 · printed {today}</text>',
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
                f'<g filter="url(#shadow)">{stamp_body(s, prefix=f"s{i}")}</g></svg>'
            )
        else:
            out.append(
                f'<rect x="{_fmt(x + 6)}" y="{_fmt(y + 6)}" width="{_fmt(sw - 12)}" height="{_fmt(sh - 12)}" '
                f'fill="none" stroke="{ink}" stroke-width="0.6" stroke-dasharray="3 4" opacity="0.35"/>'
            )
    out.append(
        f'<text x="{_fmt(x0)}" y="{_fmt(ph - margin - 6)}" font-family="{SERIF}" font-size="10" '
        f'letter-spacing="1" fill="{ink}" opacity="0.75">'
        "EACH CODE READS stamp:sha256:… — CHECK A STAMP WITH  stamp verify &lt;hash&gt;</text>"
    )
    out.append(
        f'<text x="{_fmt(x0 + grid_w)}" y="{_fmt(ph - margin - 6)}" text-anchor="end" font-family="{SERIF}" '
        f'font-size="10" letter-spacing="1" fill="{ink}" opacity="0.75">STAMP {__version__} · '
        "GITHUB.COM/LOKI-INU/STAMP</text>"
    )
    out.append("\n</svg>\n")
    return "".join(out)


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
figcaption code { font: 12px/1 ui-monospace, Menlo, Consolas, monospace; color: #b9b09c; }
.empty { grid-column: 1 / -1; text-align: center; color: #a79f8f; padding: 80px 0; font-style: italic; }
footer { padding: 24px 48px 48px; color: #7f776a; font-size: 13px; border-top: 1px solid #3a352d; }
footer code { font: 12px ui-monospace, Menlo, Consolas, monospace; }
@media print { body { background: #fff; color: #222; } header, footer { display: none; } main { gap: 24px; } }
"""


def render_album(stamps: Iterable[Stamp], title: str = "Stamp album") -> str:
    """A static, file://-friendly gallery of the album's stamps."""
    stamps = list(stamps)
    cards = []
    for s in stamps:
        svg = f"stamps/{s.sha256}.svg"
        cards.append(
            "<figure>"
            f'<a href="{svg}" title="Open stamp"><img src="{svg}" alt="{_esc(s.label)}" loading="lazy"></a>'
            "<figcaption>"
            f"<b title=\"{_esc(s.label)}\">{_esc(s.label)}</b>"
            f'<a href="{_esc(s.url)}" title="{_esc(s.url)}">{_esc(s.host or s.url)}</a>'
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
        f"<main>{body}</main>\n"
        f"<footer>Stamps are named by the SHA-256 of the bytes as fetched. "
        f"To check one against the original, run <code>stamp verify &lt;hash&gt;</code>. "
        f"Generated by stamp {__version__}.</footer>\n"
        "</body></html>\n"
    )
