"""Tests: the playback time as text (design section 9: hh:mm:ss.mmm), no Tk in them. Expected texts are written out by hand; the round trip is checked
against an independent computation with divmod on random times."""
import random

from canopysynth.editor.timetext import format_time, parse_time

MS = 1_000_000
S = 1_000_000_000


def raises(text):
    try:
        parse_time(text)
    except ValueError as error:
        return str(error)
    raise AssertionError(f"{text!r} must not parse")


def test_py_a_time_is_shown_as_hours_minutes_seconds_and_milliseconds_cut_not_rounded():
    assert format_time(0) == "00:00:00.000"
    assert format_time(1 * MS) == "00:00:00.001" and format_time(999 * MS + 999_999) == "00:00:00.999"        # cut: never later than it is
    assert format_time(S) == "00:00:01.000" and format_time(61 * S + 500 * MS) == "00:01:01.500"
    assert format_time(3600 * S) == "01:00:00.000" and format_time(3 * 3600 * S + 25 * 60 * S + 7 * S + 89 * MS) == "03:25:07.089"
    assert format_time(100 * 3600 * S) == "100:00:00.000"                                                   # more than two digits of hours when needed
    assert format_time(-1) == "-00:00:00.000"                                                               # (less than a millisecond below zero: still negative)
    assert format_time(-(2 * S + 5 * MS)) == "-00:00:02.005" and format_time(-(3600 * S)) == "-01:00:00.000"


def test_py_typed_times_in_every_accepted_shape_are_read_to_the_nanosecond():
    assert parse_time("00:00:00.000") == 0 and parse_time("0") == 0
    assert parse_time("01:02:03.456") == (3600 + 2 * 60 + 3) * S + 456 * MS
    assert parse_time("2:03.5") == 123 * S + 500 * MS                                                       # minutes and seconds
    assert parse_time("90") == 90 * S and parse_time("1.25") == S + 250 * MS                                # seconds alone, any number of them
    assert parse_time("0.123456789") == 123_456_789 and parse_time("0.1") == 100 * MS and parse_time("5.000000001") == 5 * S + 1
    assert parse_time("  -00:00:01.500  ") == -(S + 500 * MS) and parse_time("+3") == 3 * S                # a sign, and spaces round it
    assert parse_time("100:00:00") == 100 * 3600 * S and parse_time("0:0:0") == 0
    assert parse_time("1:59:59.999") == 7199 * S + 999 * MS


def test_py_a_time_that_is_not_a_time_is_refused_with_a_sentence_that_says_what_to_write():
    for text in ("", "abc", "1:2:3:4", "1.2.3", "1:x", ":30", "1::30", "1.", "--1", "1.1234567890", "٣", "1e3", "1,5", "00:00:00.0000000001"):
        assert "hh:mm:ss.mmm" in raises(text), text
    assert "below 60" in raises("1:60") and "below 60" in raises("1:00:60") and "below 60" in raises("1:60:00")
    assert parse_time("60") == 60 * S and parse_time("0:59:59") == 3599 * S                                  # (seconds alone may be any number)


def test_py_formatting_then_parsing_gives_back_the_time_to_the_millisecond_for_random_times():
    rng = random.Random(12)
    for _ in range(500):
        total_ms = rng.randrange(0, 400 * 3600 * 1000)
        text = format_time(total_ms * MS + rng.randrange(0, MS))
        hours, rest = divmod(total_ms, 3600 * 1000)
        minutes, rest = divmod(rest, 60 * 1000)
        seconds, ms = divmod(rest, 1000)
        assert text == f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"
        assert parse_time(text) == total_ms * MS
        assert parse_time("-" + text) == -total_ms * MS
        assert format_time(parse_time("-" + text)) == ("-" + text if total_ms else text)                      # (minus zero is zero)
