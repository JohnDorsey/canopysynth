"""Tests (plan step 13): determinism through the public Python API (design section 5: the same graph, knobs, boundary values, settings and files give the same
floats every time). The recorded outputs themselves are in tests/c/test_determinism.c, a table of hashes that the three C test programs check; this file asks the
Python API the same questions of the same data and compares what it answers with the hash in that table, so the bridge (ctypes, the memoryview of a span, the
Graph model and its settings) is shown to give the C engine's bits and nothing else. Then the properties, through Graph, Engine and Instance: a copy of the graph
saved with to_dict and loaded again, another engine, an update of an unchanged or an unrelated-changed graph, and instances in other threads all answer alike."""
import os
import re
import struct
import tempfile
import threading

from canopysynth import Engine, Graph
from test_fileread import write_wav

FNV_START = 0xCBF29CE484222325
MASK = (1 << 64) - 1
C_TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "c", "test_determinism.c")
FILE_CASE = "a 16-bit stereo file at 44.1 kHz"

# The shapes of tests/c/test_determinism.c, in its order: (point, t0, t1, n).
SHAPES = [
    (False, 0, 1_000_000_000, 4800),
    (False, -250_000_000, 750_000_000, 960),
    (False, 1_000_000_000, 0, 1000),
    (False, 123_456_789, 123_456_789, 10),
    (False, 0, 1_500_000_000, 65536),
    (False, 2_500_000_000, 2_500_100_000, 7),
    (True, 777_777_777, 0, 1),
    (True, -42_000_000, 0, 1),
    (False, 3_000_000_000, 3_000_100_000, 480),
]


def fnv1a(data, state=FNV_START):
    for byte in data:
        state = ((state ^ byte) * 0x100000001B3) & MASK
    return state


def write_case_file(path):
    """The file of the C test: 16-bit stereo at 44100 Hz, 16317 frames of two integer formulas."""
    data = b"".join(struct.pack("<hh", (k * 37) % 65536 - 32768, ((k * k) % 1000 - 500) * 60) for k in range(16317))
    write_wav(path, 1, 16, 2, 44100, data)


def file_graph(path):
    graph = Graph()
    song = graph.add("file_read", path=path)
    left = graph.add("boundary_outlet", name="l")
    right = graph.add("boundary_outlet", name="r")
    graph.connect(song.outlet("left"), left.inlet("in"))
    graph.connect(song.outlet("right"), right.inlet("in"))
    return graph


def ask(instance, outlet, shape):
    """The bytes of one query's floats."""
    point, t0, t1, n = shape
    if point:
        return struct.pack("<f", instance.value(outlet, t0))
    return bytes(instance.audio(outlet, t0, t1, n))


def case_hash(instance):
    """The hash the C test makes of the case: FNV-1a of the little-endian 64-bit hashes of every query, outlet by outlet, shape by shape."""
    hashes = [fnv1a(ask(instance, outlet, shape)) for outlet in ("l", "r") for shape in SHAPES]
    return fnv1a(b"".join(struct.pack("<Q", h) for h in hashes))


def recorded_in_c(case):
    text = open(C_TEST, encoding="utf-8").read()
    found = re.search(r'\{"' + re.escape(case) + r'", build_\w+, (?:NULL|after_\w+), \{[^}]*\}, 0x([0-9a-f]{16})ULL\}', text)
    assert found, f"the table of tests/c/test_determinism.c has no case {case!r}"
    return int(found.group(1), 16)


def test_py_the_public_api_answers_the_bits_the_c_test_recorded_for_the_file_graph():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "determinism.wav")
        write_case_file(path)
        with Engine(file_graph(path)) as engine, engine.new_instance() as instance:
            got = case_hash(instance)
    want = recorded_in_c(FILE_CASE)
    assert got == want, (f"through Graph, Engine and Instance the file graph hashes to 0x{got:016x}, the table of tests/c/test_determinism.c records 0x{want:016x} "
                         "(the shapes of this file must be those of that one)")


def test_py_a_saved_and_reloaded_copy_another_engine_an_update_and_other_threads_all_answer_alike():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "determinism.wav")
        write_case_file(path)
        graph = file_graph(path)
        with Engine(graph) as engine, engine.new_instance() as instance:
            first = case_hash(instance)
            assert case_hash(instance) == first                                             # asked again
            with engine.new_instance() as cold:                                             # a cold instance, asked in the opposite order
                backwards = {(o, i): ask(cold, o, shape) for o in ("r", "l") for i, shape in reversed(list(enumerate(SHAPES)))}
                forwards = {(o, i): ask(instance, o, shape) for o in ("l", "r") for i, shape in enumerate(SHAPES)}
                assert backwards == forwards
            copy = Graph.from_dict(graph.to_dict(), base_dir=None)                          # saved, loaded again, in another engine
            with Engine(copy) as other, other.new_instance() as in_other:
                assert case_hash(in_other) == first
            graph.add("boundary_inlet", name="unrelated")                                   # an unrelated node, installed in this engine
            engine.update()
            assert case_hash(instance) == first
            engine.update()                                                                 # the same graph again
            assert case_hash(instance) == first
            results, problems = [], []

            def work():
                try:
                    with engine.new_instance() as mine:
                        results.append(case_hash(mine))
                except Exception as error:                                                  # noqa: BLE001 - reported below
                    problems.append(error)

            threads = [threading.Thread(target=work) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            assert not problems, problems
            assert results == [first] * 3
