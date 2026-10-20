# SPDX-License-Identifier: GPL-3.0-or-later
"""Try the editor with a real Engine and your real sound device (plan step 12; the author's check of "editing during playback").

    python dev/editor_try.py                       opens the editor on a small graph: two file nodes (A and B) and a realtime preview node, A's two
                                                   outlets wired to the preview's left and right inlets; the Engine plays through the machine's audio
    python dev/editor_try.py --wav C:/music/a.wav  opens that file in node A first (the same as pressing its Open... button)
    python dev/editor_try.py --audio null          the same with no sound (miniaudio's null device)

What to try (everything is live: the Engine compiles the graph again after every edit and the preview keeps playing):
  - press Open... on file A (a WAV file: 8, 16, 24 or 32 bit PCM or 32-bit float), then Play on the preview node; pause; type a time in its Time field
    (hh:mm:ss.mmm, or mm:ss or just seconds) and press Enter; play on from there;
  - while it plays: open another file in A (it replaces the sound at once), take A's wires off the preview's inlets (right-click an inlet, Disconnect)
    and wire B in instead (drag from B's outlets to the preview's inlets);
  - click the Device box of the preview node: it lists "(system default)" and the playback devices of this machine; choose one (the sound moves to it);
  - give a node a bad file (Open... a file that is not a WAV): the node says why under itself and the old sound keeps playing;
  - right-click the background and add a boundary node without a name: the message line says the graph cannot be compiled, and the preview goes on
    playing the previous graph until you name it (right-click it, Rename...).
Close the window to stop (the device is closed with the Engine)."""
import argparse
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import canopysynth                                         # noqa: E402
from canopysynth.editor import Editor                      # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="the editor with a real engine")
    parser.add_argument("--audio", choices=("system", "null"), default="system", help="the audio system (default: the machine's own)")
    parser.add_argument("--wav", metavar="FILE", help="a WAV file to open in file node A at the start")
    options = parser.parse_args()
    graph = canopysynth.Graph()
    a = graph.add("file_read", x=20, y=60)
    graph.add("file_read", x=20, y=300)
    preview = graph.add("realtime_preview", x=420, y=40)
    graph.connect(a.outlet("left"), preview.inlet("left"))
    graph.connect(a.outlet("right"), preview.inlet("right"))
    if options.wav:
        a.set("path", os.path.abspath(options.wav))
    engine = canopysynth.Engine(graph)
    engine.set_audio_backend(options.audio)
    if options.wav:
        engine.action(a.id, "open")
    root = tk.Tk()
    root.title(f"canopysynth editor with an engine ({options.audio} audio)")
    root.geometry("1000x680+60+40")
    editor = Editor(root, graph, width=1000, height=640)
    editor.pack(fill="both", expand=True)
    try:
        root.mainloop()
    finally:
        engine.close()


if __name__ == "__main__":
    main()
