# SPDX-License-Identifier: GPL-3.0-or-later
"""Playback times as text, for the time field of the realtime preview node (design section 9: "shown as hh:mm:ss.mmm"). No Tk in here."""

NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000


def format_time(time_ns):
    """A time in nanoseconds as hh:mm:ss.mmm (the milliseconds cut, not rounded, so that a time never shows later than it is; hours have at least two
    digits and as many more as needed; a negative time has a minus sign in front)."""
    sign = "-" if time_ns < 0 else ""
    total_ms = abs(time_ns) // NS_PER_MS
    seconds, milliseconds = divmod(total_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def parse_time(text):
    """The time in nanoseconds that `text` names: hh:mm:ss.mmm, or mm:ss.mmm, or ss.mmm, or ss; the fraction of a second may have 1 to 9 digits and may be
    left out; a minus sign may come first; minutes and seconds must be below 60 when a larger unit is given. ValueError, with a sentence that says
    what is wrong, for anything else."""
    original = text
    text = text.strip()
    sign = -1 if text.startswith("-") else 1
    if text.startswith(("-", "+")):
        text = text[1:].strip()
    whole, dot, fraction = text.partition(".")
    parts = whole.split(":")
    if len(parts) > 3 or not all(part.isascii() and part.isdigit() for part in parts) or (dot and not (fraction.isascii() and fraction.isdigit())) \
            or len(fraction) > 9:
        raise ValueError(f"a time is written hh:mm:ss.mmm (the hours and minutes may be left out), not {original.strip()!r}")
    numbers = [int(part) for part in parts]
    if any(number >= 60 for number in numbers[1:]):
        raise ValueError(f"minutes and seconds must be below 60 when a larger unit is given: {original.strip()!r}")
    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number
    return sign * (seconds * NS_PER_SECOND + (int(fraction.ljust(9, "0")) if fraction else 0))
