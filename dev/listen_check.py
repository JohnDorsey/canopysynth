# SPDX-License-Identifier: GPL-3.0-or-later
"""The listening check of plan step 7: plays test sounds through the realtime preview node on a REAL audio device, so that a person can hear
that it does what the design says. (The automated tests use miniaudio's null backend, which plays the audio nowhere; nobody but you can hear this.)

    python dev/listen_check.py                      the whole check on the system's default device
    python dev/listen_check.py --list               only lists the devices the preview can use
    python dev/listen_check.py --device "NAME"      uses the device with that exact name (see --list); a name that does not exist falls back
                                                    to the default device, as the design says, and the check shows the note
    python dev/listen_check.py --wav C:\\path\\song.wav    after the tests, an interactive player for your own file (left and right of the file
                                                    go to the preview's left and right): p play, s pause, t HH:MM:SS.mmm go to a time, q quit
    python dev/listen_check.py --loud               adds one more test: two loud signals whose sum goes beyond full scale and must be clipped
    python dev/listen_check.py --auto --backend null    runs the whole script without sound and without questions (to test the script itself)

KEEP YOUR VOLUME LOW at the start: the tones are moderate (a quarter of full scale), but speakers and headphones differ. Every test says what you
should hear and asks you to answer y (heard it), n (did not) or q (stop). The answers are written at the end; tell the assistant the result.
"""
import argparse
import math
import os
import struct
import sys
import tempfile
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "python"))

import ctypes  # noqa: E402

import engine_dll as e  # noqa: E402  (ctypes bindings of the DLL: the Python bridge of plan step 9 does not exist yet)

PREVIEW = 50
RATE = 48000
# A file node loads its file when it is created and when "open" is pressed, never when a later graph names another path: so each file has an ID of
# its own, and a graph that uses a file always uses it under that ID.
FILE_IDS = {"a440": 1, "e660": 2, "a880": 3, "melody": 4, "a440_loud": 5, "yours": 6}


# ---- test sounds -------------------------------------------------------------------------------------------------------------------------

def write_wav(path, samples, rate=RATE):
    """A mono 16-bit PCM file from floats in -1..1."""
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, round(s * 32767)))) for s in samples))


def tone(freq, seconds, amplitude=0.25, fade=0.01):
    """A sine with a short fade at both ends (so that starting and stopping does not click)."""
    n = int(seconds * RATE)
    fade_n = int(fade * RATE)
    out = []
    for i in range(n):
        gain = min(1.0, i / fade_n, (n - 1 - i) / fade_n) if fade_n else 1.0
        out.append(amplitude * gain * math.sin(2 * math.pi * freq * i / RATE))
    return out


def melody():
    """Six notes of one second each, going up: C D E F G A. Where a pause or a typed time lands is audible as the note you hear."""
    out = []
    for freq in (261.63, 293.66, 329.63, 349.23, 392.00, 440.00):
        out += tone(freq, 1.0, 0.3, 0.005)
    return out


# ---- time text (hh:mm:ss.mmm), as the editor of plan step 12 will show it -----------------------------------------------------------------

def format_time(ns):
    sign = "-" if ns < 0 else ""
    ms = abs(ns) // 1_000_000
    return f"{sign}{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def parse_time(text):
    """'HH:MM:SS.mmm' (or 'MM:SS.mmm', 'SS.mmm', a leading '-') to nanoseconds; ValueError if it is not a time."""
    text = text.strip()
    sign = -1 if text.startswith("-") else 1
    parts = text.lstrip("-").split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(text)
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return sign * round(seconds * 1000) * 1_000_000


# ---- talking to the engine ---------------------------------------------------------------------------------------------------------------

def read_text(function, *args):
    length = e.i32()
    assert function(*args, None, 0, ctypes.byref(length)) == e.OK
    buffer = ctypes.create_string_buffer(length.value + 1)
    assert function(*args, buffer, length.value + 1, ctypes.byref(length)) == e.OK
    return buffer.value.decode("utf-8")


class Check:
    def __init__(self, backend, device, auto):
        self.auto = auto
        self.device = device
        self.registry = e.registry_new()
        self.engine = e.engine_new(self.registry)
        assert e.engine_set_audio_backend(self.engine, e.AUDIO_NULL if backend == "null" else e.AUDIO_SYSTEM) == e.OK
        self.graph = None
        self.results = []
        self.dir = tempfile.mkdtemp(prefix="canopy_listen_")
        self.files = {}

    def wav(self, name, samples):
        path = os.path.join(self.dir, name + ".wav")
        write_wav(path, samples)
        self.files[name] = path
        return path

    # -- graphs: a file_read node for each file used (under its own ID) and the preview (50); routes = [(file, outlet, preview inlet)] --
    def install(self, routes):
        graph = e.graph_new()
        for name in sorted({route[0] for route in routes}):
            assert e.graph_add_node(graph, FILE_IDS[name], b"file_read") == e.OK
            assert e.graph_set_string(graph, FILE_IDS[name], b"path", self.files[name].encode("utf-8")) == e.OK
        assert e.graph_add_node(graph, PREVIEW, b"realtime_preview") == e.OK
        if self.device:
            assert e.graph_set_string(graph, PREVIEW, b"device", self.device.encode("utf-8")) == e.OK
        for name, outlet, inlet in routes:
            assert e.graph_connect(graph, FILE_IDS[name], outlet.encode(), PREVIEW, inlet.encode()) == e.OK
        status = e.engine_set_graph(self.engine, graph)
        assert status == e.OK, e.engine_last_error(self.engine)
        e.graph_free(graph)
        e.engine_collect(self.engine)

    def action(self, name):
        assert e.engine_action(self.engine, PREVIEW, name.encode()) == e.OK

    def state(self):
        playing, t = e.i32(), e.i64()
        assert e.preview_state(self.engine, PREVIEW, ctypes.byref(playing), ctypes.byref(t)) == e.OK
        return playing.value, t.value

    def message(self):
        return read_text(e.engine_node_message, self.engine, PREVIEW)

    def seek(self, ns):
        assert e.preview_set_time(self.engine, PREVIEW, ns) == e.OK

    def play_for(self, seconds, label=""):
        """Plays for `seconds` of wall time, printing the time every half second."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
            if not self.auto:
                print(f"    {label} time {format_time(self.state()[1])}", flush=True)

    def ask(self, name, expect):
        print(f"\n=== {name}\n    You should hear: {expect}", flush=True)

    def verdict(self, name):
        if self.auto:
            self.results.append((name, "auto"))
            return True
        while True:
            answer = input("    Heard that? [y/n/q] ").strip().lower()
            if answer in ("y", "n", "q"):
                break
        self.results.append((name, answer))
        return answer != "q"

    def close(self):
        for name in list(self.files.values()):
            try:
                os.remove(name)
            except OSError:
                pass
        try:
            os.rmdir(self.dir)
        except OSError:
            pass
        assert e.engine_free(self.engine) == e.OK                    # also stops the device of a preview that is still playing
        e.registry_free(self.registry)


# ---- the tests ---------------------------------------------------------------------------------------------------------------------------

def run(check, loud):
    check.wav("a440", tone(440, 3.0))
    check.wav("e660", tone(660, 3.0))
    check.wav("a880", tone(880, 3.0))
    check.wav("melody", melody())
    check.wav("a440_loud", tone(440, 3.0, 0.9))

    def section(name, expect, routes, seconds=2.5):
        check.ask(name, expect)
        check.install(routes)
        check.seek(0)
        check.action("play")
        playing, _ = check.state()
        if not playing:
            print(f"    The preview did not start: {check.message()}", flush=True)
        else:
            note = check.message()
            if note:
                print(f"    (the node says: {note})", flush=True)
        check.play_for(seconds, "playing")
        check.action("pause")
        return check.verdict(name)

    if not section("1. left only", "a steady low tone (440 Hz, the A above middle C) from the LEFT speaker or ear only; nothing at all on the right.",
                   [("a440", "left", "left")]):
        return
    if not section("2. right only", "a higher tone (660 Hz) from the RIGHT side only; nothing on the left.", [("e660", "left", "right")]):
        return
    if not section("3. center", "an even higher tone (880 Hz) in BOTH speakers equally, so that it seems to come from the middle.",
                   [("a880", "left", "center")]):
        return
    if not section("4. left + center together", "two tones: the low one (440 Hz) only on the left, the high one (880 Hz) in both: so the left side has "
                   "both tones, the right side only the high one.", [("a440", "left", "left"), ("a880", "left", "center")]):
        return

    # pause, resume and a typed time, on the melody (six notes, one per second, going up)
    check.ask("5. pause, go on, and a typed time",
              "a rising scale, one note per second. It plays notes 1 and 2, goes SILENT for one second (paused), goes on with note 3 (not from the\n"
              "    start), plays notes 3 and 4, and then jumps to 00:00:04.000: you hear note 5 and then note 6 (the highest), then it stops.")
    check.install([("melody", "left", "left"), ("melody", "left", "right")])
    check.seek(0)
    check.action("play")
    check.play_for(2.0, "playing")
    check.action("pause")
    print("    ...paused (silence for one second)", flush=True)
    check.play_for(1.0, "paused ")
    check.action("play")
    check.play_for(2.0, "playing")
    check.seek(parse_time("00:00:04.000"))
    print("    ...typed time 00:00:04.000", flush=True)
    check.play_for(2.2, "playing")
    check.action("pause")
    if not check.verdict("5. pause, go on, and a typed time"):
        return

    # an edit while playing: the same preview, the graph around it replaced by another one; the sound changes pitch, the position does not jump
    check.ask("6. an edit while playing",
              "a tone that plays for a while, and then, without a gap or a jump in time, changes to a higher tone (the graph is replaced while the\n"
              "    preview keeps playing: this is compile-and-swap with a real device).")
    check.install([("a440", "left", "left"), ("a440", "left", "right")])
    check.seek(0)
    check.action("play")
    check.play_for(1.5, "low tone ")
    before = check.state()[1]
    check.install([("e660", "left", "left"), ("e660", "left", "right")])
    after = check.state()[1]
    print(f"    ...graph replaced (time before {format_time(before)}, just after {format_time(after)})", flush=True)
    check.play_for(1.5, "high tone")
    check.action("pause")
    if not check.verdict("6. an edit while playing"):
        return

    # a device that does not exist: falls back to the default, and the node says so
    check.ask("7. a device that does not exist",
              "the same tone as test 1 on the default device although the setting names a device that is not there; the node's note below must\n"
              "    say that it was not found and that the system default is used.")
    saved = check.device
    check.device = "Surely not a device of this machine"
    check.install([("a440", "left", "left"), ("a440", "left", "right")])
    check.seek(0)
    check.action("device")                                               # switch to the device the setting now names (falls back to the default)
    check.action("play")
    print(f"    the node says: {check.message()!r}", flush=True)
    check.play_for(2.0, "playing")
    check.action("pause")
    check.device = saved
    check.install([("a440", "left", "left"), ("a440", "left", "right")])
    check.action("device")                                               # and back to the chosen device
    if not check.verdict("7. a device that does not exist"):
        return

    if loud:
        check.ask("8. LOUD: a sum beyond full scale is clipped",
                  "(LOWER YOUR VOLUME NOW.) A loud, harsh, buzzy version of the 440 Hz tone: the tone (at 0.9 of full scale) is on both the left\n"
                  "    inlet and the center inlet, so the sum is 1.8 and must be cut off at full scale (distortion, but no crackling wrap-around).")
        if not check.auto:
            input("    Volume low? Press Enter to play. ")
        check.install([("a440_loud", "left", "left"), ("a440_loud", "left", "center")])
        check.seek(0)
        check.action("play")
        check.play_for(1.5, "playing")
        check.action("pause")
        check.verdict("8. LOUD: a sum beyond full scale is clipped")


def player(check, path):
    """An interactive player for a WAV file of your own: its left goes to the preview's left, its right to the preview's right."""
    check.files["yours"] = path
    check.install([("yours", "left", "left"), ("yours", "right", "right")])
    print("\nYour file is loaded. Commands: p = play, s = pause, t HH:MM:SS.mmm = go to a time, i = show the time, q = quit.", flush=True)
    note = check.message()
    if note:
        print(f"  the node says: {note}")
    check.files.pop("yours")                                              # (not ours to delete)
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue
        command, _, argument = line.partition(" ")
        if command == "q":
            break
        elif command == "p":
            check.action("play")
            print(f"  playing from {format_time(check.state()[1])}  {check.message()}")
        elif command == "s":
            check.action("pause")
            print(f"  paused at {format_time(check.state()[1])}")
        elif command == "t":
            try:
                check.seek(parse_time(argument))
            except ValueError:
                print("  not a time; write it as HH:MM:SS.mmm")
                continue
            print(f"  time is now {format_time(check.state()[1])}")
        elif command == "i":
            playing, t = check.state()
            print(f"  {'playing' if playing else 'paused'} at {format_time(t)}")
        else:
            print("  p, s, t HH:MM:SS.mmm, i or q")
    check.action("pause")


def main(argv):
    parser = argparse.ArgumentParser(description="Listening check of the realtime preview node (plan step 7).")
    parser.add_argument("--list", action="store_true", help="list the playback devices and stop")
    parser.add_argument("--device", help="the exact name of the device to use (default: the system default)")
    parser.add_argument("--wav", help="a WAV file of your own to play in an interactive player after the tests")
    parser.add_argument("--loud", action="store_true", help="add the loud clipping test")
    parser.add_argument("--auto", action="store_true", help="no questions, no pauses for answers (with --backend null this runs without sound)")
    parser.add_argument("--backend", choices=("system", "null"), default="system", help="'null' plays nowhere (to test this script)")
    args = parser.parse_args(argv)
    check = Check(args.backend, args.device, args.auto)
    try:
        listing = read_text(e.engine_audio_devices, check.engine)
        names = listing.split("\n") if listing else []
        print(f"Playback devices ({args.backend} audio system): " + (", ".join(f'"{n}"' for n in names) if names else "none found"))
        if args.list:
            return 0
        print(f"The preview will use: {args.device or 'the system default device'}")
        if not args.auto:
            input("Keep your volume LOW. Press Enter to start. ")
        run(check, args.loud)
        if args.wav:
            player(check, os.path.abspath(args.wav))
    except KeyboardInterrupt:
        print("\n(stopped)")
    finally:
        try:
            check.action("pause")
        except Exception:                                                  # noqa: BLE001
            pass
        check.close()
    print("\nResults:")
    for name, answer in check.results:
        print(f"  {name:48s} {answer}")
    return 0 if all(answer in ("y", "auto") for _, answer in check.results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
