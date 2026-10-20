# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the FileReadNode through ctypes, against an independent model written here: WAV files of every accepted format are generated with
struct (no audio library), and what the node answers at many times and span densities is compared bit for bit with the model's linear
interpolation (exact position between two frames, float32 arithmetic as in the node). Also the refused files, the messages, and when the file is
read (at creation and on "open" only)."""
import ctypes
import os
import random
import struct
import tempfile

import engine_dll as e
from engine_dll import Rig, float32 as f32, span_buffer

U8_SCALE = f32(0.00784313725490196078)        # dr_wav's own constant for 8-bit PCM: 0..255 -> -1..1


def to_float(kind, bits, raw):
    """What the node should hold for a raw sample of the file."""
    if kind == "float":
        return f32(raw)
    if bits == 8:
        return f32(f32(raw * U8_SCALE) - 1.0)
    return f32(raw / float(1 << (bits - 1)))


def sample_bytes(kind, bits, raw):
    if kind == "float":
        return struct.pack("<f" if bits == 32 else "<d", raw)
    if bits == 8:
        return struct.pack("<B", raw)
    if bits == 16:
        return struct.pack("<h", raw)
    if bits == 24:
        return struct.pack("<i", raw)[:3]
    return struct.pack("<i", raw)


def random_raw(rng, kind, bits):
    if kind == "float":
        return f32(rng.uniform(-1.5, 1.5))
    if bits == 8:
        return rng.randrange(256)
    return rng.randrange(-(1 << (bits - 1)), 1 << (bits - 1))


def write_wav(path, tag, bits, channels, rate, data, claimed_length=None, block_extra=0):
    block = channels * bits // 8
    claimed = len(data) if claimed_length is None else claimed_length
    header = (b"RIFF" + struct.pack("<I", 36 + claimed) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, tag, channels, rate, rate * block, block, bits)
              + b"data" + struct.pack("<I", claimed))
    with open(path, "wb") as handle:
        handle.write(header + data)


class Wav:
    """A generated file: frames[k][c] are the model's float32 values."""

    def __init__(self, directory, name, kind, bits, channels, rate, frame_count, seed):
        rng = random.Random(seed)
        raws = [[random_raw(rng, kind, bits) for _ in range(channels)] for _ in range(frame_count)]
        data = b"".join(sample_bytes(kind, bits, raw) for frame in raws for raw in frame)
        self.path = os.path.join(directory, name)
        self.rate, self.channels = rate, channels
        self.frames = [[to_float(kind, bits, raw) for raw in frame] for frame in raws]
        write_wav(self.path, 3 if kind == "float" else 1, bits, channels, rate, data)

    def value(self, channel, t):
        """The model of the node's answer at time t (ns) for 'left' (0) or 'right' (1)."""
        column = min(channel, self.channels - 1)
        count = len(self.frames)
        scaled = t * self.rate
        k, remainder = scaled // 10 ** 9, scaled % 10 ** 9
        if count == 0 or k < 0 or k > count - 1:
            return 0.0
        a = self.frames[k][column]
        if k == count - 1:
            return a if remainder == 0 else 0.0
        b = self.frames[k + 1][column]
        return f32(a + (remainder / 10 ** 9) * (b - a))


def span_times(t0, t1, n):
    q, r = divmod(t1 - t0, n)
    return [t0 + i * q + (i * r) // n for i in range(n)]


def file_rig(path):
    """file_read (1) -> boundary outlets 'l' (2) and 'r' (3)."""
    rig = Rig()
    rig.node(1, "file_read")
    rig.node(2, "boundary_outlet")
    rig.node(3, "boundary_outlet")
    rig.connect(1, "left", 2, "in")
    rig.connect(1, "right", 3, "in")
    assert e.graph_set_string(rig.graph, 2, b"name", b"l") == e.OK
    assert e.graph_set_string(rig.graph, 3, b"name", b"r") == e.OK
    if path is not None:
        assert e.graph_set_string(rig.graph, 1, b"path", path.encode("utf-8")) == e.OK
    rig.install()
    return rig


def message(rig):
    buffer, length = ctypes.create_string_buffer(1000), e.i32()
    assert e.engine_node_message(rig.engine, 1, buffer, 1000, ctypes.byref(length)) == e.OK
    return buffer.value.decode("utf-8")


def bits_of(value):
    return struct.pack("<f", value)


def check_points(rig, wav, rng, count):
    end = (len(wav.frames) + 3) * 10 ** 9 // wav.rate
    times = [rng.randint(-2 * 10 ** 9 // wav.rate, end) for _ in range(count)] + [0, -1, 1]
    if wav.frames:
        last = (len(wav.frames) - 1) * 10 ** 9 // wav.rate
        times += [last - 1, last, last + 1, last + 10 ** 9 // wav.rate]
    for t in times:
        for channel, name in ((0, b"l"), (1, b"r")):
            got, want = e.instance_read_at(rig.instance, name, t), wav.value(channel, t)
            assert bits_of(got) == bits_of(want), (name, t, got, want)


def test_py_every_accepted_format_gives_the_values_of_the_model_at_grid_and_off_grid_times_and_beyond_the_edges():
    with tempfile.TemporaryDirectory() as directory:
        rng = random.Random(1)
        for kind, bits in (("pcm", 8), ("pcm", 16), ("pcm", 24), ("pcm", 32), ("float", 32)):
            for channels, rate in ((2, 1000), (1, 44100)):
                wav = Wav(directory, f"f{kind}{bits}_{channels}.wav", kind, bits, channels, rate, 60, seed=bits * 10 + channels)
                rig = file_rig(wav.path)
                assert message(rig) == ""
                check_points(rig, wav, rng, 150)
                rig.close()


def test_py_mono_feeds_both_outlets_more_than_two_channels_use_the_first_two_and_tiny_files_work():
    with tempfile.TemporaryDirectory() as directory:
        rng = random.Random(2)
        mono = Wav(directory, "mono.wav", "pcm", 16, 1, 1000, 30, seed=3)
        rig = file_rig(mono.path)
        for t in (0, 5_500_000, 29_000_000):
            assert e.instance_read_at(rig.instance, b"l", t) == e.instance_read_at(rig.instance, b"r", t)
        check_points(rig, mono, rng, 60)
        rig.close()
        three = Wav(directory, "three.wav", "float", 32, 3, 1000, 30, seed=4)
        rig = file_rig(three.path)
        check_points(rig, three, rng, 100)
        assert e.instance_read_at(rig.instance, b"l", 3_000_000) != e.instance_read_at(rig.instance, b"r", 3_000_000)
        rig.close()
        one = Wav(directory, "one.wav", "float", 32, 2, 1000, 1, seed=5)                    # a single frame: only t = 0 is not silence
        rig = file_rig(one.path)
        assert e.instance_read_at(rig.instance, b"l", 0) == one.frames[0][0] != 0.0
        assert e.instance_read_at(rig.instance, b"l", 1) == 0.0 and e.instance_read_at(rig.instance, b"l", -1) == 0.0
        rig.close()
        none = Wav(directory, "none.wav", "float", 32, 2, 1000, 0, seed=6)                  # no frames at all: silence, and no message
        rig = file_rig(none.path)
        assert e.instance_read_at(rig.instance, b"l", 0) == 0.0 and message(rig) == ""
        rig.close()


def test_py_spans_of_any_density_and_direction_are_the_model_sampled_at_the_span_times():
    with tempfile.TemporaryDirectory() as directory:
        rng = random.Random(3)
        wav = Wav(directory, "s.wav", "pcm", 24, 2, 8000, 400, seed=7)                     # 50 ms of audio
        rig = file_rig(wav.path)
        for _ in range(60):
            t0, t1 = rng.randint(-20_000_000, 70_000_000), rng.randint(-20_000_000, 70_000_000)
            n = rng.choice([1, 2, 7, 50, 199, 400, 1000, 3000])
            if rng.random() < 0.1:
                t1 = t0
            for channel, name in ((0, b"l"), (1, b"r")):
                out = span_buffer(n)
                assert e.instance_read_span(rig.instance, name, t0, t1, n, out) == e.OK
                want = [wav.value(channel, t) for t in span_times(t0, t1, n)]
                assert [bits_of(v) for v in out] == [bits_of(v) for v in want], (name, t0, t1, n)
        rig.close()


def make_bad_files(directory):
    paths = {}
    good = Wav(directory, "good.wav", "float", 32, 1, 1000, 10, seed=8)
    data64 = b"".join(struct.pack("<d", 0.5) for _ in range(10))
    paths["float64"] = os.path.join(directory, "f64.wav")
    write_wav(paths["float64"], 3, 64, 1, 1000, data64)
    paths["alaw"] = os.path.join(directory, "alaw.wav")
    write_wav(paths["alaw"], 6, 8, 1, 1000, bytes(range(10)))
    paths["garbage"] = os.path.join(directory, "garbage.wav")
    with open(paths["garbage"], "wb") as handle:
        handle.write(b"this is not a wav file at all, only text" * 5)
    paths["empty"] = os.path.join(directory, "empty.wav")
    open(paths["empty"], "wb").close()
    return good, paths


def test_py_files_that_cannot_be_used_leave_the_node_silent_with_a_message_and_a_failed_open_keeps_the_old_file():
    with tempfile.TemporaryDirectory() as directory:
        good, bad = make_bad_files(directory)
        wanted = {"float64": "format not supported", "alaw": "format not supported", "garbage": "not a WAV file", "empty": "not a WAV file"}
        for name, text in wanted.items():
            rig = file_rig(bad[name])
            assert text in message(rig), (name, message(rig))
            assert e.instance_read_at(rig.instance, b"l", 1_000_000) == 0.0
            out = span_buffer(8)
            for i in range(8):
                out[i] = 5.0
            assert e.instance_read_span(rig.instance, b"r", 0, 8_000_000, 8, out) == e.OK and all(v == 0.0 for v in out)    # a span is silent too
            rig.close()
        for path, text in ((os.path.join(directory, "missing.wav"), "file not found"), (directory, "not a file"), ("relative/path.wav", "absolute"),
                           ("C:relative.wav", "absolute"), ("\\rooted.wav", "absolute"), ("/rooted.wav", "absolute")):     # (drive-relative and rooted are relative too)
            rig = file_rig(path)
            assert text in message(rig), (path, message(rig))
            rig.close()
        rig = file_rig(good.path)                                                           # a good file, then "open" on a bad path
        before = e.instance_read_at(rig.instance, b"l", 3_000_000)
        assert before == good.value(0, 3_000_000) != 0.0 and message(rig) == ""
        for name, text in wanted.items():
            assert e.graph_set_string(rig.graph, 1, b"path", bad[name].encode()) == e.OK
            rig.update()
            assert e.engine_action(rig.engine, 1, b"open") == e.OK
            assert text in message(rig)
            assert e.instance_read_at(rig.instance, b"l", 3_000_000) == before             # the old file is still there
        assert e.graph_set_string(rig.graph, 1, b"path", b"") == e.OK
        rig.update()
        assert e.engine_action(rig.engine, 1, b"open") == e.OK and "no file" in message(rig)
        assert e.instance_read_at(rig.instance, b"l", 3_000_000) == before
        newer = Wav(directory, "newer.wav", "float", 32, 1, 1000, 10, seed=12)                 # and a good open afterwards clears the message
        assert e.graph_set_string(rig.graph, 1, b"path", newer.path.encode()) == e.OK
        rig.update()
        assert e.engine_action(rig.engine, 1, b"open") == e.OK and message(rig) == ""
        assert e.instance_read_at(rig.instance, b"l", 3_000_000) == newer.value(0, 3_000_000) != before
        rig.close()


def test_py_the_file_is_read_at_creation_and_on_open_only_and_a_good_open_replaces_it_and_clears_the_message():
    with tempfile.TemporaryDirectory() as directory:
        first = Wav(directory, "first.wav", "pcm", 16, 2, 1000, 40, seed=9)
        second = Wav(directory, "second.wav", "pcm", 24, 1, 2000, 90, seed=10)
        rig = file_rig(first.path)
        t = 7_300_000
        assert e.instance_read_at(rig.instance, b"l", t) == first.value(0, t)
        assert e.graph_set_string(rig.graph, 1, b"path", second.path.encode()) == e.OK
        rig.update()                                                                        # a new description with another path: not read
        assert e.instance_read_at(rig.instance, b"l", t) == first.value(0, t)
        assert e.engine_action(rig.engine, 1, b"open") == e.OK                              # until "open"
        assert message(rig) == ""
        for tt in (t, 11_100_000, 44_000_000):
            assert bits_of(e.instance_read_at(rig.instance, b"l", tt)) == bits_of(second.value(0, tt))
        with open(first.path, "rb") as source, open(second.path, "wb") as target:             # the file on disk changes under the node...
            target.write(source.read())
        assert e.engine_action(rig.engine, 1, b"nothing") == e.OK                           # ...and another action than "open" does not read it
        assert bits_of(e.instance_read_at(rig.instance, b"l", t)) == bits_of(second.value(0, t))
        os.remove(second.path)                                                              # a file that is gone: another install does not notice
        rig.update()
        assert bits_of(e.instance_read_at(rig.instance, b"l", t)) == bits_of(second.value(0, t)) and message(rig) == ""
        assert e.engine_action(rig.engine, 1, b"open") == e.OK and "file not found" in message(rig)
        assert bits_of(e.instance_read_at(rig.instance, b"l", t)) == bits_of(second.value(0, t))     # and the node plays on
        rig.close()


def test_py_a_path_with_spaces_and_non_ascii_text_works_and_a_file_shorter_than_its_header_says_is_used_as_far_as_it_goes():
    with tempfile.TemporaryDirectory() as directory:
        folder = os.path.join(directory, "café ♪ folder")
        os.makedirs(folder)
        wav = Wav(folder, "söng one.wav", "pcm", 16, 1, 1000, 20, seed=11)
        rig = file_rig(wav.path)
        assert message(rig) == "" and e.instance_read_at(rig.instance, b"l", 4_500_000) == wav.value(0, 4_500_000) != 0.0
        rig.close()
        path = os.path.join(directory, "short.wav")
        values = [1000, -2000, 3000, -4000, 5000]
        data = b"".join(struct.pack("<h", v) for v in values)
        write_wav(path, 1, 16, 1, 1000, data, claimed_length=len(data) + 400)               # the header promises 200 more frames
        rig = file_rig(path)
        assert e.instance_read_at(rig.instance, b"l", 2_000_000) == f32(3000 / 32768.0)
        assert e.instance_read_at(rig.instance, b"l", 4_000_000) == f32(5000 / 32768.0)
        assert e.instance_read_at(rig.instance, b"l", 4_000_001) == 0.0
        rig.close()
        huge = os.path.join(directory, "huge.wav")                                          # a header that claims 4 GB of data in a file of 40 bytes
        write_wav(huge, 1, 16, 2, 1000, b"".join(struct.pack("<h", v) for v in range(20)), claimed_length=0xFFFFFF00)
        rig = file_rig(huge)
        assert message(rig) == "" and e.instance_read_at(rig.instance, b"l", 9_000_000) == f32(18 / 32768.0)     # frame 9, left: no giant allocation
        assert e.instance_read_at(rig.instance, b"l", 9_000_001) == 0.0
        rig.close()
