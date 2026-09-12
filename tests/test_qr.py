import pytest

from stamp import qr


def _finder_at(code, x0, y0):
    for dy in range(7):
        for dx in range(7):
            ring = max(abs(dx - 3), abs(dy - 3))
            expected = ring != 2
            if code.dark(x0 + dx, y0 + dy) != expected:
                return False
    return True


def test_stamp_payload_fits_version_5():
    code = qr.encode("stamp:sha256:" + "0f" * 32)
    assert code.version == 5
    assert code.size == 37
    assert code.ecl == qr.ECL_M


def test_finder_patterns_and_timing():
    code = qr.encode("stamp:sha256:" + "a1" * 32)
    n = code.size
    assert _finder_at(code, 0, 0)
    assert _finder_at(code, n - 7, 0)
    assert _finder_at(code, 0, n - 7)
    for i in range(8, n - 8):
        assert code.dark(i, 6) == (i % 2 == 0)
        assert code.dark(6, i) == (i % 2 == 0)
    assert code.dark(8, n - 8)  # the always-dark module


def test_deterministic_and_sensitive():
    a = qr.encode("stamp:sha256:" + "ab" * 32)
    b = qr.encode("stamp:sha256:" + "ab" * 32)
    c = qr.encode("stamp:sha256:" + "ab" * 31 + "ac")
    assert a.modules == b.modules
    assert a.modules != c.modules


def test_known_data_capacities():
    # Total data codewords from the specification tables.
    assert qr._data_codewords(1, qr.ECL_L) == 19
    assert qr._data_codewords(1, qr.ECL_H) == 9
    assert qr._data_codewords(5, qr.ECL_M) == 86
    assert qr._data_codewords(10, qr.ECL_Q) == 154
    assert qr._data_codewords(40, qr.ECL_L) == 2956
    assert qr._data_codewords(40, qr.ECL_H) == 1276


def test_version_selection_and_limits():
    assert qr.encode("").version == 1
    assert qr.encode("a" * 17, ecl=qr.ECL_L).version == 1
    assert qr.encode("a" * 18, ecl=qr.ECL_L).version == 2
    assert qr.encode("a" * 2953, ecl=qr.ECL_L).version == 40
    with pytest.raises(ValueError):
        qr.encode("a" * 2954, ecl=qr.ECL_L)


def test_alignment_positions():
    assert qr._alignment_positions(1) == []
    assert qr._alignment_positions(2) == [6, 18]
    assert qr._alignment_positions(7) == [6, 22, 38]
    assert qr._alignment_positions(32) == [6, 34, 60, 86, 112, 138]
    assert qr._alignment_positions(40) == [6, 30, 58, 86, 114, 142, 170]


def test_format_bits_are_consistent_with_chosen_mask():
    code = qr.encode("hello, stamp", ecl=qr.ECL_Q, mask=3)
    bits = 0
    for i in range(6):
        bits |= code.dark(8, i) << i
    bits |= code.dark(8, 7) << 6
    bits |= code.dark(8, 8) << 7
    bits |= code.dark(7, 8) << 8
    for i in range(9, 15):
        bits |= code.dark(14 - i, 8) << i
    data = (bits ^ 0x5412) >> 10
    assert data & 7 == 3
    assert data >> 3 == 3  # ECL_Q is encoded as 0b11
