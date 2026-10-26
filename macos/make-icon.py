"""Draw Stamp.icns. A perforated stamp, no extra libraries."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

W = 1024
CREAM = (251, 248, 241, 255)
INK = (47, 93, 52, 255)
HILL = (78, 130, 72, 255)
HILL_FAR = (168, 196, 150, 255)
SKY = (232, 236, 220, 255)


def png(w: int, h: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def scale(src: bytearray, sw: int, sh: int, dw: int, dh: int) -> bytes:
    out = bytearray(dw * dh * 4)
    for y in range(dh):
        y0 = y * sh // dh
        y1 = max(y0 + 1, (y + 1) * sh // dh)
        for x in range(dw):
            x0 = x * sw // dw
            x1 = max(x0 + 1, (x + 1) * sw // dw)
            acc = [0, 0, 0, 0]
            count = 0
            for yy in range(y0, y1):
                row = yy * sw
                for xx in range(x0, x1):
                    i = (row + xx) * 4
                    a = src[i + 3]
                    acc[0] += src[i] * a
                    acc[1] += src[i + 1] * a
                    acc[2] += src[i + 2] * a
                    acc[3] += a
                    count += 1
            j = (y * dw + x) * 4
            if acc[3] == 0 or count == 0:
                continue
            out[j] = acc[0] // acc[3]
            out[j + 1] = acc[1] // acc[3]
            out[j + 2] = acc[2] // acc[3]
            out[j + 3] = acc[3] // count
    return bytes(out)


def draw() -> bytearray:
    buf = bytearray(W * W * 4)
    left, top, right, bottom = 96, 64, 928, 960

    def put(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if 0 <= x < W and 0 <= y < W:
            i = (y * W + x) * 4
            buf[i:i + 4] = bytes(color)

    def fill_rect(x0, y0, x1, y1, color) -> None:
        for y in range(max(0, y0), min(W, y1)):
            row = y * W * 4
            span = bytes(color) * (min(W, x1) - max(0, x0))
            start = row + max(0, x0) * 4
            buf[start:start + len(span)] = span

    def clear_circle(cx, cy, r) -> None:
        r2 = r * r
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    put(x, y, (0, 0, 0, 0))

    def fill_circle(cx, cy, r, color) -> None:
        r2 = r * r
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    put(x, y, color)

    def stroke_rect(x0, y0, x1, y1, color, t) -> None:
        fill_rect(x0, y0, x1, y0 + t, color)
        fill_rect(x0, y1 - t, x1, y1, color)
        fill_rect(x0, y0, x0 + t, y1, color)
        fill_rect(x1 - t, y0, x1, y1, color)

    fill_rect(left, top, right, bottom, CREAM)
    hole = 26
    step = 46
    x = left
    while x <= right:
        clear_circle(x, top, hole)
        clear_circle(x, bottom, hole)
        x += step
    y = top
    while y <= bottom:
        clear_circle(left, y, hole)
        clear_circle(right, y, hole)
        y += step

    # Picture well.
    px0, py0, px1, py1 = 168, 150, 856, 560
    fill_rect(px0, py0, px1, py1, SKY)
    # Ridges, far then near.
    for y in range(py0, py1):
        t = (y - py0) / (py1 - py0)
        wave = int(36 * (0.5 + 0.5 * __import__("math").sin((y + 40) / 28)))
        if t > 0.42:
            color = HILL_FAR if t < 0.62 else HILL if t < 0.82 else INK
            fill_rect(px0, y, px1, y + 1, color)
            # a lighter notch so the ridge is not a flat block
            if t < 0.62:
                fill_rect(px0, y, px0 + 180 + wave, y + 1, SKY)
        # sky hatching
        elif (y - py0) % 7 == 0:
            fill_rect(px0, y, px1, y + 1, (210, 214, 196, 255))
    fill_circle(640, 270, 58, CREAM)
    fill_circle(640, 270, 30, INK)
    stroke_rect(px0, py0, px1, py1, INK, 6)
    stroke_rect(140, 118, 884, 908, INK, 8)
    stroke_rect(156, 134, 868, 892, INK, 3)
    # A short rule and a block of "type", so the icon reads as a card even tiny.
    fill_rect(200, 640, 620, 668, INK)
    fill_rect(200, 700, 520, 718, HILL)
    fill_rect(200, 736, 470, 754, HILL)
    fill_rect(200, 820, 360, 868, INK)
    return buf


def icns(images: dict[bytes, bytes]) -> bytes:
    body = b"".join(tag + struct.pack(">I", len(data) + 8) + data for tag, data in images.items())
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def main() -> None:
    here = Path(__file__).resolve().parent
    master = draw()
    sizes = {
        b"icp4": 16, b"icp5": 32, b"icp6": 64, b"ic07": 128,
        b"ic08": 256, b"ic09": 512, b"ic10": 1024,
        b"ic11": 32, b"ic12": 64, b"ic13": 256, b"ic14": 512,
    }
    packed = {}
    cache: dict[int, bytes] = {}
    for tag, size in sizes.items():
        if size not in cache:
            rgba = master if size == W else scale(master, W, W, size, size)
            cache[size] = png(size, size, rgba if isinstance(rgba, bytes) else bytes(rgba))
        packed[tag] = cache[size]
    (here / "Stamp.icns").write_bytes(icns(packed))
    (here / "icon-256.png").write_bytes(cache[256])
    print(f"wrote {here / 'Stamp.icns'} ({(here / 'Stamp.icns').stat().st_size} bytes)")


if __name__ == "__main__":
    main()
