"""Tests: the editor with an Engine made over the same Graph (plan step 12), in real off-screen windows and with miniaudio's null backend (nothing is
heard): edits compile and swap, a graph that cannot be compiled leaves the previous one running, knobs reach the engine live, the preview node's buttons,
time field and device list, the file node's Open..., the notes shown under nodes, and the engines' life with the editor's. Helpers come from test_editor.py,
test_editor_controls.py and test_engine_controls.py. Timing is loose: real time on a machine that may be busy."""
import contextlib
import ctypes
import os
import random
import subprocess
import sys
import tempfile
import time

import canopysynth
import engine_dll as e
from canopysynth import Engine, Graph, GraphError
from canopysynth import _descriptor as d
from test_editor import at, items, one, window
from test_editor_controls import catch_menus, click, double_click, field_point, knob_point, labels, type_into_box, widgets_of
from test_engine_controls import serial, wait_until, write_tone

MS = 1_000_000
INITIAL_TIME = "00:00:00.000"


def pump(editor, seconds=0.0, until=None, timeout=3.0):
    """Runs Tk's events (the editor's timer included) for `seconds`, or until `until()` is true (at most `timeout`); returns what `until` said."""
    end = time.time() + (timeout if until is not None else seconds)
    while time.time() < end:
        editor.update()
        if until is not None and until():
            return True
        time.sleep(0.01)
    editor.update()
    return until() if until is not None else None


def add_unnamed(graph, type_key="boundary_outlet", x=700, y=450):
    """A boundary node without a name, put into the model the way a host, or a file written by another program, can (the model allows it while editing
    and the engine refuses it when the graph is compiled). The editor never makes one, so this is how a test gets a graph that cannot be compiled."""
    return graph.add(type_key, x=x, y=y)


def build(graph):
    nodes = {
        "play": graph.add("realtime_preview", x=20, y=10),
        "file": graph.add("file_read", x=330, y=10),
        "src": graph.add("boundary_inlet", x=10, y=300, name="x"),
        "out": graph.add("boundary_outlet", x=300, y=300, name="y"),
        "free": graph.add("boundary_outlet", x=600, y=300, name="free"),
    }
    graph.connect(nodes["src"].outlet("out"), nodes["out"].inlet("in"))
    return nodes


@contextlib.contextmanager
def linked(width=900, height=640):
    """Yields (editor, graph, nodes, engine): the sample graph, an Engine made over it before the window (null audio), and the editor."""
    graph = Graph()
    nodes = build(graph)
    engine = Engine(graph)
    engine.set_audio_backend("null")
    try:
        with window(graph, width, height) as editor:
            yield editor, graph, nodes, engine
    finally:
        engine.close()


def engine_knob(engine, node, key):
    """The position of a knob as the installed graph of the engine holds it (read through the DLL: the bridge has no call for it)."""
    function = engine._lib.canopy_engine_get_knob
    function.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_int32, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint64)]
    function.restype = ctypes.c_int32
    value = ctypes.c_float()
    assert function(engine._engine, node.id, node.info.inlet_index[key], ctypes.byref(value), None) == 0
    return value.value


def time_text(editor, node):
    return editor.canvas.itemcget(one(editor, f"widgetvalue:{node.id}:3"), "text")


def button_point(editor, node, label):
    w = widgets_of(editor, node)[label]
    return at(editor, w.x + w.w / 2, w.y + w.h / 2)


# ---------------------------------------------------------------- compile and swap

def test_py_every_edit_that_changes_what_an_engine_compiles_compiles_again_and_the_quiet_edits_do_not():
    with linked() as (editor, graph, nodes, engine):
        collected = []
        original = engine.collect
        engine.collect = lambda: (collected.append(1), original())[1]
        base = serial(engine)
        added = editor.add_node("boundary_inlet", 600, 450)                            # a node added: compiled at once, under a name of its own
        assert serial(engine) == base + 1 and editor.message == "" and [b.name for b in engine.boundary_nodes()] == ["default0", "free", "x", "y"]
        editor.edit_setting(added, "name", "z")                                         # a setting: compiled
        assert serial(engine) == base + 2 and [b.name for b in engine.boundary_nodes()] == ["free", "x", "y", "z"]
        assert editor.connect(added.outlet("out"), nodes["free"].inlet("in"))           # a connection
        assert serial(engine) == base + 3
        assert editor.disconnect(nodes["free"].inlet("in"))                             # and its removal
        assert serial(engine) == base + 4
        editor.edit_setting(nodes["play"], "device", "(system default)")                # a value that did not change: nothing is told, nothing compiled
        assert serial(engine) == base + 4 and collected == []
        editor.remove_node(added)                                                       # a node removed: compiled, then the engine lets go of what it can
        assert serial(engine) == base + 5 and collected == [1] and [b.name for b in engine.boundary_nodes()] == ["free", "x", "y"]
        before = serial(engine)
        box = editor.box(nodes["out"])
        start = at(editor, box.x + 40, box.y + 8)
        editor.canvas.event_generate("<ButtonPress-1>", x=int(start[0]), y=int(start[1]), time=900000)           # a node dragged: moved, no compile
        editor.canvas.event_generate("<B1-Motion>", x=int(start[0]) + 30, y=int(start[1]) + 10, state=0x100, time=900010)
        editor.canvas.event_generate("<ButtonRelease-1>", x=int(start[0]) + 30, y=int(start[1]) + 10, time=900020)
        editor.update()
        editor.set_knob(nodes["free"], "in", 0.25)                                       # a knob, selecting, the loop protection switch: none compile
        editor.select(nodes["free"].id)
        editor.select_nodes([nodes["play"].id, nodes["file"].id])
        editor.set_loop_protection(False)
        editor.set_loop_protection(True)
        assert serial(engine) == before and nodes["out"].x == 330


def test_py_a_graph_that_cannot_be_compiled_leaves_the_engine_running_the_previous_one_and_the_message_stays_until_it_can():
    with linked() as (editor, graph, nodes, engine):                                     # (the editor itself never makes a boundary node without a name or with a taken one; a host can)
        instance = engine.new_instance()
        try:
            engine.set_boundary("x", 0.5)
            assert instance.value("y", 0) == 0.5
            base = serial(engine)
            new = add_unnamed(graph)                                                     # a host adds a boundary node without a name: the next edit cannot be compiled
            assert editor.connect(nodes["src"].outlet("out"), nodes["free"].inlet("in"))
            assert serial(engine) == base and "not applied" in editor.message and "previous graph" in editor.message and "needs a name" in editor.message
            assert editor._message_after is None                                         # it stays: nothing clears it by itself
            pump(editor, 0.3)
            assert "needs a name" in editor.message
            assert instance.value("y", 0) == 0.5                                         # the previous graph is still what runs
            new.set("name", "y")                                                         # a name that is taken: the compile fails too, with the model's words
            assert editor.disconnect(nodes["free"].inlet("in"))
            assert serial(engine) == base and "used by node" in editor.message
            editor.say("something else")                                                  # another sentence replaces it...
            editor.edit_setting(new, "name", "w")
            assert serial(engine) == base + 1 and editor.message == "something else"      # ...and a compile that works does not clear what it did not say
            assert instance.value("w", 0) == 0.0 and instance.value("y", 0) == 0.5        # the new graph runs now
            again = add_unnamed(graph, "boundary_inlet", 800, 450)                        # fail again, then fix: the message goes
            editor.edit_setting(new, "name", "w2")
            assert "needs a name" in editor.message and serial(engine) == base + 1
            editor.remove_node(again)
            assert editor.message == "" and serial(engine) == base + 2
        finally:
            instance.close()


def test_py_a_knob_moved_in_the_editor_reaches_the_engine_at_once_by_dragging_or_typing_and_compiles_nothing():
    with linked() as (editor, graph, nodes, engine):
        instance = engine.new_instance()
        try:
            base = serial(engine)
            x, y = knob_point(editor, nodes["free"], "in")
            editor.canvas.event_generate("<ButtonPress-1>", x=int(x), y=int(y), time=910000)
            editor.canvas.event_generate("<B1-Motion>", x=int(x), y=int(y) - 50, state=0x100, time=910010)
            editor.update()
            assert nodes["free"].knobs["in"] == 0.5 and instance.value("free", 0) == 0.5          # while the button is still down
            editor.canvas.event_generate("<ButtonRelease-1>", x=int(x), y=int(y) - 50, time=910020)
            double_click(editor, x, y)
            type_into_box(editor, "-0.25")
            assert instance.value("free", 0) == -0.25 and serial(engine) == base
            assert engine_knob(engine, nodes["play"], "left") == 0.0
            editor.set_knob(nodes["play"], "left", 0.75)                                   # the preview node's inlet, which has no wire
            assert engine_knob(engine, nodes["play"], "left") == 0.75 and serial(engine) == base
            add_unnamed(graph, "boundary_inlet", 700, 450)                                # (a host's node without a name: the graph cannot be compiled)
            late = editor.add_node("boundary_outlet", 600, 450)                           # a node the engine does not have (its compile failed): ignored
            editor.set_knob(late, "in", 0.5)
            assert "needs a name" in editor.message and "knob" not in editor.message       # (the message is the compile error, not a knob error)
            assert serial(engine) == base
        finally:
            instance.close()


def random_edit_run(editor, graph, engine, instance, rng, steps, written=None, protected=(), between=None, stop=None):
    """A long run of random edits made through the editor, with these checks after each: no edit left a graph the engine could not compile, each edit that
    changes the graph compiled it exactly once and the others not at all, the engine's boundary nodes are the editor's, and what the engine gives for each
    boundary outlet is what the picture says (the wire's source, as last written, or the knob). `written` is what the host last wrote to each boundary inlet
    that is there (by node ID; a node starts at 0). `protected` are node IDs the run leaves alone (another thread uses them: the run neither edits nor checks
    them); `between(step)` is called after each edit (the stress pumps Tk and presses buttons there; it returns how many times it installed the
    graph itself, if it did) and `stop()` ends the run early. Returns what was done."""
    written = dict(written or {})
    base, compiles = serial(engine), 0
    names = ["", "x", "y", "free", "default0", "default1", "n0", "n1", "n2", "N0"]
    done = dict.fromkeys(("add", "renamed", "refused", "connected", "unconnected", "disconnected", "removed", "knob", "write"), 0)
    actions = ["add", "add", "rename", "rename", "rename", "connect", "connect", "disconnect", "remove", "knob", "write", "write"]
    for step in range(steps):
        if stop is not None and stop():
            break
        all_boundary = [n for n in graph.nodes() if n.type in ("boundary_inlet", "boundary_outlet")]
        boundary = [n for n in all_boundary if n.id not in protected]
        inlets = [n for n in boundary if n.type == "boundary_inlet"]
        outlets = [n for n in boundary if n.type == "boundary_outlet"]
        action = rng.choice(actions)
        if action == "add" and len(boundary) < 10:
            node = editor.add_node(rng.choice(["boundary_inlet", "boundary_outlet"]), 10 * step % 800, 450)
            written[node.id] = 0.0
            compiles, done["add"] = compiles + 1, done["add"] + 1
        elif action == "rename" and boundary:
            node, text = rng.choice(boundary), rng.choice(names)
            old, taken = node.settings["name"], {n.settings["name"] for n in all_boundary if n is not node}
            result = editor.edit_setting(node, "name", text)
            assert result == (text != "" and text not in taken), (step, text, sorted(taken))
            if result and text != old:
                compiles, done["renamed"] = compiles + 1, done["renamed"] + 1
            done["refused"] += not result
        elif action == "connect" and inlets and outlets:
            source, target = rng.choice(inlets), rng.choice(outlets)
            reason = graph.can_connect(source.outlet("out"), target.inlet("in"))
            made = editor.connect(source.outlet("out"), target.inlet("in"))
            assert made == (reason is None) and (made or reason in editor.message), (step, reason, editor.message)
            compiles, done["connected"], done["unconnected"] = compiles + made, done["connected"] + made, done["unconnected"] + (not made)
        elif action == "disconnect" and any(graph.connection_into(n.inlet("in")) for n in outlets):
            target = rng.choice([n for n in outlets if graph.connection_into(n.inlet("in"))])
            assert editor.disconnect(target.inlet("in"))
            compiles, done["disconnected"] = compiles + 1, done["disconnected"] + 1
        elif action == "remove" and len(boundary) > 2:
            node = rng.choice(boundary)
            editor.remove_node(node)
            written.pop(node.id, None)
            compiles, done["removed"] = compiles + 1, done["removed"] + 1
        elif action == "knob" and outlets:
            editor.set_knob(rng.choice(outlets), "in", rng.choice([-1.0, -0.5, 0.0, 0.25, 1.0]))
            done["knob"] += 1
        elif action == "write" and inlets:
            node, value = rng.choice(inlets), rng.choice([-2.5, 0.0, 0.5, 3.75])
            engine.set_boundary(node.settings["name"], value)
            written[node.id] = value
            done["write"] += 1
        assert "not applied" not in editor.message, (step, editor.message)                  # no edit left a graph the engine could not compile
        assert serial(engine) == base + compiles, (step, serial(engine) - base, compiles)  # each edit that changes the graph compiled it once, the others not at all
        assert graph.boundary_nodes() == engine.boundary_nodes(), step                       # the engine's boundary nodes are the editor's: names, kinds, IDs
        for node in graph.boundary_nodes():
            if node.kind == "outlet" and node.node_id not in protected:                       # and what they give is what the picture says: the wire's source or the knob
                outlet = graph.node(node.node_id)
                connection = graph.connection_into(outlet.inlet("in"))
                wanted = written[connection.outlet.node.id] if connection else outlet.knobs["in"]
                assert instance.value(node.name, 0) == wanted, (step, node.name)
        if between is not None:
            compiles += between(step) or 0                                                      # (it returns how many times it installed the graph itself)
    return done


def test_py_after_every_edit_of_a_long_random_run_the_engine_plays_exactly_the_graph_the_editor_shows_and_no_compile_fails():
    with linked() as (editor, graph, nodes, engine):
        instance = engine.new_instance()
        try:
            done = random_edit_run(editor, graph, engine, instance, random.Random(20261005), 400, written={nodes["src"].id: 0.0})
            assert min(done.values()) > 5, done                                                       # (the run did try every kind of edit, often)
        finally:
            instance.close()


# ---------------------------------------------------------------- the preview node

def test_py_the_preview_node_plays_and_pauses_from_its_buttons_and_its_time_field_follows_and_takes_a_typed_time():
    with linked() as (editor, graph, nodes, engine):
        play = nodes["play"]
        assert pump(editor, until=lambda: time_text(editor, play) == INITIAL_TIME)
        assert time_text(editor, play) == INITIAL_TIME and engine.preview_state(play.id) == (False, 0)
        click(editor, *button_point(editor, play, "Play"))
        assert engine.preview_state(play.id)[0] is True
        assert pump(editor, until=lambda: time_text(editor, play) != INITIAL_TIME)             # the field moves with the playback, with no event of the user's
        click(editor, *button_point(editor, play, "Pause"))
        assert engine.preview_state(play.id)[0] is False
        pump(editor, 0.3)
        stopped = time_text(editor, play)
        pump(editor, 0.3)
        assert time_text(editor, play) == stopped and stopped != INITIAL_TIME                   # it stands still while paused
        click(editor, *field_point(editor, play, "Time"))                                      # a time typed in
        assert editor._entry is not None and editor._entry[0].get() == stopped
        type_into_box(editor, "00:01:02.500")
        assert engine.preview_state(play.id) == (False, 62_500 * MS) and time_text(editor, play) == "00:01:02.500"
        click(editor, *field_point(editor, play, "Time"))
        type_into_box(editor, "1:30")                                                           # shorter forms are read too
        assert engine.preview_state(play.id) == (False, 90_000 * MS) and time_text(editor, play) == "00:01:30.000"
        click(editor, *field_point(editor, play, "Time"))
        type_into_box(editor, "half past two")
        assert "hh:mm:ss.mmm" in editor.message and engine.preview_state(play.id) == (False, 90_000 * MS)
        click(editor, *button_point(editor, play, "Play"))                                      # play on from the typed time, and type another while it plays
        click(editor, *field_point(editor, play, "Time"))
        type_into_box(editor, "00:00:10.000")
        assert engine.preview_state(play.id)[1] < 10_000 * MS + 1500 * MS and engine.preview_state(play.id)[0] is True
        assert pump(editor, until=lambda: time_text(editor, play) >= "00:00:10.000" and time_text(editor, play) < "00:00:12")


def test_py_the_device_choice_lists_the_machines_devices_and_choosing_one_sets_it_and_a_missing_one_is_said_under_the_node():
    with linked() as (editor, graph, nodes, engine):
        play = nodes["play"]
        shown = catch_menus(editor)
        base = serial(engine)
        click(editor, *field_point(editor, play, "Device"))
        assert labels(shown[-1]) == ["(system default)", "NULL Playback Device"]                # the fixed entry, then what the engine's audio system lists
        assert [editor.getvar(shown[-1].entrycget(i, "variable")) for i in range(2)] == ["(system default)"] * 2
        shown[-1].invoke(1)
        assert play.settings["device"] == "NULL Playback Device" and serial(engine) == base + 1 and editor.message == ""
        click(editor, *button_point(editor, play, "Play"))
        assert engine.preview_state(play.id)[0] is True and items(editor, f"note:{play.id}") == ()
        editor.edit_setting(play, "device", "No such audio device")                              # saved earlier, not on this machine
        assert engine.preview_state(play.id)[0] is True                                         # the "device" action switched it, keeping the state
        assert pump(editor, until=lambda: items(editor, f"note:{play.id}") != ())
        note = editor.canvas.itemcget(one(editor, f"note:{play.id}"), "text")
        assert "audio device not found: No such audio device" in note and "system default" in note
        x0, y0, x1, y1 = editor.canvas.bbox(one(editor, f"note:{play.id}"))                      # under the node, no wider than it
        body = editor.canvas.bbox(one(editor, f"body:{play.id}"))
        assert y0 >= body[3] and x0 >= body[0] - 2 and x1 <= body[2] + 3
        click(editor, *field_point(editor, play, "Device"))
        assert labels(shown[-1]) == ["(system default)", "NULL Playback Device", "No such audio device"]      # the value that is set shows, marked
        assert editor.getvar(shown[-1].entrycget(0, "variable")) == "No such audio device"
        shown[-1].invoke(0)
        assert play.settings["device"] == "(system default)" and engine.node_message(play.id) == ""
        assert pump(editor, until=lambda: items(editor, f"note:{play.id}") == ())              # fixed: the note goes


def test_py_a_button_of_a_node_the_engine_does_not_have_says_so_and_a_node_with_nothing_to_say_has_no_note():
    with linked() as (editor, graph, nodes, engine):
        broken = add_unnamed(graph, "boundary_inlet", 600, 450)                              # a host's node without a name: the graph cannot be compiled...
        extra = editor.add_node("realtime_preview", 700, 10)                                 # ...so this node is not in the installed graph
        editor.say("")
        click(editor, *button_point(editor, extra, "Play"))
        assert f"installed graph has no node {extra.id}" in editor.message
        editor.say("")
        click(editor, *field_point(editor, extra, "Time"))                                   # a time typed into its field is refused by the engine too, and the refusal is said
        type_into_box(editor, "00:00:05.000")
        assert f"installed graph has no node {extra.id}" in editor.message
        editor.redraw()
        assert time_text(editor, extra) == INITIAL_TIME                                      # (the engine never told its time, so the field shows the first one)
        for node_id, note in editor._notes.items():
            assert note != ""                                                                  # only nodes with something to say have a note
        editor.remove_node(broken)
        editor.remove_node(extra)
        assert "not applied" not in editor.message and serial(engine) > 0                      # (the compile worked; the button's own sentence is not the link's to clear)
        assert all(text != "" for text in editor._notes.values())


def test_py_the_device_list_has_the_fixed_entry_once_whatever_the_machine_calls_its_devices():
    with linked() as (editor, graph, nodes, engine):
        shown = catch_menus(editor)
        engine.audio_devices = lambda: ["Speakers", "(system default)", "Headset"]            # (a machine with a device that has the fixed entry's name)
        click(editor, *field_point(editor, nodes["play"], "Device"))
        assert labels(shown[-1]) == ["(system default)", "Speakers", "Headset"]
        engine.audio_devices = lambda: []                                                     # no device at all: just the fixed entry
        click(editor, *field_point(editor, nodes["play"], "Device"))
        assert labels(shown[-1]) == ["(system default)"]
        link = editor._engine_links()[0]                                                      # only the preview's device widget is given the machine's devices
        engine.audio_devices = lambda: ["Speakers"]
        device = [w for w in editor.box(nodes["play"]).widgets if w.setting == "device"][0]
        name = editor.box(nodes["src"]).widgets[0]
        assert link.choices(nodes["play"], device) == ["(system default)", "Speakers"]
        assert link.choices(nodes["src"], name) is None and link.choices(nodes["play"], editor.box(nodes["play"]).widgets[0]) is None
        assert link.choices(nodes["src"], device) is None                                     # (a widget of that name on another type of node does not count)
        editor.select_nodes([nodes["file"].id, nodes["src"].id])                              # a node outside a selected group has the plain item
        assert labels(editor.build_node_menu(nodes["play"]))[0] == "Delete"
        assert labels(editor.build_node_menu(nodes["file"]))[0] == "Delete selected"


def test_py_a_preview_warns_under_its_node_of_nodes_that_feed_it_and_are_not_realtime_safe_and_stops_when_they_are_gone():
    slow = e.PyNodeType("vendor.slow", inlets=[("in", 0.0)], outlets=["out"], at=lambda ctx, outlet, t: 0.0)
    rig = e.Rig(slow)
    try:
        graph = Graph(types=canopysynth.NodeTypes.from_registry(rig.registry, e.lib))
        preview = graph.add("realtime_preview", x=20, y=10)
        node = graph.add("vendor.slow", x=300, y=10)
        with Engine(graph, registry=rig.registry) as engine:
            with window(graph, 800, 500) as editor:
                assert items(editor, f"note:{preview.id}") == ()
                assert editor.connect(node.outlet("out"), preview.inlet("center"))
                editor.redraw()
                text = editor.canvas.itemcget(one(editor, f"note:{preview.id}"), "text")
                assert "not realtime safe" in text and "vendor.slow" in text and f"node {node.id}" in text
                assert items(editor, f"note:{node.id}") == ()                                  # only the preview node is warned about
                assert editor.disconnect(preview.inlet("center"))
                editor.redraw()
                assert items(editor, f"note:{preview.id}") == ()
    finally:
        rig.close()


def test_py_editing_during_playback_keeps_the_preview_playing_and_what_it_plays_is_the_edited_graph():
    slow = e.PyNodeType("vendor.slow", inlets=[("in", 0.0)], outlets=["out"], at=lambda ctx, outlet, t: 0.0)
    rig = e.Rig(slow)
    try:
        graph = Graph(types=canopysynth.NodeTypes.from_registry(rig.registry, e.lib))
        play = graph.add("realtime_preview", x=20, y=10)
        node = graph.add("vendor.slow", x=330, y=10)
        keeper = graph.add("boundary_outlet", x=330, y=250, name="keep")
        with Engine(graph, registry=rig.registry) as engine:
            engine.set_audio_backend("null")
            with window(graph, 900, 640) as editor:
                click(editor, *button_point(editor, play, "Play"))
                assert engine.preview_state(play.id)[0] is True
                last = [0]

                def still_playing():
                    playing, now = engine.preview_state(play.id)
                    moved = pump(editor, until=lambda: engine.preview_state(play.id)[1] > now, timeout=2.0)
                    assert playing is True and moved, "the preview must go on playing, and the time on moving, after every edit"
                    last[0] = engine.preview_state(play.id)[1]
                before = serial(engine)
                assert editor.connect(node.outlet("out"), play.inlet("center"))                     # a wire from a node that is not realtime safe...
                assert "vendor.slow" in engine.preview_warning(play.id)                             # ...is in the installed graph at once, while it plays
                still_playing()
                editor.edit_setting(keeper, "name", "keep2")                                        # a setting
                assert [b.name for b in engine.boundary_nodes()] == ["keep2"]
                still_playing()
                broken = add_unnamed(graph, "boundary_outlet", 700, 450)                            # a host's node without a name...
                added = editor.add_node("boundary_inlet", 600, 450)                                 # ...so this edit cannot be compiled: the old graph plays on
                assert "needs a name" in editor.message and [b.name for b in engine.boundary_nodes()] == ["keep2"]
                still_playing()
                editor.remove_node(broken)                                                           # (fixed: the node that was added, which has a name of its own, is compiled)
                assert [b.name for b in engine.boundary_nodes()] == ["default0", "keep2"] and editor.message == ""
                still_playing()
                editor.edit_setting(added, "name", "level")                                          # a setting of it
                assert [b.name for b in engine.boundary_nodes()] == ["keep2", "level"]
                still_playing()
                editor.set_knob(play, "left", 0.5)                                                   # a knob
                engine.set_boundary("level", 0.25)
                still_playing()
                assert editor.disconnect(play.inlet("center"))
                assert engine.preview_warning(play.id) == ""
                still_playing()
                editor.remove_node(node)                                                             # a node deleted
                assert engine.preview_state(play.id)[0] is True and serial(engine) == before + 6               # the six edits that compile: connect, rename, delete the host's node, name the new node, disconnect, delete
                still_playing()
                click(editor, *button_point(editor, play, "Pause"))
                assert engine.preview_state(play.id)[0] is False and last[0] > 0
    finally:
        rig.close()


# ---------------------------------------------------------------- the file node

def test_py_open_asks_for_a_file_stores_its_absolute_path_has_the_engine_load_it_and_shows_the_name_or_the_problem():
    folder = tempfile.mkdtemp()
    wav = os.path.join(folder, "tone.wav")
    write_tone(wav)
    try:
        with linked() as (editor, graph, nodes, engine):
            file_node = nodes["file"]
            asked = []
            editor.file_chooser = lambda node: asked.append(node.id) or wav
            name_text = lambda: editor.canvas.itemcget(one(editor, f"widgetvalue:{file_node.id}:1"), "text")
            assert name_text() == "(none)"
            base = serial(engine)
            click(editor, *button_point(editor, file_node, "Open..."))
            assert asked == [file_node.id] and file_node.settings["path"] == os.path.abspath(wav) and serial(engine) == base + 1
            assert engine.node_message(file_node.id) == "" and items(editor, f"note:{file_node.id}") == ()
            editor.redraw()
            assert name_text() == "tone.wav"                                                  # the name, not the whole path
            gone = os.path.join(folder, "gone.wav")
            editor.file_chooser = lambda node: gone
            click(editor, *button_point(editor, file_node, "Open..."))
            assert file_node.settings["path"] == os.path.abspath(gone)
            note = editor.canvas.itemcget(one(editor, f"note:{file_node.id}"), "text")
            assert "file not found" in note and "gone.wav" in note and name_text() == "gone.wav"
            editor.file_chooser = lambda node: ""                                              # the dialog was cancelled: nothing changes
            before = (file_node.settings["path"], serial(engine))
            click(editor, *button_point(editor, file_node, "Open..."))
            assert (file_node.settings["path"], serial(engine)) == before
            editor.file_chooser = lambda node: wav                                             # choosing the same file again reloads it (and the note goes)
            click(editor, *button_point(editor, file_node, "Open..."))
            editor.redraw()
            assert items(editor, f"note:{file_node.id}") == ()
            editor.file_chooser = lambda node: "tone.wav"                                      # a relative answer is made absolute from the current folder
            click(editor, *button_point(editor, file_node, "Open..."))
            assert os.path.isabs(file_node.settings["path"]) and file_node.settings["path"] == os.path.abspath("tone.wav")
            assert pump(editor, until=lambda: items(editor, f"note:{file_node.id}") != ())
            actions = []
            editor.add_action_listener(lambda node, action: actions.append((node.id, action)))   # listeners are told as well
            editor.file_chooser = lambda node: wav
            click(editor, *button_point(editor, file_node, "Open..."))
            assert actions == [(file_node.id, "open")]
    finally:
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)


# ---------------------------------------------------------------- engines and the editor's life

def test_py_without_an_engine_the_buttons_and_the_time_field_say_there_is_none_and_an_engine_made_later_is_picked_up():
    graph = Graph()
    nodes = build(graph)
    with window(graph, 900, 640) as editor:
        assert time_text(editor, nodes["play"]) == INITIAL_TIME                                 # with no engine at all, a preview node's time field shows the first time
        click(editor, *button_point(editor, nodes["play"], "Play"))
        assert "no engine is attached" in editor.message
        click(editor, *field_point(editor, nodes["play"], "Time"))
        type_into_box(editor, "00:00:05.000")
        assert "no engine is attached" in editor.message and "nowhere to go" in editor.message
        editor.say("")
        added = editor.add_node("boundary_inlet", 600, 450)                                     # edits without an engine are plain edits: no message
        assert editor.message == ""
        editor.remove_node(added)
        engine = Engine(graph)                                                                  # made after the editor: found at its next tick
        try:
            engine.set_audio_backend("null")
            editor._engine_links()                                                              # seen at once, with its time and notes, not a tick later
            assert editor._time_texts.get(nodes["play"].id) == INITIAL_TIME and editor._links != {}
            assert pump(editor, until=lambda: editor._links != {} and time_text(editor, nodes["play"]) == INITIAL_TIME)
            click(editor, *button_point(editor, nodes["play"], "Play"))
            assert engine.preview_state(nodes["play"].id)[0] is True
            editor.edit_setting(nodes["free"], "name", "renamed")                               # and edits reach it from then on
            assert [b.name for b in engine.boundary_nodes()] == ["renamed", "x", "y"]
        finally:
            engine.close()
        editor.say("")
        editor.edit_setting(nodes["free"], "name", "again")                                     # a closed engine is let go: no error, no message
        assert editor.message == "" and graph.engines() == []
        pump(editor, 0.3)
        assert editor._links == {}


def test_py_every_engine_made_over_the_graph_is_kept_up_to_date_and_gets_the_buttons_and_the_knobs():
    with linked() as (editor, graph, nodes, engine):
        other = Engine(graph)
        try:
            other.set_audio_backend("null")
            base = (serial(engine), serial(other))
            editor.add_node("boundary_inlet", 600, 450)
            editor.edit_setting(graph.nodes()[-1], "name", "second")
            assert (serial(engine), serial(other)) == (base[0] + 2, base[1] + 2)                 # (the node compiled when it was added, and again when it was named)
            assert [b.name for b in other.boundary_nodes()] == [b.name for b in engine.boundary_nodes()] and "second" in [b.name for b in other.boundary_nodes()]
            instance = other.new_instance()
            try:
                editor.set_knob(nodes["free"], "in", 0.5)
                assert instance.value("free", 0) == 0.5                                          # the knob reached the second engine too
            finally:
                instance.close()
            click(editor, *button_point(editor, nodes["play"], "Play"))
            assert engine.preview_state(nodes["play"].id)[0] is True and other.preview_state(nodes["play"].id)[0] is True
            editor.set_graph(Graph())                                                            # another graph: no engine of this one is the editor's any more
            assert editor._links == {} and editor._notes == {} and editor._time_texts == {}
        finally:
            other.close()


def test_py_deleting_a_node_from_its_menu_compiles_the_graph_without_it_and_collects_and_the_polling_goes_on_quietly():
    with linked() as (editor, graph, nodes, engine):
        collected = []
        original = engine.collect
        engine.collect = lambda: (collected.append(1), original())[1]
        shown = catch_menus(editor)
        play = nodes["play"]
        click(editor, *button_point(editor, play, "Play"))
        assert engine.preview_state(play.id)[0] is True
        box = editor.box(play)
        editor.canvas.event_generate("<ButtonPress-3>", x=int(at(editor, box.x + 40, box.y + 8)[0]), y=int(at(editor, box.x + 40, box.y + 8)[1]), time=920000)
        editor.update()
        assert labels(shown[-1]) == ["Delete"]
        base = serial(engine)
        shown[-1].invoke(0)
        assert serial(engine) == base + 1 and collected == [1] and play.graph is None
        try:
            engine.preview_state(play.id)
        except GraphError as error:
            assert f"no node {play.id}" in str(error)
        else:
            raise AssertionError("the deleted preview node must be gone from the installed graph")
        pump(editor, 0.4)                                                                        # the timer asks for the time of no node: nothing happens
        assert [n.type for n in graph.nodes()].count("realtime_preview") == 0


def test_py_destroying_an_editor_that_has_an_engine_cancels_its_timer_and_nothing_runs_after_the_window_is_gone():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = (
        "import sys, time, tkinter as tk\n"
        f"sys.path.insert(0, r'{base}')\n"
        "import canopysynth\n"
        "from canopysynth.editor import Editor\n"
        "root = tk.Tk(); root.geometry('400x300+6000+6000')\n"
        "root.tk.eval('proc bgerror {message} {lappend ::background_errors $message}')\n"
        "graph = canopysynth.Graph(); graph.add('realtime_preview')\n"
        "engine = canopysynth.Engine(graph); engine.set_audio_backend('null')\n"
        "editor = Editor(root, graph, width=400, height=250); editor.pack(); root.update()\n"
        "editor.after(150, lambda: None)\n"
        "end = time.time() + 0.3\n"
        "while time.time() < end:\n"
        "    root.update(); time.sleep(0.01)\n"
        "assert editor._links, 'the engine was not found'\n"
        "editor.destroy()\n"
        "end = time.time() + 0.5\n"
        "while time.time() < end:\n"
        "    root.update(); time.sleep(0.01)\n"
        "try:\n"
        "    print('background errors:', root.tk.eval('set ::background_errors'))\n"
        "except tk.TclError:\n"
        "    print('no background errors')\n"
        "root.destroy(); engine.close(); print('done')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.stdout.split("\n")[:2] == ["no background errors", "done"] and result.stderr == "", (result.stdout, result.stderr)
