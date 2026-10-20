# SPDX-License-Identifier: GPL-3.0-or-later
"""The Python API snippet of design section 15, as a program that runs (plan step 14: "a fresh checkout builds, installs and runs the section 15 snippet").

    python examples/section15.py               makes a one-second test tone WAV file, builds the graph of the snippet, shows the editor and reads from the graph
    python examples/section15.py --no-window   the same without the window (what the tests run)
    python examples/section15.py song.wav      uses that WAV file instead of the test tone

The lines that are the snippet's own are marked "section 15"; the rest is what the snippet leaves to the reader (a file to play, the "open" press that
loads it, a printout)."""
import math
import os
import struct
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(os.path.dirname(HERE), "canopysynth")):           # run from an unzipped folder, not installed: find the package next to examples/
    sys.path.insert(0, os.path.dirname(HERE))

import canopysynth                                                  # noqa: E402


def write_tone(path, seconds=1.0, rate=48000, hertz=440.0):
    """A 16-bit stereo WAV file: a sine in the left channel (half scale), silence in the right."""
    with wave.open(path, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for k in range(int(seconds * rate)):
            frames += struct.pack("<hh", int(16000 * math.sin(2 * math.pi * hertz * k / rate)), 0)
        out.writeframes(bytes(frames))


def main(argv):
    window = "--no-window" not in argv
    files = [a for a in argv if not a.startswith("--")]
    with tempfile.TemporaryDirectory() as folder:
        wav = os.path.abspath(files[0]) if files else os.path.join(folder, "song.wav")
        if not files:
            write_tone(wav)

        graph = canopysynth.Graph()                                      # section 15
        song = graph.add("file_read", path=wav)                          # section 15 (it names C:/audio/song.wav)
        left = graph.add("boundary_outlet", name="song_left")            # section 15
        level = graph.add("boundary_inlet", name="intensity")            # section 15
        graph.connect(song.outlet("left"), left.inlet("in"))             # section 15
        graph.loop_protection = True                                     # section 15

        if window:
            import tkinter as tk
            root = tk.Tk()                                               # section 15
            editor = canopysynth.Editor(root, graph)                     # section 15: a tk.Frame
            editor.pack(side="right", fill="both", expand=True)          # section 15

        engine = canopysynth.Engine(graph)                               # section 15
        engine.action(song.id, "open")                                   # (the node's Open... button: the file was loaded when the engine compiled; this loads it again)
        for b in engine.boundary_nodes():                                # section 15
            print(b.name, b.kind)                                        # section 15
        engine.set_boundary("intensity", 0.7)                            # section 15

        inst = engine.new_instance()                                     # section 15
        t_ns = 251_000_000                                               # a quarter of a second in
        t0_ns, t1_ns = 0, 10_000_000                                     # the first 10 ms
        value = inst.value("song_left", t_ns)                            # section 15
        n = canopysynth.ns_to_frame(t1_ns, 48000) - canopysynth.ns_to_frame(t0_ns, 48000)     # section 15
        audio = inst.audio("song_left", t0_ns, t1_ns, n)                 # section 15
        frame, frac = canopysynth.ns_to_frame_fraction(t_ns, 44100)      # section 15
        d = graph.to_dict()                                              # section 15
        print(f"value at {t_ns} ns = {value:.4f}; {n} samples, peak {max(abs(x) for x in audio):.4f}; frame {frame} + {frac:.4f}; "
              f"{len(d['nodes'])} nodes saved")
        ok = n == 480 and max(abs(x) for x in audio) > 0.1 and len(d["nodes"]) == 3 and d["loop_protection"] is True
        if not files:
            ok = ok and abs(value) <= 0.5 + 1e-6
        if window and ok:
            root.after(200, root.destroy)                                # (the snippet leaves the window open; this program closes it and goes on)
            root.mainloop()
        inst.close()
        engine.close()
        if window:
            try:
                root.destroy()
            except tk.TclError:
                pass
    print("ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
