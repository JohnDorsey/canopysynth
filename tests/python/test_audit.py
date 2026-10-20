# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests added by the final audit of plan step 15: statements of the design that the audit found true but not asserted by any test. Each says which statement.
Design 9: after the end of the audio the preview keeps playing silence until paused. Design 15: `Editor` is a tk.Frame that packs beside the host's own controls.
Design 16: an editor whose engine cannot compile what it was given (a GraphError, not only a BoundaryError) shows the reason and keeps the previous graph running."""
import os
import tempfile
import time
import tkinter as tk

import canopysynth
from canopysynth import Engine, Graph, GraphError
from test_editor import window
from test_editor_link import linked, pump
from test_engine_controls import wait_until, write_tone


def test_py_after_the_end_of_the_audio_the_preview_goes_on_playing_silence_until_it_is_paused():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "short.wav")
        write_tone(path, seconds=0.1)                                          # a tenth of a second of sound
        graph = Graph()
        song = graph.add("file_read", path=path)
        play = graph.add("realtime_preview")
        graph.connect(song.outlet("left"), play.inlet("left"))
        with Engine(graph) as engine:
            engine.set_audio_backend("null")
            assert engine.node_message(song.id) == ""
            engine.action(play.id, "play")
            try:
                assert wait_until(lambda: engine.preview_state(play.id)[1] > 500_000_000)       # half a second in: well past the end of the file
                playing, first = engine.preview_state(play.id)
                assert playing is True
                assert wait_until(lambda: engine.preview_state(play.id)[1] > first + 100_000_000)   # and still moving on
                assert engine.preview_state(play.id)[0] is True
            finally:
                engine.action(play.id, "pause")
            assert wait_until(lambda: engine.preview_state(play.id)[0] is False)
            stopped = engine.preview_state(play.id)[1]
            time.sleep(0.3)
            assert engine.preview_state(play.id) == (False, stopped), "the time moved after Pause"


def test_py_the_editor_is_a_tk_frame_that_packs_to_the_right_of_the_hosts_own_controls():
    root = tk.Tk()
    try:
        root.geometry("900x500+6000+6000")
        graph = Graph()
        left = tk.Frame(root, width=120)
        tk.Button(left, text="the host's own button").pack()
        left.pack(side="left", fill="y")
        editor = canopysynth.Editor(root, graph)                             # (design section 15: `canopysynth.Editor(root, graph)  # a tk.Frame`)
        editor.pack(side="right", fill="both", expand=True)
        root.update()
        assert isinstance(editor, tk.Frame)
        assert left.winfo_rootx() + left.winfo_width() <= editor.winfo_rootx(), "the editor is not to the right of the host's controls"
        assert editor.winfo_width() > 400 and left.winfo_width() >= 100
        assert root.cget("menu") == "", "the editor gave the host's window a menu bar"
    finally:
        root.destroy()


def test_py_an_engine_that_raises_a_graph_error_when_the_editor_asks_it_to_compile_is_shown_and_the_previous_graph_keeps_running():
    with linked() as (editor, graph, nodes, engine):
        instance = engine.new_instance()
        try:
            engine.set_boundary("x", 0.5)
            assert instance.value("y", 0) == 0.5
            real_update = engine.update

            def refuse():
                raise GraphError("the engine says no, for a reason of its own")

            engine.update = refuse                                           # (what a compile fault other than a boundary name looks like to the editor)
            try:
                assert editor.connect(nodes["src"].outlet("out"), nodes["free"].inlet("in"))
                assert "not applied" in editor.message and "previous graph" in editor.message and "for a reason of its own" in editor.message, editor.message
                pump(editor, 0.3)
                assert "for a reason of its own" in editor.message             # it stays
                assert instance.value("y", 0) == 0.5                             # the previous graph is what runs
            finally:
                engine.update = real_update
            assert editor.disconnect(nodes["free"].inlet("in"))                  # the next edit compiles again, and the message goes
            assert editor.message == ""
        finally:
            instance.close()
