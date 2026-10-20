# SPDX-License-Identifier: GPL-3.0-or-later
"""The public helper functions: nanoseconds to sample frames.

Times inside canopysynth are signed 64-bit integers counting nanoseconds since t = 0, and there is no global sample rate. These two
functions are how a host (or a node author, through the C versions in canopy.h) turns a time into a position among the samples of some
rate. They use exact integer arithmetic, the same as the C ones, and raise the same errors."""
_NS = 10 ** 9
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1
MAX_RATE = INT64_MAX // _NS          # 9223372036 Hz: the largest rate the C functions accept


def _check(ns, rate):
    if not (isinstance(ns, int) and INT64_MIN <= ns <= INT64_MAX):
        raise ValueError(f"a time must be a signed 64-bit integer of nanoseconds, not {ns!r}")
    if not (isinstance(rate, int) and 1 <= rate <= MAX_RATE):
        raise ValueError(f"a rate must be a whole number of Hz from 1 to {MAX_RATE}, not {rate!r}")


def _fit(value):
    if not INT64_MIN <= value <= INT64_MAX:
        raise OverflowError("the frame number does not fit in a signed 64-bit integer")
    return value


def ns_to_frame(ns, rate):
    """Public helper function: the sample frame nearest to time `ns` (nanoseconds) at `rate` Hz.

    It is floor((ns * rate + 500_000_000) / 1_000_000_000): round half up, with floor division so negative times behave consistently.

    How it is useful: a host that wants a block of audio at its own rate for the time span [t0, t1) asks for
    `n = ns_to_frame(t1, rate) - ns_to_frame(t0, rate)` samples, NOT round((t1 - t0) * rate / 1e9). Consecutive blocks [a, b) and [b, c)
    then tile exactly, with no gap and no overlap.

    Raises ValueError for a time outside int64 or a rate outside 1..9223372036, and OverflowError when the frame number itself does not
    fit in an int64."""
    _check(ns, rate)
    return _fit((ns * rate + _NS // 2) // _NS)


def ns_to_frame_fraction(ns, rate):
    """Public helper function: where time `ns` falls among the samples at `rate` Hz, as (frame, fraction).

    `frame` is the whole sample frame at or before the time (floor, not rounded) and `fraction` (0 <= fraction < 1, a float) is how far it
    is towards the next frame.

    How it is useful: a node (or a host reading its own audio) that interpolates between two samples uses
    `(1 - fraction) * data[frame] + fraction * data[frame + 1]`.

    Raises the same errors as ns_to_frame."""
    _check(ns, rate)
    scaled = ns * rate
    frame = _fit(scaled // _NS)
    return frame, (scaled % _NS) / _NS
