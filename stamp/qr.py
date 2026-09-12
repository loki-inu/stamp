"""A small QR Code encoder (ISO/IEC 18004), byte mode, versions 1-40.

Only what a stamp needs: turn a short string into a matrix of dark/light
modules. No image output here; ``svg.py`` draws the modules.
"""

from __future__ import annotations

from dataclasses import dataclass

# Error-correction levels, indexed L, M, Q, H.
ECL_L, ECL_M, ECL_Q, ECL_H = 0, 1, 2, 3
_ECL_FORMAT_BITS = (1, 0, 3, 2)

# ECC codewords per block and number of blocks, per level, versions 1..40.
_ECC_PER_BLOCK = (
    (7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28,
     28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
     26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30,
     28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28,
     30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)
_NUM_BLOCKS = (
    (1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8,
     8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    (1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
     17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    (1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20,
     23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25,
     25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)


@dataclass(frozen=True)
class QRCode:
    version: int
    ecl: int
    mask: int
    size: int
    modules: tuple[tuple[bool, ...], ...]

    def dark(self, x: int, y: int) -> bool:
        return self.modules[y][x]


# ---------------------------------------------------------------- GF(256)

def _gf_mul(a: int, b: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((b >> i) & 1) * a
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: bytes, divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ------------------------------------------------------------- capacities

def _raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver: int, ecl: int) -> int:
    return _raw_data_modules(ver) // 8 - _ECC_PER_BLOCK[ecl][ver - 1] * _NUM_BLOCKS[ecl][ver - 1]


def _byte_mode_bits(nbytes: int, ver: int) -> int:
    return 4 + (8 if ver <= 9 else 16) + 8 * nbytes


def _alignment_positions(ver: int) -> list[int]:
    if ver == 1:
        return []
    numalign = ver // 7 + 2
    size = ver * 4 + 17
    step = 26 if ver == 32 else (ver * 8 + numalign * 3 + 5) // (numalign * 4 - 4) * 2
    result = [6]
    pos = size - 7
    for _ in range(numalign - 1):
        result.insert(1, pos)
        pos -= step
    return result


# --------------------------------------------------------------- encoding

class _BitBuffer(list):
    def append_bits(self, val: int, n: int) -> None:
        self.extend(((val >> i) & 1) for i in range(n - 1, -1, -1))


def _encode_data(data: bytes, ver: int, ecl: int) -> bytes:
    capacity_bits = _data_codewords(ver, ecl) * 8
    bb = _BitBuffer()
    bb.append_bits(0x4, 4)
    bb.append_bits(len(data), 8 if ver <= 9 else 16)
    for b in data:
        bb.append_bits(b, 8)
    bb.append_bits(0, min(4, capacity_bits - len(bb)))
    bb.append_bits(0, -len(bb) % 8)
    for pad in (0xEC, 0x11) * ((capacity_bits - len(bb)) // 16 + 1):
        if len(bb) >= capacity_bits:
            break
        bb.append_bits(pad, 8)
    out = bytearray()
    for i in range(0, len(bb), 8):
        byte = 0
        for bit in bb[i:i + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
    return bytes(out)


def _add_ecc_and_interleave(data: bytes, ver: int, ecl: int) -> bytes:
    numblocks = _NUM_BLOCKS[ecl][ver - 1]
    blockecclen = _ECC_PER_BLOCK[ecl][ver - 1]
    rawcodewords = _raw_data_modules(ver) // 8
    numshortblocks = numblocks - rawcodewords % numblocks
    shortblocklen = rawcodewords // numblocks

    blocks: list[bytes] = []
    divisor = _rs_divisor(blockecclen)
    k = 0
    for i in range(numblocks):
        datlen = shortblocklen - blockecclen + (0 if i < numshortblocks else 1)
        dat = data[k:k + datlen]
        k += datlen
        ecc = bytes(_rs_remainder(dat, divisor))
        if i < numshortblocks:
            dat += b"\0"
        blocks.append(dat + ecc)

    result = bytearray()
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortblocklen - blockecclen or j >= numshortblocks:
                result.append(blk[i])
    return bytes(result)


# ---------------------------------------------------------------- drawing

class _Canvas:
    def __init__(self, ver: int, ecl: int) -> None:
        self.ver = ver
        self.ecl = ecl
        self.size = ver * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        self._draw_finder(3, 3)
        self._draw_finder(size - 4, 3)
        self._draw_finder(3, size - 4)
        align = _alignment_positions(self.ver)
        n = len(align)
        for i in range(n):
            for j in range(n):
                if (i, j) in ((0, 0), (0, n - 1), (n - 1, 0)):
                    continue
                self._draw_alignment(align[i], align[j])
        self.draw_format_bits(0)
        self._draw_version()

    def _draw_finder(self, x: int, y: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.size and 0 <= yy < self.size:
                    dist = max(abs(dx), abs(dy))
                    self.set_function(xx, yy, dist not in (2, 4))

    def _draw_alignment(self, x: int, y: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self.set_function(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format_bits(self, mask: int) -> None:
        data = _ECL_FORMAT_BITS[self.ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        size = self.size
        for i in range(6):
            self.set_function(8, i, (bits >> i) & 1 == 1)
        self.set_function(8, 7, (bits >> 6) & 1 == 1)
        self.set_function(8, 8, (bits >> 7) & 1 == 1)
        self.set_function(7, 8, (bits >> 8) & 1 == 1)
        for i in range(9, 15):
            self.set_function(14 - i, 8, (bits >> i) & 1 == 1)
        for i in range(8):
            self.set_function(size - 1 - i, 8, (bits >> i) & 1 == 1)
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, (bits >> i) & 1 == 1)
        self.set_function(8, size - 8, True)

    def _draw_version(self) -> None:
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.ver << 12 | rem
        for i in range(18):
            bit = (bits >> i) & 1 == 1
            a = self.size - 11 + i % 3
            b = i // 3
            self.set_function(a, b, bit)
            self.set_function(b, a, bit)

    def draw_codewords(self, data: bytes) -> None:
        size = self.size
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = size - 1 - vert if upward else vert
                    if not self.is_function[y][x] and i < len(data) * 8:
                        self.modules[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        masker = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.is_function[y][x] and masker(x, y):
                    self.modules[y][x] ^= True

    def penalty(self) -> int:
        size = self.size
        modules = self.modules
        result = 0

        def line_penalty(line: list[bool]) -> int:
            score = 0
            i = 0
            while i < size:
                j = i
                while j < size and line[j] == line[i]:
                    j += 1
                if j - i >= 5:
                    score += 3 + (j - i - 5)
                i = j
            # 1:1:3:1:1 finder-like runs with 4 light modules on either side.
            for i in range(size - 6):
                if [line[i + k] for k in range(7)] == _FINDER_RUN:
                    left = i >= 4 and not any(line[i - 4:i])
                    right = i + 11 <= size and not any(line[i + 7:i + 11])
                    if left or right:
                        score += 40
            return score

        for y in range(size):
            result += line_penalty(modules[y])
        for x in range(size):
            result += line_penalty([modules[y][x] for y in range(size)])
        for y in range(size - 1):
            for x in range(size - 1):
                if modules[y][x] == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                    result += 3
        dark = sum(sum(row) for row in modules)
        percent = dark * 100 / (size * size)
        result += int(abs(percent - 50) // 5) * 10
        return result


_FINDER_RUN = [True, False, True, True, True, False, True]


_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def encode(text: str | bytes, ecl: int = ECL_M, min_version: int = 1, mask: int | None = None) -> QRCode:
    """Encode ``text`` as a byte-mode QR code, choosing the smallest version that fits."""
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    for ver in range(min_version, 41):
        if _byte_mode_bits(len(data), ver) <= _data_codewords(ver, ecl) * 8:
            break
    else:
        raise ValueError("data too long for a QR code")

    codewords = _add_ecc_and_interleave(_encode_data(data, ver, ecl), ver, ecl)
    canvas = _Canvas(ver, ecl)
    canvas.draw_function_patterns()
    canvas.draw_codewords(codewords)

    if mask is None:
        best, best_penalty = 0, None
        for m in range(8):
            canvas.apply_mask(m)
            canvas.draw_format_bits(m)
            p = canvas.penalty()
            if best_penalty is None or p < best_penalty:
                best, best_penalty = m, p
            canvas.apply_mask(m)  # masks are involutions; undo
        mask = best
    canvas.apply_mask(mask)
    canvas.draw_format_bits(mask)

    return QRCode(
        version=ver,
        ecl=ecl,
        mask=mask,
        size=canvas.size,
        modules=tuple(tuple(row) for row in canvas.modules),
    )
