# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the Python bridge (plan step 9, design sections 15 and 16): the section 15 snippet as written, against the model of a generated WAV file;
compile faults and updates; the boundary list and writes; every error of a query; instances in several threads; and the lifetime of engines
and instances (nothing leaks, in any order of closing or dropping)."""
import ctypes
import gc
import struct
import tempfile
import threading

import canopysynth
import engine_dll as e
import graph_dll
from canopysynth import BoundaryError, Engine, Graph, GraphError, NodeTypes, QueryError
from canopysynth import _descriptor as d
from engine_dll import PyNodeType, Rig, float32 as f32
from test_fileread import Wav, span_times

INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1
ERR_OVERFLOW, ERR_N, ERR_ARGUMENT, ERR_BUSY = 2, 3, 13, 14


def bits(value):
    return struct.pack("<f", value)


def refuses(function, kind, *fragments):
    """`function` must raise `kind` whose message holds every fragment; returns the exception."""
    try:
        function()
    except kind as error:
        for fragment in fragments:
            assert fragment in str(error), (fragment, str(error))
        return error
    raise AssertionError(f"expected {kind.__name__}, none was raised")


def pair_graph(in_name="x", out_name="y"):
    graph = Graph()
    level = graph.add("boundary_inlet", name=in_name)
    result = graph.add("boundary_outlet", name=out_name)
    graph.connect(level.outlet("out"), result.inlet("in"))
    return graph


def snippet_graph(path):
    """The graph of the design's section 15 snippet, plus a boundary inlet that is read back by a boundary outlet."""
    graph = canopysynth.Graph()
    song = graph.add("file_read", path=path)
    left = graph.add("boundary_outlet", name="song_left")
    right = graph.add("boundary_outlet", name="song_right")
    level = graph.add("boundary_inlet", name="intensity")
    echo = graph.add("boundary_outlet", name="intensity_out")
    graph.connect(song.outlet("left"), left.inlet("in"))
    graph.connect(song.outlet("right"), right.inlet("in"))
    graph.connect(level.outlet("out"), echo.inlet("in"))
    graph.loop_protection = True
    return graph


# ---------------------------------------------------------------- the design's snippet

def test_py_the_section_15_snippet_runs_as_written_and_audio_is_the_files_model():
    with tempfile.TemporaryDirectory() as directory:
        wav = Wav(directory, "song.wav", "int", 16, 2, 44100, 2000, seed=5)
        graph = snippet_graph(wav.path)
        engine = canopysynth.Engine(graph)                              # keeps the latest compiled graph
        listed = [(b.name, b.kind) for b in engine.boundary_nodes()]    # BoundaryInfo(name, kind, node_id)
        assert listed == [("intensity", "inlet"), ("intensity_out", "outlet"), ("song_left", "outlet"), ("song_right", "outlet")]
        engine.set_boundary("intensity", 0.7)                           # any thread
        inst = engine.new_instance()                                    # one per querying thread
        assert bits(inst.value("intensity_out", 12345)) == bits(f32(0.7))
        for t in (0, 1, 22_675, 1_000_000, 22_675_736, 44_000_000, 45_300_000, -5, 10 ** 12):          # point queries: the model of the file node
            for name, channel in (("song_left", 0), ("song_right", 1)):
                assert bits(inst.value(name, t)) == bits(f32(wav.value(channel, t))), (name, t)
        for t0, t1, n in ((0, 45_000_000, 100), (-10_000_000, 60_000_000, 1000), (30_000_000, 5_000_000, 64), (7, 7, 5), (0, 1_000_000_000, 65536),
                          (3, 4, 1), (0, 45_351_474, 2000)):
            audio = inst.audio("song_left", t0, t1, n)                  # span queries: n float32
            assert isinstance(audio, memoryview) and audio.format == "f" and audio.itemsize == 4 and len(audio) == n and not audio.readonly
            want = [f32(wav.value(0, t)) for t in span_times(t0, t1, n)]
            assert [bits(v) for v in audio] == [bits(v) for v in want], (t0, t1, n)
        n = canopysynth.ns_to_frame(45_000_000, 48000) - canopysynth.ns_to_frame(0, 48000)
        frame, frac = canopysynth.ns_to_frame_fraction(7_000_000, 44100)
        assert n == 2160 and frame == 308 and 0 <= frac < 1
        assert len(inst.audio("song_right", 0, 45_000_000, n)) == 2160
        d = graph.to_dict()                                             # the host stores this in its own project file
        assert canopysynth.Graph.from_dict(d, base_dir=None).to_dict() == d
        inst.close()
        engine.close()


def test_py_times_beyond_32_bits_reach_the_node_intact_for_point_and_span_queries():
    with tempfile.TemporaryDirectory() as directory:
        wav = Wav(directory, "long.wav", "int", 16, 1, 8000, 48000, seed=9)                  # six seconds: 6 000 000 000 ns
        graph = Graph()
        song = graph.add("file_read", path=wav.path)
        out = graph.add("boundary_outlet", name="song")
        graph.connect(song.outlet("left"), out.inlet("in"))
        with Engine(graph) as engine, engine.new_instance() as inst:
            for t in (4_294_967_295, 4_294_967_296, 4_500_000_000, 5_999_875_000, 2_147_483_648, 3_000_000_001):
                assert bits(inst.value("song", t)) == bits(f32(wav.value(0, t))) and wav.value(0, t) != 0.0, t
            for t0, t1, n in ((4_400_000_000, 4_500_000_000, 50), (5_000_000_000, 4_294_967_000, 40), (2_147_483_000, 2_148_000_000, 33)):
                got = inst.audio("song", t0, t1, n)
                assert [bits(v) for v in got] == [bits(f32(wav.value(0, t))) for t in span_times(t0, t1, n)], (t0, t1, n)


def test_py_a_memoryview_of_a_span_is_a_buffer_other_code_can_wrap_and_each_call_gets_its_own():
    with Engine(pair_graph()) as engine, engine.new_instance() as inst:
        engine.set_boundary("x", 0.25)
        first = inst.audio("y", 0, 100, 8)
        engine.set_boundary("x", -0.5)
        second = inst.audio("y", 0, 100, 8)
        assert list(first) == [0.25] * 8 and list(second) == [-0.5] * 8                   # the first is not overwritten by the second
        assert struct.unpack("<8f", bytes(first)) == (0.25,) * 8                           # the bytes are plain little-endian float32
        assert first.tolist() == [0.25] * 8 and first.nbytes == 32 and first.contiguous
        first[0] = 9.0                                                                     # a writable buffer: the caller owns it
        assert first[0] == 9.0 and second[0] == -0.5


# ---------------------------------------------------------------- compiling and updating

def test_py_a_graph_that_cannot_be_compiled_raises_graph_error_with_the_engines_reason_and_leaks_nothing():
    base = e.alloc_live()
    graph = Graph()
    graph.add("boundary_inlet", name="x")
    graph.add("boundary_outlet", name="x")
    problem = refuses(lambda: Engine(graph), BoundaryError, '"x"', "node 1", "node 2", "unique")
    try:
        graph.validate()
    except BoundaryError as error:
        assert str(problem) == str(error)                                # the model's validate says it in the engine's words
    graph = Graph()
    graph.add("boundary_inlet")
    refuses(lambda: Engine(graph), BoundaryError, "node 1", "needs a name")
    catalog = graph_dll.make_catalog()                                   # a type this engine's registry (the built-in types) does not have
    foreign = Graph(types=catalog)
    foreign.add("py.versioned")
    refuses(lambda: Engine(foreign), GraphError, "node 1", "py.versioned", "unknown node type")
    assert e.alloc_live() == base                                        # the engine, its registry and the half-made description are freed


def test_py_update_swaps_in_the_edited_graph_and_a_failed_update_keeps_the_old_one_running():
    graph = pair_graph()
    knob = graph.add("boundary_outlet", name="from_knob")
    knob.set_knob("in", 0.25)
    with Engine(graph) as engine, engine.new_instance() as inst:
        engine.set_boundary("x", 0.75)
        assert inst.value("from_knob", 0) == 0.25 and inst.value("y", 0) == 0.75
        knob.set_knob("in", -0.5)
        assert inst.value("from_knob", 0) == 0.25                        # nothing happens until update()
        engine.update()
        assert inst.value("from_knob", 0) == -0.5
        assert inst.value("y", 0) == 0.75                                # the boundary value survived: it belongs to the node
        extra = graph.add("boundary_outlet", name="y")                   # a repeated name: the engine refuses
        problem = refuses(engine.update, BoundaryError, '"y"', "unique")
        assert str(problem) == str(refuses(graph.validate, BoundaryError))
        assert inst.value("y", 0) == 0.75 and inst.value("from_knob", 0) == -0.5          # the old graph is still what runs
        assert [b.name for b in engine.boundary_nodes()] == ["from_knob", "x", "y"] and len(engine.boundary_nodes()) == 3
        extra.set("name", "z")
        engine.update()
        assert [b.name for b in engine.boundary_nodes()] == ["from_knob", "x", "y", "z"]
        graph.remove(graph.node(2))                                      # the outlet "y" goes: a read of it is now a fault
        engine.update()
        refuses(lambda: inst.value("y", 0), BoundaryError, "'y'")
        engine.set_boundary("x", 0.5)                                    # "x" is still there, with its value kept


def test_py_a_graph_with_no_nodes_is_a_graph_and_everything_asked_of_it_names_a_missing_boundary():
    with Engine(Graph()) as engine, engine.new_instance() as inst:
        assert engine.boundary_nodes() == []
        refuses(lambda: engine.set_boundary("x", 1.0), BoundaryError, "'x'")
        refuses(lambda: inst.value("x", 0), BoundaryError, "'x'")
        refuses(lambda: inst.audio("x", 0, 10, 4), BoundaryError, "'x'")


def test_py_every_setting_kind_and_knob_reaches_the_node_as_the_model_holds_it_and_a_choice_goes_by_index():
    seen = []

    def at(ctx, outlet, t):
        seen.append((e.ctx_int(ctx, 0), e.ctx_float(ctx, 1), e.ctx_string(ctx, 2), e.ctx_string(ctx, 3), e.ctx_int(ctx, 4), e.ctx_int(ctx, 5)))
        return e.ctx_inlet_at(ctx, 0, t)

    probe = PyNodeType("py.probe", inlets=[("a", 0.25)], outlets=["out"],
                       settings=[("count", "int", 7), ("gain", "float", 1.5), ("label", "string", "hi"), ("wav", "path", ""),
                                 ("mode", "choice", 1, ["sine", "square", "saw"])], flags=d.FLAG_HAS_INTERNAL_RATE, at=at)
    rig = Rig(probe)
    catalog = NodeTypes.from_registry(rig.registry, e.lib)
    graph = Graph(types=catalog)
    node = graph.add("py.probe")
    out = graph.add("boundary_outlet", name="out")
    graph.connect(node.outlet("out"), out.inlet("in"))
    with Engine(graph, registry=rig.registry) as engine, engine.new_instance() as inst:
        assert inst.value("out", 0) == 0.25                              # the type's default knob
        assert seen[-1] == (7, 1.5, b"hi", b"", 1, 48000)                # and its default settings, the choice as index 1
        node.set("count", INT64_MIN)
        node.set("gain", -2.5e-300)
        node.set("label", "h\u00e9llo \u4e2d\U0001f600")
        node.set("wav", "C:\\audio\\\u00e9.wav")
        node.set("mode", "saw")
        node.set("internal_sampling_rate", 384000)
        node.set_knob("a", -0.375)
        engine.update()
        assert inst.value("out", 0) == -0.375
        assert seen[-1] == (INT64_MIN, -2.5e-300, "h\u00e9llo \u4e2d\U0001f600".encode("utf-8"), "C:\\audio\\\u00e9.wav".encode("utf-8"), 2, 384000)
        node.set("mode", "sine")
        node.set("count", INT64_MAX)
        engine.update()
        inst.value("out", 0)
        assert seen[-1][0] == INT64_MAX and seen[-1][4] == 0
    rig.close()


def test_py_the_engine_works_with_a_registry_the_caller_made_and_leaves_it_alone():
    seen = []
    twice = PyNodeType("py.twice", inlets=[("in", 0.0)], outlets=["out"], at=lambda ctx, outlet, t: f32(e.ctx_inlet_at(ctx, 0, t) * 2.0))
    rig = Rig(twice)
    catalog = NodeTypes.from_registry(rig.registry, e.lib)
    graph = Graph(types=catalog)
    source, middle, sink = graph.add("boundary_inlet", name="x"), graph.add("py.twice"), graph.add("boundary_outlet", name="y")
    graph.connect(source.outlet("out"), middle.inlet("in"))
    graph.connect(middle.outlet("out"), sink.inlet("in"))
    for _ in range(2):                                                   # twice: the registry is still valid after the first engine is gone
        with Engine(graph, registry=rig.registry) as engine, engine.new_instance() as inst:
            engine.set_boundary("x", 0.375)
            assert inst.value("y", 5) == 0.75
            assert list(inst.audio("y", 0, 50, 5)) == [0.75] * 5
            seen.append(1)
    assert seen == [1, 1]
    rig.close()


# ---------------------------------------------------------------- boundary writes and the list

def test_py_boundary_nodes_lists_what_the_model_lists_including_long_and_unusual_names():
    graph = Graph()
    names = ["b", "B", "\u00e9\u4e2d\U0001f600", "a" * 300, "a" * 255, "a" * 256, "with space and \"quotes\" \\", "\U00010000", "\uffff"]
    for i, name in enumerate(names):
        graph.add("boundary_inlet" if i % 2 else "boundary_outlet", name=name)
    with Engine(graph) as engine:
        listed = engine.boundary_nodes()
        assert listed == graph.boundary_nodes() and len(listed) == len(names)
        assert all(isinstance(b, canopysynth.BoundaryInfo) for b in listed)
        assert sorted(names, key=lambda s: s.encode("utf-8")) == [b.name for b in listed]


def test_py_node_ids_beyond_32_bits_reach_the_engine_whole():
    big = [2 ** 40, -2 ** 40, 2 ** 62 + 5, INT64_MAX, INT64_MIN]
    data = {"format": "canopysynth-graph", "version": 1, "loop_protection": True, "connections": [],
            "nodes": [{"id": i, "type": "boundary_inlet" if n % 2 else "boundary_outlet", "type_version": 1, "x": 0, "y": 0,
                       "settings": {"name": f"n{n}"}, "knobs": {}} for n, i in enumerate(big)]}
    graph = Graph.from_dict(data)
    with Engine(graph) as engine:
        assert sorted((b.name, b.node_id) for b in engine.boundary_nodes()) == sorted((f"n{n}", i) for n, i in enumerate(big))


def test_py_set_boundary_takes_any_float_and_refuses_what_is_not_a_boundary_inlet_by_name():
    with Engine(pair_graph()) as engine, engine.new_instance() as inst:
        for value in (0.0, -0.0, 1.0e30, -1.0e30, 2.5, 7, -3, 1.0e-40, float("inf"), float("-inf")):
            engine.set_boundary("x", value)
            assert bits(inst.value("y", 0)) == bits(f32(value)), value
        engine.set_boundary("x", float("nan"))
        assert inst.value("y", 0) != inst.value("y", 0)                  # NaN comes out as NaN
        engine.set_boundary("x", 1e300)                                  # too big for a float32: it becomes infinity, as the C call does
        assert inst.value("y", 0) == float("inf")
        refuses(lambda: engine.set_boundary("nope", 1.0), BoundaryError, "'nope'")
        refuses(lambda: engine.set_boundary("X", 1.0), BoundaryError, "'X'")                                   # names are case-sensitive
        refuses(lambda: engine.set_boundary("x ", 1.0), BoundaryError, "'x '")
        refuses(lambda: engine.set_boundary("y", 1.0), BoundaryError, "'y'", "boundary outlet", "not a boundary inlet")
        refuses(lambda: engine.set_boundary("x\0junk", 1.0), BoundaryError, "no boundary node")              # a NUL must not cut the name short
        refuses(lambda: engine.set_boundary("", 1.0), BoundaryError, "''")
        refuses(lambda: engine.set_boundary("\ud800", 1.0), BoundaryError, "not valid text")
        refuses(lambda: engine.set_boundary(None, 1.0), BoundaryError, "text")
        refuses(lambda: engine.set_boundary(b"x", 1.0), BoundaryError, "text")
        for bad in ("0.5", None, True, [1.0]):
            refuses(lambda: engine.set_boundary("x", bad), TypeError, "number")
        refuses(lambda: engine.set_boundary("x", 10 ** 400), ValueError, "float")
        engine.set_boundary("x", 0.5)                                    # and after all the refusals it still works
        assert inst.value("y", 0) == 0.5


# ---------------------------------------------------------------- queries and their errors

def test_py_a_query_of_a_missing_or_wrong_kind_of_boundary_name_raises_boundary_error_naming_it():
    with Engine(pair_graph()) as engine, engine.new_instance() as inst:
        refuses(lambda: inst.value("nope", 0), BoundaryError, "'nope'")
        refuses(lambda: inst.audio("nope", 0, 10, 4), BoundaryError, "'nope'")
        refuses(lambda: inst.value("x", 0), BoundaryError, "'x'", "boundary inlet", "not a boundary outlet")
        refuses(lambda: inst.audio("x", 0, 10, 4), BoundaryError, "'x'", "boundary inlet")
        refuses(lambda: inst.value("y\0", 0), BoundaryError, "no boundary node")
        refuses(lambda: inst.audio("\ud800", 0, 10, 4), BoundaryError, "not valid text")
        refuses(lambda: inst.value(5, 0), BoundaryError, "text")


def test_py_times_must_be_64_bit_integers_and_n_a_whole_number_and_a_bad_n_is_a_query_error_without_allocating():
    with Engine(pair_graph()) as engine, engine.new_instance() as inst:
        for bad in (1.0, "0", None, True, 2 ** 63, -2 ** 63 - 1, 10 ** 30):
            refuses(lambda: inst.value("y", bad), ValueError, "t_ns")
            refuses(lambda: inst.audio("y", bad, 10, 4), ValueError, "t0_ns")
            refuses(lambda: inst.audio("y", 0, bad, 4), ValueError, "t1_ns")
        for bad in (4.0, "4", None, True):
            refuses(lambda: inst.audio("y", 0, 10, bad), ValueError, "n")
        for bad in (0, -1, -2 ** 62, 65537, 10 ** 12, 2 ** 40):          # (10 ** 12 floats would be 4 TB: it must be refused before any allocation)
            error = refuses(lambda: inst.audio("y", 0, 10, bad), QueryError, "span query", "y")
            assert error.status == ERR_N
        assert len(inst.audio("y", 0, 10, 65536)) == 65536 and len(inst.audio("y", 0, 10, 1)) == 1
        error = refuses(lambda: inst.audio("y", INT64_MIN, INT64_MAX, 4), QueryError, "span query")      # t1 - t0 does not fit in 64 bits
        assert error.status == ERR_OVERFLOW
        assert len(inst.audio("y", INT64_MIN + 1, 0, 4)) == 4 and len(inst.audio("y", 0, INT64_MAX, 4)) == 4      # (INT64_MIN to 0 is 2 ** 63 long: too much)
        assert refuses(lambda: inst.audio("y", INT64_MIN, 0, 4), QueryError).status == ERR_OVERFLOW
        assert inst.value("y", INT64_MIN) == 0.0 and inst.value("y", INT64_MAX) == 0.0


def test_py_a_node_that_fails_in_a_span_query_raises_query_error_with_its_status_and_so_does_a_point_query():
    fail = PyNodeType("py.fail", inlets=[("in", 0.0)], outlets=["out"], span=lambda ctx, outlet, t0, t1, n, out: ERR_ARGUMENT)
    rig = Rig(fail)
    graph = Graph(types=NodeTypes.from_registry(rig.registry, e.lib))
    node, sink = graph.add("py.fail"), graph.add("boundary_outlet", name="y")
    graph.connect(node.outlet("out"), sink.inlet("in"))
    with Engine(graph, registry=rig.registry) as engine, engine.new_instance() as inst:
        error = refuses(lambda: inst.audio("y", 0, 100, 10), QueryError)
        assert error.status == ERR_ARGUMENT and isinstance(error, Exception) and not isinstance(error, GraphError)
        error = refuses(lambda: inst.value("y", 0), QueryError)           # a point query reports it too (the span handler answers it for a span-only node)
        assert error.status == ERR_ARGUMENT and "point query" in str(error)
    rig.close()


def test_py_a_node_whose_point_handler_fails_makes_both_kinds_of_query_raise_query_error_with_its_status():
    calls = []

    def at(ctx, outlet, t):
        calls.append(t)
        return (42, 5.0) if t >= 100 else 0.25            # the answer 5.0 must not get out when the status is nonzero

    pointwise = PyNodeType("py.pointwise", inlets=[("in", 0.0)], outlets=["out"], at=at)       # point handler only: spans are derived from it
    rig = Rig(pointwise)
    graph = Graph(types=NodeTypes.from_registry(rig.registry, e.lib))
    node, sink = graph.add("py.pointwise"), graph.add("boundary_outlet", name="y")
    graph.connect(node.outlet("out"), sink.inlet("in"))
    with Engine(graph, registry=rig.registry) as engine, engine.new_instance() as inst:
        assert inst.value("y", 99) == 0.25
        error = refuses(lambda: inst.value("y", 100), QueryError, "point query")
        assert error.status == 42
        assert list(inst.audio("y", 0, 90, 9)) == [0.25] * 9
        del calls[:]
        error = refuses(lambda: inst.audio("y", 0, 200, 20), QueryError, "span query")      # the sample at t = 100 fails: the whole span does
        assert error.status == 42 and calls == list(range(0, 110, 10))        # and nothing after it was asked
    rig.close()


def test_py_an_instance_used_twice_at_once_raises_query_error_busy_in_a_call_from_inside_a_node_and_from_another_thread():
    state = {"status": None, "out": None, "entered": threading.Event(), "release": threading.Event(), "block": False, "pointer": None}

    def at(ctx, outlet, t):
        if state["block"]:
            state["entered"].set()
            state["release"].wait(30)
            return 0.5
        state["status"], state["out"] = e.instance_read_at_status(state["pointer"], b"y", 0)
        return 0.25

    middle = PyNodeType("py.middle", inlets=[("in", 0.0)], outlets=["out"], at=at)
    rig = Rig(middle)
    graph = Graph(types=NodeTypes.from_registry(rig.registry, e.lib))
    node, sink = graph.add("py.middle"), graph.add("boundary_outlet", name="y")
    graph.connect(node.outlet("out"), sink.inlet("in"))
    with Engine(graph, registry=rig.registry) as engine, engine.new_instance() as inst:
        state["pointer"] = inst._pointer
        assert inst.value("y", 0) == 0.25                                # a call from inside the node's own handler is refused...
        assert state["status"] == ERR_BUSY and state["out"] == 0.0       # ...with the status, and a zero
        state["block"] = True
        results = []
        worker = threading.Thread(target=lambda: results.append(inst.value("y", 0)))
        worker.start()
        assert state["entered"].wait(30)
        error = refuses(lambda: inst.value("y", 0), QueryError, "in use")
        assert error.status == ERR_BUSY
        error = refuses(lambda: inst.audio("y", 0, 10, 4), QueryError, "in use")
        assert error.status == ERR_BUSY
        state["release"].set()
        worker.join(30)
        assert results == [0.5] and not worker.is_alive()
        state["block"] = False
        assert inst.value("y", 0) == 0.25                                # and the instance is usable again
    rig.close()


# ---------------------------------------------------------------- threads

def test_py_one_instance_per_thread_read_while_boundary_values_are_written_and_the_graph_is_updated():
    graph = pair_graph()
    knob = graph.add("boundary_outlet", name="from_knob")
    knob.set_knob("in", 0.25)
    allowed = [0.0, 0.125, -0.5, 0.75, 1.5, -2.0]
    allowed_knob = {0.25, -0.25}
    problems, counters, stop = [], [0, 0, 0], threading.Event()

    def reader(index, engine):
        try:
            with engine.new_instance() as inst:
                while not stop.is_set():
                    assert inst.value("y", index) in allowed
                    span = inst.audio("y", 0, 1600, 16)
                    assert all(v in allowed for v in span)
                    assert inst.value("from_knob", 0) in allowed_knob
                    counters[index] += 1
        except BaseException as error:                                   # noqa: BLE001
            problems.append(repr(error))
            stop.set()

    def writer(engine):
        try:
            for i in range(3000):
                engine.set_boundary("x", allowed[i % len(allowed)])
        except BaseException as error:                                   # noqa: BLE001
            problems.append(repr(error))

    def wait_until(condition):
        for _ in range(3000):
            if condition() or problems:
                return
            threading.Event().wait(0.01)
        problems.append("a thread made no progress")

    with Engine(graph) as engine:
        threads = [threading.Thread(target=reader, args=(i, engine)) for i in range(3)]
        for t in threads:
            t.start()
        wait_until(lambda: min(counters) >= 20)
        w = threading.Thread(target=writer, args=(engine,))
        w.start()
        for i in range(60):
            knob.set_knob("in", -0.25 if i % 2 == 0 else 0.25)
            engine.update()
        w.join(60)
        before = list(counters)
        wait_until(lambda: all(c >= b + 20 for c, b in zip(counters, before)))
        stop.set()
        for t in threads:
            t.join(60)
        assert not problems, problems
        assert min(counters) >= 40 and not any(t.is_alive() for t in threads)


# ---------------------------------------------------------------- lifetimes

def test_py_closing_the_engine_with_an_open_instance_is_refused_and_everything_can_be_closed_twice():
    base = e.alloc_live()
    engine = Engine(pair_graph())
    inst = engine.new_instance()
    other = engine.new_instance()
    refuses(engine.close, RuntimeError, "2 open instance")
    engine.set_boundary("x", 0.5)                                        # nothing was freed: it all still works
    assert inst.value("y", 0) == 0.5 and other.value("y", 0) == 0.5
    inst.close()
    refuses(engine.close, RuntimeError, "1 open instance")
    inst.close()                                                         # twice is fine and does not count twice
    refuses(engine.close, RuntimeError, "1 open instance")
    other.close()
    engine.close()
    engine.close()
    assert e.alloc_live() == base
    refuses(lambda: inst.value("y", 0), RuntimeError, "closed")
    refuses(lambda: inst.audio("y", 0, 10, 4), RuntimeError, "closed")
    refuses(lambda: engine.set_boundary("x", 1.0), RuntimeError, "closed")
    refuses(engine.boundary_nodes, RuntimeError, "closed")
    refuses(engine.update, RuntimeError, "closed")
    refuses(engine.new_instance, RuntimeError, "closed")


def test_py_when_the_python_instance_object_cannot_be_built_new_instance_is_a_memory_error_and_leaves_no_instance_behind():
    """Found by the real out-of-memory test (test_shutdown.py), which failed one run in five: `new_instance` made the instance in C, counted it, and only then built the Python
    object, so a MemoryError there lost the pointer for good (the engine then refused to close, "1 open instance"). Memory that has really run out cannot be had in a
    test that has to be exact, so the failure is put in at the place where it matters: the object cannot be built."""
    from canopysynth import engine as engine_module
    base = e.alloc_live()
    engine = Engine(pair_graph())
    real = engine_module.Instance

    class Unbuildable:
        def __init__(self, *arguments):
            raise MemoryError("the Instance object could not be built")

    engine_module.Instance = Unbuildable
    try:
        refuses(engine.new_instance, MemoryError, "could not be built")
    finally:
        engine_module.Instance = real
    engine.close()                                                       # no instance is open (nothing was left in C): this must not be refused
    assert e.alloc_live() == base
    engine = Engine(pair_graph())                                        # and the ordinary path still counts, answers and frees
    inst = engine.new_instance()
    engine.set_boundary("x", 0.25)
    assert inst.value("y", 0) == 0.25
    refuses(engine.close, RuntimeError, "1 open instance")
    inst.close()
    engine.close()
    assert e.alloc_live() == base


def test_py_new_instance_takes_the_instance_from_a_slot_made_before_the_call_and_never_turns_the_pointer_into_a_number():
    """The last way left to lose an instance was ctypes turning the pointer that `canopy_engine_new_instance` returns into a Python int: a small allocation, and when it
    failed the instance was alive in C with nobody to free it (the real out-of-memory test, one run in fifty or so). The engine now calls `canopy_engine_new_instance_into`
    with a ctypes slot (and its `byref`) made BEFORE the call, and keeps the slot itself as the instance's handle: no number is made after the call. The slot is
    written here the way the C function writes it, and what the engine does with it is followed to the call that frees the instance."""
    base = e.alloc_live()
    with Engine(pair_graph()) as engine:
        real = engine._lib
        calls, freed = [], []

        def into(handle, reference):
            calls.append((handle, reference))
            reference._obj.value = 0x1234                                # what canopy_engine_new_instance_into does with its out parameter
            return 0

        engine._lib = Faulty(real, canopy_engine_new_instance_into=into, canopy_instance_free=freed.append)
        inst = engine.new_instance()
        assert len(calls) == 1 and calls[0][0] == engine._handle()
        assert isinstance(inst._pointer, ctypes.c_void_p) and inst._pointer.value == 0x1234, inst._pointer     # the slot, not a number
        refuses(engine.close, RuntimeError, "1 open instance")           # it is counted
        inst.close()
        assert len(freed) == 1 and freed[0] is calls[0][1]._obj, freed      # the very slot the C function wrote is what frees the instance
        inst.close()                                                     # twice is fine
        assert len(freed) == 1
        for status, kind in ((e.ERR_MEMORY, MemoryError), (e.ERR_ARGUMENT, RuntimeError)):
            engine._lib = Faulty(real, canopy_engine_new_instance_into=lambda *a, status=status: status)
            refuses(engine.new_instance, kind)
        engine._lib = real                                               # neither failure was counted: the engine closes with nothing open
    assert e.alloc_live() == base


def test_py_an_instance_keeps_its_engine_alive_and_dropping_things_without_closing_frees_them_all():
    base = e.alloc_live()
    engine = Engine(pair_graph())
    inst = engine.new_instance()
    engine.set_boundary("x", 0.5)
    del engine
    gc.collect()
    assert inst.value("y", 0) == 0.5                                     # the engine is still there: the instance holds it
    assert e.alloc_live() > base
    del inst
    gc.collect()
    assert e.alloc_live() == base                                        # the instance, then the engine, then its registry were freed
    for _ in range(3):                                                   # and in a loop, with the engine dropped first and the instance later
        engine = Engine(pair_graph())
        first, second = engine.new_instance(), engine.new_instance()
        engine = None
        del second
        gc.collect()
        assert first.value("y", 0) == 0.0
        first = None
        gc.collect()
    assert e.alloc_live() == base


def test_py_a_failed_start_and_context_managers_leave_nothing_behind():
    base = e.alloc_live()
    bad = Graph()
    bad.add("boundary_inlet")
    for _ in range(3):
        refuses(lambda: Engine(bad), BoundaryError, "needs a name")
    with Engine(pair_graph()) as engine:
        with engine.new_instance() as inst:
            assert inst.value("y", 0) == 0.0
        refuses(lambda: inst.value("y", 0), RuntimeError, "closed")
    refuses(engine.update, RuntimeError, "closed")
    assert e.alloc_live() == base


def test_py_the_package_exports_the_design_names_and_the_instance_reads_from_threads_that_did_not_make_it():
    assert canopysynth.Engine is Engine and canopysynth.QueryError is QueryError and issubclass(QueryError, Exception)
    assert not issubclass(QueryError, GraphError) and not issubclass(GraphError, QueryError)
    assert canopysynth.BoundaryError is BoundaryError and issubclass(BoundaryError, Exception)
    assert not issubclass(BoundaryError, GraphError) and not issubclass(GraphError, BoundaryError) and not issubclass(BoundaryError, QueryError)
    with Engine(pair_graph()) as engine, engine.new_instance() as inst:      # made in this thread, used in another (one at a time is all C asks)
        engine.set_boundary("x", 0.375)
        results = []
        worker = threading.Thread(target=lambda: results.append(inst.value("y", 1)))
        worker.start()
        worker.join(30)
        assert results == [0.375]


# ---------------------------------------------------------------- statuses the C engine reports and the tests cannot provoke for real

class Faulty:
    """The real DLL object, except that the named functions are replaced: `Faulty(real, canopy_engine_new_instance=lambda *a: None)`."""

    def __init__(self, real, **replaced):
        self._real, self._replaced = real, replaced

    def __getattr__(self, name):
        return self._replaced[name] if name in self._replaced else getattr(self._real, name)


def with_faulty(engine, **replaced):
    """Makes `engine` use a Faulty DLL object; returns the real one to put back."""
    real = engine._lib
    engine._lib = Faulty(real, **replaced)
    return real


def test_py_memory_running_out_in_the_engine_is_a_memory_error_and_nothing_is_left_over():
    from canopysynth import _native
    base = e.alloc_live()
    graph = pair_graph()
    graph.add("boundary_outlet", name="z")
    with Engine(graph) as engine:
        real = engine._lib
        for name, answer in (("canopy_graph_new", lambda: None), ("canopy_graph_add_node", lambda *a: e.ERR_MEMORY),
                             ("canopy_graph_set_string", lambda *a: e.ERR_MEMORY), ("canopy_graph_set_knob", lambda *a: e.ERR_MEMORY),
                             ("canopy_graph_connect", lambda *a: e.ERR_MEMORY), ("canopy_engine_set_graph", lambda *a: e.ERR_MEMORY)):
            engine._lib = Faulty(real, **{name: answer})
            refuses(engine.update, MemoryError, "out of memory")
            engine._lib = real
            engine.update()                                              # and the engine is as it was: the next update works
        engine._lib = Faulty(real, canopy_engine_new_instance_into=lambda *a: e.ERR_MEMORY)
        refuses(engine.new_instance, MemoryError, "instance")
        engine._lib = real
        with engine.new_instance() as inst:                              # (the failed one did not count: the engine can still be closed after this)
            assert inst.value("y", 0) == 0.0
    assert e.alloc_live() == base
    for name in ("canopy_registry_new", "canopy_engine_new"):            # at the start: what was made is freed
        real_dll = _native.dll()
        _native._dll = Faulty(real_dll, **{name: lambda *a: None})
        try:
            refuses(lambda: Engine(pair_graph()), MemoryError)
        finally:
            _native._dll = real_dll
    assert e.alloc_live() == base


def test_py_other_statuses_of_the_engine_become_graph_errors_with_the_engines_sentences():
    graph = pair_graph()
    with Engine(graph) as engine:
        real = with_faulty(engine, canopy_engine_set_graph=lambda *a: e.ERR_GRAPH, canopy_engine_last_error=lambda *a: None)
        refuses(engine.update, GraphError, "graph")                      # no reason given: the sentence of the status
        engine._lib = Faulty(real, canopy_engine_set_graph=lambda *a: e.ERR_ARGUMENT)
        refuses(engine.update, GraphError)
        engine._lib = Faulty(real, canopy_graph_connect=lambda *a: e.ERR_ARGUMENT)           # (a failure the engine would not notice: the graph just lacks it)
        refuses(engine.update, GraphError, canopysynth._native.message(e.ERR_ARGUMENT))
        engine._lib = Faulty(real, canopy_engine_set_boundary=lambda *a: e.ERR_ARGUMENT)
        refuses(lambda: engine.set_boundary("x", 1.0), BoundaryError)
        engine._lib = Faulty(real, canopy_engine_boundary_at=lambda *a: e.ERR_ARGUMENT)
        refuses(engine.boundary_nodes, BoundaryError)
        engine._lib = real
        engine.update()
        assert [b.name for b in engine.boundary_nodes()] == ["x", "y"]


def test_py_a_boundary_list_that_changes_while_it_is_read_is_read_again_and_one_that_never_settles_is_an_error():
    with Engine(pair_graph()) as engine:
        real = engine._lib
        calls = []

        def stale_once(handle, index, *rest):
            calls.append(index)
            return e.ERR_INDEX if len(calls) == 1 else real.canopy_engine_boundary_at(handle, index, *rest)

        engine._lib = Faulty(real, canopy_engine_boundary_at=stale_once)
        assert [b.name for b in engine.boundary_nodes()] == ["x", "y"] and calls == [0, 0, 1]
        engine._lib = Faulty(real, canopy_engine_boundary_at=lambda *a: e.ERR_INDEX)
        refuses(engine.boundary_nodes, BoundaryError, "kept changing")
        engine._lib = real


def test_py_closing_an_engine_the_c_side_says_is_busy_is_a_runtime_error_that_keeps_it_open():
    engine = Engine(pair_graph())
    real = with_faulty(engine, canopy_engine_free=lambda *a: e.ERR_BUSY)
    refuses(engine.close, RuntimeError, "in use")
    engine._lib = real
    engine.set_boundary("x", 0.5)                                        # still open and working
    engine.close()
