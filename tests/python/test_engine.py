"""Tests: the engine seen from Python through ctypes, with node types written in Python (tests only: version 1 has no Python tier).
These give the C engine independent references: Python big integers for where the samples of a span are, a plain recursive evaluation of
whole random graphs, the list of exported functions in the headers, and a thread test of the knob table."""
import ctypes
import os
import random
import re
import struct
import threading
import time

import engine_dll as e
from engine_dll import PyNodeType, Rig, ERRORS, float32, span_buffer, lib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def bits(value):
    return struct.pack("<f", value)


def test_py_every_function_the_headers_declare_as_exported_is_exported_by_the_dll():
    names = set()
    for header in ("canopy.h", "canopy_node.h", "canopy_engine.h"):
        with open(os.path.join(ROOT, "src", header), encoding="utf-8") as handle:
            names |= set(re.findall(r"CANOPY_API\s+[^;{}()]*?\b(canopy_\w+)\s*\(", handle.read()))
    assert len(names) >= 44, sorted(names)                  # (44 when this was written: the regex must not silently stop matching)
    missing = [name for name in sorted(names) if not hasattr(lib, name)]
    assert not missing, missing


# ---- where the samples of a span are, against Python big integers ----

def reference_times(t0, t1, n):
    d = t1 - t0
    return [t0 + (i * d) // n for i in range(n)]


def recorder_rig():
    log = []

    def record(ctx, outlet, t):
        log.append(t)
        return 0.5

    rig = Rig(PyNodeType("py.recorder", at=record), PyNodeType("py.sink", inlets=[("in0", 0.0), ("in1", 0.5)], outlets=[]))
    rig.node(1, "py.recorder")
    rig.node(2, "py.sink")
    rig.connect(1, "out", 2, "in0")
    rig.install()
    return rig, log


def query_recorder(rig, log, t0, t1, n):
    out = span_buffer(n)
    for i in range(n):
        out[i] = -1.0
    del log[:]
    status = e.instance_inlet_span(rig.instance, 2, 0, t0, t1, n, out)
    return status, list(log), list(out)


def random_span(rng):
    """(t0, t1) whose difference fits in an int64: small, huge, or at the very limits."""
    style = rng.randrange(5)
    if style == 0:
        return rng.randint(-1000, 1000), rng.randint(-1000, 1000)
    if style == 1:
        return rng.randint(-2 ** 40, 2 ** 40), rng.randint(-2 ** 40, 2 ** 40)
    d = rng.randint(-2 ** 63, 2 ** 63 - 1) if style == 2 else rng.choice([e.INT64_MAX, e.INT64_MIN, e.INT64_MAX - 1, e.INT64_MIN + 1, 0, 1, -1])
    low, high = max(e.INT64_MIN, e.INT64_MIN - d), min(e.INT64_MAX, e.INT64_MAX - d)       # t0 must keep t0 + d inside the int64 range
    t0 = rng.choice([low, high, rng.randint(low, high)])
    return t0, t0 + d


def test_py_the_samples_of_a_span_are_where_big_integer_arithmetic_puts_them():
    rig, log = recorder_rig()
    rng = random.Random(20261002)
    cases = [(0, 100, 4), (100, 0, 4), (5, 5, 7), (0, e.INT64_MAX, 3), (e.INT64_MAX, 0, 3), (0, e.INT64_MIN, 5), (e.INT64_MIN + 1, 0, 4),
             (-1, e.INT64_MAX - 1, 1), (e.INT64_MIN, -1, 2), (-1, e.INT64_MIN, 6)]
    cases += [random_span(rng) + (rng.choice([1, 2, 3, 7, 64, 255, 1000]),) for _ in range(400)]
    for t0, t1, n in cases:
        status, seen, out = query_recorder(rig, log, t0, t1, n)
        assert status == e.OK, (t0, t1, n, status)
        assert seen == reference_times(t0, t1, n), (t0, t1, n)
        assert out == [0.5] * n
        assert all(e.INT64_MIN <= t <= e.INT64_MAX for t in seen)
    for t0, t1 in ((0, e.INT64_MAX), (e.INT64_MAX, 0), (-12345, 2 ** 40), (7, 7)):          # the largest n, with its 65536 callbacks
        status, seen, out = query_recorder(rig, log, t0, t1, e.MAX_N)
        assert status == e.OK and seen == reference_times(t0, t1, e.MAX_N), (t0, t1)
    rig.close()


def test_py_a_span_whose_length_overflows_or_whose_n_is_bad_is_refused_before_any_node_is_asked():
    rig, log = recorder_rig()
    overflowing = [(-2, e.INT64_MAX), (e.INT64_MIN, 1), (e.INT64_MAX, -2), (e.INT64_MIN, e.INT64_MAX), (1, e.INT64_MIN), (e.INT64_MAX, e.INT64_MIN)]
    for t0, t1 in overflowing:
        assert not (e.INT64_MIN <= t1 - t0 <= e.INT64_MAX)           # (these really are too long: Python integers do not overflow)
        status, seen, out = query_recorder(rig, log, t0, t1, 6)
        assert status == e.ERR_OVERFLOW and seen == [] and out == [0.0] * 6, (t0, t1)
    for n in (0, -1, e.MAX_N + 1, 10 ** 9, e.INT64_MIN, e.INT64_MAX):
        out = span_buffer(4)
        for i in range(4):
            out[i] = -1.0
        assert e.instance_inlet_span(rig.instance, 2, 0, 0, 100, n, out) == e.ERR_N
        assert list(out) == [-1.0] * 4 and log == []       # the buffer's size is unknown, so it is left alone
    rig.close()


# ---- whole random graphs against a plain recursive evaluation ----

def make_types():
    def const_at(ctx, outlet, t):
        return e.ctx_float(ctx, 0)

    def time_at(ctx, outlet, t):
        return float(t) if outlet == 0 else 2.0 * float(t)

    def gain_at(ctx, outlet, t):
        return e.ctx_inlet_at(ctx, 0, t) * e.ctx_inlet_at(ctx, 1, t)

    def gain_span(ctx, outlet, t0, t1, n, out):
        scratch = e.ctx_scratch(ctx, n)
        if not scratch:
            return e.ERR_MEMORY
        status = e.ctx_inlet_span(ctx, 0, t0, t1, n, out)
        if status:
            return status
        status = e.ctx_inlet_span(ctx, 1, t0, t1, n, scratch)
        if status:
            return status
        for i in range(n):
            out[i] = out[i] * scratch[i]
        return e.OK

    def sum_at(ctx, outlet, t):
        return e.ctx_inlet_at(ctx, 0, t) + e.ctx_inlet_at(ctx, 1, t)

    def shift_at(ctx, outlet, t):
        return e.ctx_inlet_at(ctx, 0, t + e.ctx_int(ctx, 0))

    def shift_span(ctx, outlet, t0, t1, n, out):
        shift = e.ctx_int(ctx, 0)
        return e.ctx_inlet_span(ctx, 0, t0 + shift, t1 + shift, n, out)

    return [
        PyNodeType("py.const", settings=[("value", "float", 0.0)], at=const_at),
        PyNodeType("py.time", outlets=["a", "b"], at=time_at),
        PyNodeType("py.gain", inlets=[("in", 0.0), ("gain", 1.0)], at=gain_at, span=gain_span, scratch=1),
        PyNodeType("py.sum", inlets=[("a", 0.0), ("b", 0.0)], at=sum_at),
        PyNodeType("py.shift", inlets=[("in", 0.0)], settings=[("shift", "int", 0)], at=shift_at, span=shift_span),
        PyNodeType("py.sink", inlets=[("in0", 0.0), ("in1", 0.25), ("in2", -0.75)], outlets=[]),
    ]


INLETS = {"const": [], "time": [], "gain": [("in", 0.0), ("gain", 1.0)], "sum": [("a", 0.0), ("b", 0.0)], "shift": [("in", 0.0)],
          "sink": [("in0", 0.0), ("in1", 0.25), ("in2", -0.75)]}
OUTLETS = {"const": ["out"], "time": ["a", "b"], "gain": ["out"], "sum": ["out"], "shift": ["out"]}


def random_model(rng):
    """Nodes in dependency order; each inlet is connected to an earlier node's outlet or left to its knob."""
    nodes = []
    for index in range(rng.randint(3, 9)):
        kind = rng.choice(["const", "time", "gain", "sum", "shift"])
        node = {"id": rng.choice([index + 1, index + 1, -index - 1, 1000 + index]), "kind": kind, "value": float32(rng.uniform(-3, 3)),
                "shift": rng.randint(-300, 300), "inlets": [], "knobs": []}
        for key, default in INLETS[kind]:
            source = None
            if index and rng.random() < 0.7:
                source = rng.randrange(index)
                source = (source, rng.randrange(len(OUTLETS[nodes[source]["kind"]])))
            node["inlets"].append(source)
            node["knobs"].append(float32(rng.uniform(-1, 1)) if rng.random() < 0.6 else float32(default))
        nodes.append(node)
    sink = {"id": 77777, "kind": "sink", "inlets": [], "knobs": []}
    for key, default in INLETS["sink"]:
        source = None
        if rng.random() < 0.85:
            source = rng.randrange(len(nodes))
            source = (source, rng.randrange(len(OUTLETS[nodes[source]["kind"]])))
        sink["inlets"].append(source)
        sink["knobs"].append(float32(rng.uniform(-1, 1)) if rng.random() < 0.6 else float32(default))
    nodes.append(sink)
    return nodes


def ref_inlet(nodes, node, inlet, t):
    source = node["inlets"][inlet]
    if source is None:
        return node["knobs"][inlet]
    return ref_outlet(nodes, nodes[source[0]], source[1], t)


def ref_outlet(nodes, node, outlet, t):
    kind = node["kind"]
    if kind == "const":
        return float32(node["value"])
    if kind == "time":
        return float32(float(t)) if outlet == 0 else float32(2.0 * float32(float(t)))
    if kind == "gain":
        return float32(ref_inlet(nodes, node, 0, t) * ref_inlet(nodes, node, 1, t))
    if kind == "sum":
        return float32(ref_inlet(nodes, node, 0, t) + ref_inlet(nodes, node, 1, t))
    return ref_inlet(nodes, node, 0, t + node["shift"])                       # shift


def build(rig, nodes):
    for node in nodes:
        rig.node(node["id"], "py." + node["kind"])
    for node in nodes:
        keys = [k for k, _ in INLETS[node["kind"]]]
        for inlet, source in enumerate(node["inlets"]):
            if source is not None:
                src = nodes[source[0]]
                rig.connect(src["id"], OUTLETS[src["kind"]][source[1]], node["id"], keys[inlet])
        for inlet, knob in enumerate(node["knobs"]):
            assert e.graph_set_knob(rig.graph, node["id"], keys[inlet].encode(), knob) == e.OK
        if node["kind"] == "const":
            assert e.graph_set_float(rig.graph, node["id"], b"value", node["value"]) == e.OK
        if node["kind"] == "shift":
            assert e.graph_set_int(rig.graph, node["id"], b"shift", node["shift"]) == e.OK


def test_py_random_graphs_answer_bit_for_bit_what_a_plain_recursive_evaluation_says():
    rng = random.Random(4242)
    types = make_types()
    for _ in range(80):
        nodes = random_model(rng)
        rig = Rig(*types)
        build(rig, nodes)
        rig.install()
        sink = nodes[-1]
        for _query in range(6):
            inlet = rng.randrange(3)
            t = rng.randint(-3000, 3000)
            got = e.instance_inlet_at(rig.instance, sink["id"], inlet, t)
            assert bits(got) == bits(ref_inlet(nodes, sink, inlet, t)), (inlet, t, nodes)
            t0, t1 = rng.randint(-3000, 3000), rng.randint(-3000, 3000)
            if rng.random() < 0.15:
                t1 = t0
            n = rng.randint(1, 25)
            out = span_buffer(n)
            assert e.instance_inlet_span(rig.instance, sink["id"], inlet, t0, t1, n, out) == e.OK
            expected = [ref_inlet(nodes, sink, inlet, t_i) for t_i in reference_times(t0, t1, n)]
            assert [bits(v) for v in out] == [bits(v) for v in expected], (inlet, t0, t1, n, nodes)
        rig.close()


def test_py_knob_moves_change_the_answers_of_random_graphs_exactly_as_the_reference_does():
    rng = random.Random(99)
    types = make_types()
    for _ in range(30):
        nodes = random_model(rng)
        rig = Rig(*types)
        build(rig, nodes)
        rig.install()
        for _move in range(5):
            node = rng.choice(nodes)
            keys = INLETS[node["kind"]]
            if not keys:
                continue
            inlet = rng.randrange(len(keys))
            value = float32(rng.uniform(-1, 1))
            assert e.engine_set_knob(rig.engine, node["id"], inlet, value) == e.OK
            node["knobs"][inlet] = value
            sink = nodes[-1]
            for sink_inlet in range(3):
                t = rng.randint(-500, 500)
                assert bits(e.instance_inlet_at(rig.instance, sink["id"], sink_inlet, t)) == bits(ref_inlet(nodes, sink, sink_inlet, t))
        rig.close()


# ---- settings as the typed getters see them, from the other side of ctypes ----

def test_py_a_node_reads_every_kind_of_setting_through_the_typed_getters():
    seen = {}

    def read(ctx, outlet, t):
        seen["int"], seen["float"] = e.ctx_int(ctx, 0), e.ctx_float(ctx, 1)
        seen["string"], seen["path"], seen["choice"] = e.ctx_string(ctx, 2), e.ctx_string(ctx, 3), e.ctx_int(ctx, 4)
        seen["rate"] = e.ctx_int(ctx, 5)
        seen["float_as_int"], seen["int_as_string"], seen["bad"] = e.ctx_int(ctx, 1), e.ctx_string(ctx, 0), (e.ctx_int(ctx, 9), e.ctx_string(ctx, -1))
        return 1.0

    settings = PyNodeType("py.settings", settings=[("count", "int", 7), ("ratio", "float", 1.5), ("label", "string", "abc"), ("file", "path", ""),
                                                    ("mode", "choice", 1, ["low", "mid", "high"])], at=read, flags=2)
    sink = PyNodeType("py.sink", inlets=[("in0", 0.0)], outlets=[])
    rig = Rig(settings, sink)
    rig.node(1, "py.settings")
    rig.node(2, "py.sink")
    rig.connect(1, "out", 2, "in0")
    e.graph_set_int(rig.graph, 1, b"count", -5)
    e.graph_set_float(rig.graph, 1, b"ratio", 0.125)
    e.graph_set_string(rig.graph, 1, b"label", "naïve label".encode("utf-8"))
    e.graph_set_string(rig.graph, 1, b"file", b"C:/audio/song.wav")
    e.graph_set_int(rig.graph, 1, b"mode", 2)
    e.graph_set_int(rig.graph, 1, b"internal_sampling_rate", 44100)
    rig.install()
    assert e.instance_inlet_at(rig.instance, 2, 0, 0) == 1.0
    assert seen == {"int": -5, "float": 0.125, "string": "naïve label".encode("utf-8"), "path": b"C:/audio/song.wav", "choice": 2, "rate": 44100,
                    "float_as_int": 0, "int_as_string": b"", "bad": (0, b"")}
    rig.close()


# ---- the knob table from several threads ----

def test_py_knob_writes_from_one_thread_are_seen_whole_by_readers_in_other_threads():
    sink = PyNodeType("py.sink", inlets=[("in0", 0.0)], outlets=[])
    rig = Rig(sink)
    rig.node(1, "py.sink")
    rig.install()
    allowed = {0.0, float32(0.3), float32(-0.7)}            # the starting position and the two values that are written
    problems, reads = [], [0] * 3
    stop = threading.Event()

    def reader(slot):
        instance = e.engine_new_instance(rig.engine)        # one instance per thread
        try:
            while not stop.is_set():
                for _ in range(500):
                    value = e.instance_inlet_at(instance, 1, 0, 0)
                    if value not in allowed:
                        problems.append(value)
                reads[slot] += 500
        finally:
            e.instance_free(instance)

    threads = [threading.Thread(target=reader, args=(slot,)) for slot in range(3)]
    for thread in threads:
        thread.start()
    writes, deadline = 0, time.time() + 20
    while (writes < 4000 or min(reads) < 2000) and time.time() < deadline:        # write until every reader has really been reading
        assert e.engine_set_knob(rig.engine, 1, 0, 0.3 if writes % 2 == 0 else -0.7) == e.OK
        writes += 1
    stop.set()
    for thread in threads:
        thread.join()
    assert not problems, problems[:5]
    assert min(reads) >= 2000, reads
    value, generation = ctypes.c_float(), ctypes.c_uint64()
    assert e.engine_get_knob(rig.engine, 1, 0, ctypes.byref(value), ctypes.byref(generation)) == e.OK
    assert generation.value == writes and value.value == float32(0.3 if (writes - 1) % 2 == 0 else -0.7)
    rig.close()
