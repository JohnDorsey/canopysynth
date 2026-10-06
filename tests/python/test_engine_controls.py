"""Tests: the calls of `Engine` that the editor uses (plan step 12) against the real DLL: live knob writes, actions and node messages, collect, the audio
backend and its devices, and the preview node's state, time and warning. Audio always goes through miniaudio's null backend (no sound hardware, nothing
audible). Timing assertions are loose: a few hundred milliseconds of real time on a machine that may be busy."""
import ctypes
import os
import tempfile
import time
import wave

import canopysynth
import engine_dll as e
from canopysynth import Engine, Graph, GraphError
from canopysynth import _descriptor as d

MS = 1_000_000


def graph_with_boundaries():
    graph = Graph()
    nodes = {"in": graph.add("boundary_inlet", name="x"), "out": graph.add("boundary_outlet", name="y")}
    return graph, nodes


def write_tone(path, seconds=1.0, rate=8000):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x10\x00" * int(rate * seconds))


def wait_until(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def serial(engine):
    """The serial number of the installed graph: it goes up by one with every install."""
    function = engine._lib.canopy_engine_graph_serial
    function.argtypes, function.restype = [ctypes.c_void_p], ctypes.c_int64
    return function(engine._engine)


# ---------------------------------------------------------------- knobs

def test_py_a_knob_written_through_the_engine_reaches_the_next_query_without_compiling_again():
    graph, nodes = graph_with_boundaries()
    with Engine(graph) as engine:
        instance = engine.new_instance()
        try:
            assert instance.value("y", 0) == 0.0                                          # the inlet "in" of the boundary outlet: its knob, at 0
            before = serial(engine)
            engine.set_knob(nodes["out"].id, "in", 0.5)
            assert instance.value("y", 0) == 0.5 and instance.value("y", 10 ** 12) == 0.5
            engine.set_knob(nodes["out"].id, "in", -1)
            assert instance.value("y", 0) == -1.0
            engine.set_knob(nodes["out"].id, "in", 1.0)
            assert instance.value("y", 0) == 1.0 and serial(engine) == before             # nothing was installed
            for bad in (1.5, -1.0001, float("nan"), "0.5", True, None):
                try:
                    engine.set_knob(nodes["out"].id, "in", bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"{bad!r} must be refused")
            assert instance.value("y", 0) == 1.0                                          # a refused value changed nothing
        finally:
            instance.close()


def test_py_a_knob_call_for_a_node_or_inlet_that_is_not_there_says_which_and_a_node_the_installed_graph_lacks_says_why():
    graph, nodes = graph_with_boundaries()
    with Engine(graph) as engine:
        for node_id, inlet, wanted in ((999, "in", "has no node 999"), (nodes["out"].id, "nope", "no inlet 'nope'"), (nodes["out"].id, 5, "no inlet 5")):
            try:
                engine.set_knob(node_id, inlet, 0.0)
            except GraphError as error:
                assert wanted in str(error), str(error)
            else:
                raise AssertionError("must raise GraphError")
        late = graph.add("boundary_outlet", name="late")                                  # in the Graph, not yet in the installed graph
        try:
            engine.set_knob(late.id, "in", 0.5)
        except GraphError as error:
            assert f"installed graph has no node {late.id}" in str(error) and "older" in str(error)
        else:
            raise AssertionError("must raise GraphError")
        engine.update()
        engine.set_knob(late.id, "in", 0.5)                                                # after the install it works


def test_py_a_knob_is_written_to_the_inlet_that_was_named_not_the_first():
    graph = Graph()
    preview = graph.add("realtime_preview")                                                # inlets left, right, center
    with Engine(graph) as engine:
        function = engine._lib.canopy_engine_get_knob
        function.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_int32, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint64)]
        function.restype = ctypes.c_int32

        def knobs():
            values = []
            for index in range(3):
                value = ctypes.c_float()
                assert function(engine._engine, preview.id, index, ctypes.byref(value), None) == 0
                values.append(value.value)
            return values
        assert knobs() == [0.0, 0.0, 0.0]
        engine.set_knob(preview.id, "center", 0.5)
        assert knobs() == [0.0, 0.0, 0.5]
        engine.set_knob(preview.id, "right", -0.25)
        assert knobs() == [0.0, -0.25, 0.5]


# ---------------------------------------------------------------- actions, messages, collect

def test_py_a_button_action_reaches_the_node_and_what_it_says_about_itself_comes_back_as_text():
    graph = Graph()
    folder = tempfile.mkdtemp()
    wav = os.path.join(folder, "tone.wav")
    write_tone(wav)
    node = graph.add("file_read", path=os.path.join(folder, "missing.wav"))
    out = graph.add("boundary_outlet", name="y")
    graph.connect(node.outlet("left"), out.inlet("in"))
    try:
        with Engine(graph) as engine:
            assert "file not found" in engine.node_message(node.id) and "missing.wav" in engine.node_message(node.id)    # flagged at creation (design section 14)
            node.set("path", wav)
            engine.update()
            assert "file not found" in engine.node_message(node.id)                       # a new path alone loads nothing (the file is read at "open")
            engine.action(node.id, "open")
            assert engine.node_message(node.id) == ""
            instance = engine.new_instance()
            try:
                assert abs(instance.value("y", 100 * MS) - 16 / 32768) < 1e-6              # the file's samples now answer queries
            finally:
                instance.close()
            node.set("path", os.path.join(folder, "gone.wav"))
            engine.update()
            engine.action(node.id, "open")
            assert "file not found" in engine.node_message(node.id)
            for call in (lambda: engine.action(999, "open"), lambda: engine.node_message(999)):
                try:
                    call()
                except GraphError as error:
                    assert "no node 999" in str(error)
                else:
                    raise AssertionError("an unknown node must raise GraphError")
            engine.action(out.id, "anything")                                              # a node type without an action handler ignores it
    finally:
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)


def test_py_collect_reports_how_many_compiled_graphs_are_still_held():
    graph, nodes = graph_with_boundaries()
    with Engine(graph) as engine:
        assert engine.collect() == 1
        graph.add("boundary_outlet", name="z")
        engine.update()
        assert engine.collect() == 1                                                       # no instance holds the first graph: it is freed at once


def test_py_text_that_does_not_fit_the_first_buffer_is_asked_for_again_with_a_big_enough_one():
    graph, nodes = graph_with_boundaries()
    with Engine(graph) as engine:
        calls = []

        def stub(*args):                                                                   # the way the C functions copy text: cut to the capacity, NUL-ended, full length given
            buffer, capacity, length = args[-3:]
            text = ("é" * 400 + "x").encode("utf-8")                                        # 801 bytes
            calls.append(capacity)
            length._obj.value = len(text)
            chunk = text[:max(0, capacity - 1)]
            ctypes.memmove(buffer, chunk + b"\0", len(chunk) + 1)
            return 0
        status, text = engine._text(stub, "first", "second")
        assert status == 0 and text == "é" * 400 + "x" and calls == [256, 802]            # one retry, with room for the NUL
        calls.clear()

        def exact(*args):
            buffer, capacity, length = args[-3:]
            text = b"a" * 255                                                               # fits a buffer of 256 exactly (with the NUL)
            calls.append(capacity)
            length._obj.value = len(text)
            ctypes.memmove(buffer, text + b"\0", 256)
            return 0
        assert engine._text(exact) == (0, "a" * 255) and calls == [256]
        calls.clear()

        def just_too_long(*args):                                                           # 256 bytes need a buffer of 257: the cut text is not accepted
            buffer, capacity, length = args[-3:]
            text = b"b" * 256
            calls.append(capacity)
            length._obj.value = len(text)
            chunk = text[:max(0, capacity - 1)]
            ctypes.memmove(buffer, chunk + b"\0", len(chunk) + 1)
            return 0
        assert engine._text(just_too_long) == (0, "b" * 256) and calls == [256, 257]
        assert engine._text(lambda *args: 11) == (11, "")                                    # a failing status comes back as it is


# ---------------------------------------------------------------- audio devices and the preview node

def test_py_the_audio_backend_is_chosen_by_name_and_the_null_backend_has_one_device():
    graph, nodes = graph_with_boundaries()
    with Engine(graph) as engine:
        engine.set_audio_backend("null")
        assert engine.audio_devices() == ["NULL Playback Device"]
        engine.set_audio_backend("system")                                                 # (the machine's own: whatever it has, as a list of names)
        names = engine.audio_devices()
        assert isinstance(names, list) and all(isinstance(n, str) and n and "\n" not in n for n in names)
        engine.set_audio_backend("null")
        for bad in ("Null", "", None, 1):
            try:
                engine.set_audio_backend(bad)
            except ValueError as error:
                assert "'system' or 'null'" in str(error)
            else:
                raise AssertionError(f"{bad!r} must be refused")


def test_py_the_device_names_come_back_one_to_a_line_as_a_list():
    graph, nodes = graph_with_boundaries()
    with Engine(graph) as engine:
        engine._text = lambda function, *args: (0, "Speakers (Realtek)\nHeadset\nHDMI Output")
        assert engine.audio_devices() == ["Speakers (Realtek)", "Headset", "HDMI Output"]
        engine._text = lambda function, *args: (0, "One device")
        assert engine.audio_devices() == ["One device"]
        engine._text = lambda function, *args: (0, "")
        assert engine.audio_devices() == []
        engine._text = lambda function, *args: (9, "")                                       # a failing status is an error, not an empty list
        try:
            engine.audio_devices()
        except RuntimeError:
            pass
        else:
            raise AssertionError("a failing status must raise")


def test_py_a_preview_node_plays_pauses_and_is_moved_in_time_through_the_engine():
    graph = Graph()
    preview = graph.add("realtime_preview")
    with Engine(graph) as engine:
        engine.set_audio_backend("null")
        assert engine.preview_state(preview.id) == (False, 0)
        engine.action(preview.id, "play")
        assert engine.preview_state(preview.id)[0] is True
        assert wait_until(lambda: engine.preview_state(preview.id)[1] > 100 * MS)           # the time moves while it plays (the null device runs in real time)
        engine.action(preview.id, "pause")
        playing, paused_at = engine.preview_state(preview.id)
        assert playing is False
        time.sleep(0.15)
        assert engine.preview_state(preview.id) == (False, paused_at)                      # and stands still while paused
        engine.preview_set_time(preview.id, 62_500 * MS)
        assert engine.preview_state(preview.id) == (False, 62_500 * MS)                    # a whole number of milliseconds is exact
        engine.preview_set_time(preview.id, -5 * MS)
        assert engine.preview_state(preview.id) == (False, -5 * MS)
        assert engine.node_message(preview.id) == ""
        for call in (lambda: engine.preview_state(999), lambda: engine.preview_set_time(999, 0), lambda: engine.preview_warning(999)):
            try:
                call()
            except GraphError as error:
                assert "no node 999" in str(error)
            else:
                raise AssertionError("an unknown node must raise GraphError")
        other = graph.add("boundary_outlet", name="y")
        engine.update()
        for call in (lambda: engine.preview_state(other.id), lambda: engine.preview_set_time(other.id, 0), lambda: engine.preview_warning(other.id)):
            try:
                call()
            except GraphError as error:
                assert f"node {other.id} cannot do that" in str(error)
            else:
                raise AssertionError("a node that is not a preview must raise GraphError")
        try:
            engine.preview_set_time(preview.id, 1.5)
        except ValueError:
            pass
        else:
            raise AssertionError("a time is whole nanoseconds")


def test_py_a_preview_warning_names_the_nodes_that_feed_it_and_are_not_realtime_safe_and_a_missing_device_is_said_by_the_node():
    slow = e.PyNodeType("vendor.slow", inlets=[("in", 0.0)], outlets=["out"], at=lambda ctx, outlet, t: 0.0)
    safe = e.PyNodeType("vendor.safe", inlets=[("in", 0.0)], outlets=["out"], flags=d.FLAG_REALTIME_SAFE, at=lambda ctx, outlet, t: 0.0)
    rig = e.Rig(slow, safe)
    try:
        graph = Graph(types=canopysynth.NodeTypes.from_registry(rig.registry, e.lib))
        preview = graph.add("realtime_preview")
        slow_node, safe_node = graph.add("vendor.slow"), graph.add("vendor.safe")
        graph.connect(safe_node.outlet("out"), preview.inlet("left"))
        with Engine(graph, registry=rig.registry) as engine:
            engine.set_audio_backend("null")
            assert engine.preview_warning(preview.id) == ""                                # only realtime safe nodes feed it
            graph.connect(slow_node.outlet("out"), preview.inlet("right"))
            engine.update()
            warning = engine.preview_warning(preview.id)
            assert "not realtime safe" in warning and "vendor.slow" in warning and str(slow_node.id) in warning and "vendor.safe" not in warning
            preview.set("device", "No such audio device")                                   # a device no machine has: the system default plays, and the node says so
            engine.update()
            engine.action(preview.id, "device")
            engine.action(preview.id, "play")
            assert engine.preview_state(preview.id)[0] is True
            assert "audio device not found: No such audio device" in engine.node_message(preview.id)
    finally:
        rig.close()


def test_py_closing_an_engine_stops_its_preview_device_and_later_calls_say_it_is_closed():
    graph = Graph()
    preview = graph.add("realtime_preview")
    engine = Engine(graph)
    engine.set_audio_backend("null")
    engine.action(preview.id, "play")
    assert engine in graph.engines()
    engine.close()
    assert engine.closed and graph.engines() == []
    for call in (lambda: engine.preview_state(preview.id), lambda: engine.set_knob(preview.id, "left", 0.0), lambda: engine.collect(),
                 lambda: engine.audio_devices(), lambda: engine.action(preview.id, "pause")):
        try:
            call()
        except RuntimeError as error:
            assert "closed" in str(error)
        else:
            raise AssertionError("a closed engine must raise RuntimeError")


def test_py_a_graph_knows_its_open_engines_only_and_does_not_keep_them_alive():
    import gc
    graph, _nodes = graph_with_boundaries()
    assert graph.engines() == []
    first, second = Engine(graph), Engine(graph)
    assert len(graph.engines()) == 2 and first in graph.engines() and second in graph.engines()
    first.close()
    assert graph.engines() == [second]
    del second
    gc.collect()
    assert graph.engines() == []                                                          # a dropped engine is gone from the list (it frees itself)
    try:
        Engine(graph, registry=0)
    except Exception:                                                                       # noqa: BLE001 - whatever a bad registry raises: nothing is registered
        pass
    assert graph.engines() == []


def test_py_a_node_id_that_is_not_a_whole_number_in_64_bits_or_an_action_that_is_not_text_is_a_graph_error_and_presses_no_button():
    """Found by the API fuzz of step 13 (tests/python/test_api_fuzz.py): the calls added at step 12 passed their arguments straight to ctypes, so a node ID
    that was not an int was a ctypes.ArgumentError, an action that was not text was an AttributeError, and a node ID beyond 64 bits was cut to its low
    64 bits (ctypes does not check) and pressed the button of whichever node had that number."""
    graph = Graph()
    preview = graph.add("realtime_preview")
    with Engine(graph) as engine:
        engine.set_audio_backend("null")
        calls = {"action": lambda node_id: engine.action(node_id, "play"), "node_message": engine.node_message, "preview_state": engine.preview_state,
                 "preview_set_time": lambda node_id: engine.preview_set_time(node_id, 5 * MS), "preview_warning": engine.preview_warning}
        wrapped = [preview.id + 2 ** 64, preview.id - 2 ** 64, 2 ** 63, -2 ** 63 - 1, 10 ** 40]
        for name, call in calls.items():
            for bad in ("1", None, 1.0, True, [1], b"1", object(), preview.id + 0.0, *wrapped):
                try:
                    call(bad)
                except GraphError as error:
                    assert "node ID" in str(error) and "64 bits" in str(error), (name, bad, str(error))
                else:
                    raise AssertionError(f"{name}({bad!r}) must raise GraphError")
        assert engine.preview_state(preview.id) == (False, 0)                              # no refused call played it, or moved its time
        for bad in (None, 5, 1.5, True, b"play", ["play"], "pl\0ay", "\ud800", object()):
            try:
                engine.action(preview.id, bad)
            except GraphError as error:
                assert "the name of an action" in str(error), (bad, str(error))
            else:
                raise AssertionError(f"an action {bad!r} must raise GraphError")
        assert engine.preview_state(preview.id) == (False, 0)
        engine.action(preview.id, "play")                                                  # the good call still works...
        assert wait_until(lambda: engine.preview_state(preview.id)[0])
        engine.action(preview.id, "nonsense")                                              # ...and a name the node does not know is still ignored
        engine.action(preview.id, "pause")
    for call in (lambda: engine.action("not an id", 5), lambda: engine.node_message(None), lambda: engine.preview_state([]),
                 lambda: engine.preview_set_time(None, None), lambda: engine.preview_warning(2 ** 70)):
        try:
            call()
        except RuntimeError as error:                                                       # a closed engine is reported first, whatever else is wrong
            assert "closed" in str(error)
        else:
            raise AssertionError("a closed engine must raise RuntimeError")
