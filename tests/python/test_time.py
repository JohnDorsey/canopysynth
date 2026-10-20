# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the time helpers (docs/canopy_design.md section 4 and the sample placement of section 5), checked against references that use
Python's arbitrary-precision integers, which cannot overflow: the C code must agree with them everywhere inside int64, and report an error
(never a wrong value) where the true result does not fit."""
import random
from fractions import Fraction

import canopysynth
import dll
from dll import (ERR_INDEX, ERR_N, ERR_OVERFLOW, ERR_RATE, INT64_MAX, INT64_MIN, MAX_N, OK,
                 c_ns_to_frame, c_ns_to_frame_fraction, c_sample_time)

MAX_RATE = INT64_MAX // 10 ** 9                      # 9223372036: the largest rate whose intermediate products fit
RATES = [1, 2, 3, 8000, 22050, 44100, 48000, 96000, 384000, 10 ** 6, 10 ** 9, MAX_RATE]
EDGE_TIMES = [0, 1, -1, 499_999_999, 500_000_000, 500_000_001, -499_999_999, -500_000_000, -500_000_001, 999_999_999, 1_000_000_000,
              1_000_000_001, -999_999_999, -1_000_000_000, -1_000_000_001, 10 ** 12, -10 ** 12,
              INT64_MAX, INT64_MAX - 1, INT64_MIN, INT64_MIN + 1, 2 ** 62, -2 ** 62, 10 ** 18, -10 ** 18]


def ref_frame(ns, rate):
    return (ns * rate + 500_000_000) // 10 ** 9


def fits(value):
    return INT64_MIN <= value <= INT64_MAX


def random_times(rng, count):
    out = list(EDGE_TIMES)
    for _ in range(count):
        magnitude = rng.choice([3, 6, 9, 12, 15, 18, 19])
        out.append(rng.randint(-(10 ** magnitude), 10 ** magnitude))
    return [t for t in out if fits(t)]


def test_py_c_ns_to_frame_agrees_with_big_integer_arithmetic_everywhere():
    rng = random.Random(20261002)
    checked = overflowed = 0
    for ns in random_times(rng, 3000):
        for rate in RATES + [rng.randint(1, MAX_RATE) for _ in range(3)]:
            status, frame = c_ns_to_frame(ns, rate)
            want = ref_frame(ns, rate)
            if fits(want):
                assert (status, frame) == (OK, want), (ns, rate, status, frame, want)
                checked += 1
            else:
                assert status == ERR_OVERFLOW, (ns, rate, status, frame, want)
                overflowed += 1
    assert checked > 20000 and overflowed > 100


def test_py_c_ns_to_frame_refuses_rates_outside_one_to_the_largest_safe_rate():
    for rate in (0, -1, -48000, MAX_RATE + 1, INT64_MAX, INT64_MIN):
        assert c_ns_to_frame(12345, rate)[0] == ERR_RATE, rate
        assert c_ns_to_frame_fraction(12345, rate)[0] == ERR_RATE, rate
    assert c_ns_to_frame(12345, 1)[0] == OK and c_ns_to_frame(12345, MAX_RATE)[0] == OK


def test_py_c_ns_to_frame_fraction_agrees_with_exact_fractions():
    rng = random.Random(7)
    for ns in random_times(rng, 1500):
        for rate in RATES:
            exact = Fraction(ns * rate, 10 ** 9)
            frame_ref = exact.numerator // exact.denominator          # floor
            frac_ref = float(exact - frame_ref)
            status, frame, fraction = c_ns_to_frame_fraction(ns, rate)
            if fits(frame_ref):
                assert (status, frame, fraction) == (OK, frame_ref, frac_ref), (ns, rate, frame, fraction, frame_ref, frac_ref)
                assert 0.0 <= fraction < 1.0
            else:
                assert status == ERR_OVERFLOW, (ns, rate)


def test_py_consecutive_blocks_tile_exactly_with_frame_differences():
    rng = random.Random(99)
    for _ in range(3000):
        rate = rng.choice(RATES[:10])
        a = rng.randint(-10 ** 13, 10 ** 13)
        b = a + rng.randint(0, 10 ** 8)
        c = b + rng.randint(0, 10 ** 8)
        n_ab = c_ns_to_frame(b, rate)[1] - c_ns_to_frame(a, rate)[1]
        n_bc = c_ns_to_frame(c, rate)[1] - c_ns_to_frame(b, rate)[1]
        n_ac = c_ns_to_frame(c, rate)[1] - c_ns_to_frame(a, rate)[1]
        assert n_ab >= 0 and n_bc >= 0 and n_ab + n_bc == n_ac
    # the case that shows why: rounding each block's own duration over-counts (1 + 1 frames, but the whole is 1)
    rounded = round(15000 * 48000 / 1e9) + round(15000 * 48000 / 1e9)
    assert rounded == 2 and c_ns_to_frame(30000, 48000)[1] - c_ns_to_frame(0, 48000)[1] == 1


def ref_sample_time(t0, t1, n, i):
    return t0 + (i * (t1 - t0)) // n


def test_py_c_sample_time_agrees_with_big_integer_arithmetic_for_every_sample_of_small_spans():
    rng = random.Random(5)
    spans = [(0, 100), (100, 0), (0, 10), (-5, 0), (0, -5), (7, 7), (-10 ** 9, 10 ** 9), (INT64_MIN // 2, INT64_MAX // 2),
             (0, INT64_MAX), (INT64_MAX, 0), (INT64_MIN + 5, 5), (-1, INT64_MAX - 1), (INT64_MAX - 1, -1)]
    spans += [(rng.randint(-10 ** 15, 10 ** 15), rng.randint(-10 ** 15, 10 ** 15)) for _ in range(40)]
    for t0, t1 in spans:
        for n in (1, 2, 3, 4, 5, 7, 16, 100, 255):
            for i in range(n):
                status, got = c_sample_time(t0, t1, n, i)
                if fits(t1 - t0):
                    want = ref_sample_time(t0, t1, n, i)
                    assert (status, got) == (OK, want), (t0, t1, n, i, status, got, want)
                else:
                    assert status == ERR_OVERFLOW, (t0, t1, n, i, status)


def test_py_c_sample_time_agrees_for_random_samples_of_the_largest_spans():
    rng = random.Random(11)
    for _ in range(20000):
        t0 = rng.randint(INT64_MIN, INT64_MAX)
        t1 = rng.randint(INT64_MIN, INT64_MAX)
        n = rng.choice([1, 2, 3, 1000, 4096, MAX_N - 1, MAX_N])
        i = rng.randrange(n)
        status, got = c_sample_time(t0, t1, n, i)
        if fits(t1 - t0):
            assert (status, got) == (OK, ref_sample_time(t0, t1, n, i)), (t0, t1, n, i, status, got)
            assert min(t0, t1) <= got <= max(t0, t1)
        else:
            assert status == ERR_OVERFLOW, (t0, t1, n, i, status)


def test_py_c_sample_time_error_precedence_and_limits():
    assert c_sample_time(0, 10, 0, 0)[0] == ERR_N
    assert c_sample_time(0, 10, -5, 0)[0] == ERR_N
    assert c_sample_time(0, 10, MAX_N + 1, 0)[0] == ERR_N
    assert c_sample_time(0, 10, MAX_N, MAX_N - 1)[0] == OK
    assert c_sample_time(0, 10, 4, 4)[0] == ERR_INDEX
    assert c_sample_time(0, 10, 4, -1)[0] == ERR_INDEX
    assert c_sample_time(INT64_MIN, INT64_MAX, 4, 0)[0] == ERR_OVERFLOW
    assert c_sample_time(INT64_MAX, INT64_MIN, 4, 0)[0] == ERR_OVERFLOW
    assert c_sample_time(0, 10, 0, 99)[0] == ERR_N                 # a bad n is reported before a bad index


def test_py_the_python_public_helper_functions_agree_with_the_c_ones_and_raise_the_same_errors():
    rng = random.Random(3)
    for ns in random_times(rng, 400):
        for rate in RATES:
            status, frame = c_ns_to_frame(ns, rate)
            if status == OK:
                assert canopysynth.ns_to_frame(ns, rate) == frame
            else:
                try:
                    canopysynth.ns_to_frame(ns, rate)
                except OverflowError:
                    assert status == ERR_OVERFLOW
                else:
                    raise AssertionError((ns, rate))
            status, frame, fraction = c_ns_to_frame_fraction(ns, rate)
            if status == OK:
                assert canopysynth.ns_to_frame_fraction(ns, rate) == (frame, fraction)
            else:
                try:
                    canopysynth.ns_to_frame_fraction(ns, rate)
                except OverflowError:
                    assert status == ERR_OVERFLOW
                else:
                    raise AssertionError((ns, rate))
    for bad_rate in (0, -1, MAX_RATE + 1):
        for function in (canopysynth.ns_to_frame, canopysynth.ns_to_frame_fraction):
            try:
                function(1, bad_rate)
            except ValueError:
                pass
            else:
                raise AssertionError((function, bad_rate))
    for bad_time in (INT64_MAX + 1, INT64_MIN - 1):
        try:
            canopysynth.ns_to_frame(bad_time, 48000)
        except ValueError:
            pass
        else:
            raise AssertionError(bad_time)


def test_py_the_public_helper_functions_are_documented_as_such():
    for function in (canopysynth.ns_to_frame, canopysynth.ns_to_frame_fraction):
        assert "public helper function" in function.__doc__.lower()
    assert "public helper function" in canopysynth.helpers.__doc__.lower()
