"""Tests: the boundary nodes through ctypes (what the Python bridge of plan step 9 will call): writing by name, reading a point or a span, the
listing, the compile faults, and a writer thread against readers. The C tests (tests/c/test_boundary.c) check the details; here the exact
floats are compared with an independent model, including a graph with a node in between."""
import ctypes
import math
import struct
import threading
import time

import engine_dll as e
from engine_dll import PyNodeType, Rig, float32 as f32, span_buffer


def bits(value):
    return struct.pack("<f", value)


def gain_type():
    """out(t) = in(t) * 2 + 0.25, in float32: a node between the boundary nodes, written in Python."""
    return PyNodeType("py.affine", inlets=[("in", 0.0)],
                      at=lambda ctx, outlet, t: f32(f32(e.ctx_inlet_at(ctx, 0, t) * 2.0) + 0.25))


def affine_rig(in_name=b"level", out_name=b"result"):
    rig = Rig(gain_type())
    rig.node(1, "boundary_inlet")
    rig.node(2, "py.affine")
    rig.node(3, "boundary_outlet")
    rig.connect(1, "out", 2, "in")
    rig.connect(2, "out", 3, "in")
    assert e.graph_set_string(rig.graph, 1, b"name", in_name) == e.OK
    assert e.graph_set_string(rig.graph, 3, b"name", out_name) == e.OK
    rig.install()
    return rig


def test_py_a_value_written_by_name_comes_out_of_the_graph_exactly_as_a_plain_model_says_for_points_and_spans():
    rig = affine_rig()
    for value in (0.0, 0.7, -0.3, 1.0e30, -1.0e30, 2.5, 1.0e-40, -0.0, math.inf, -math.inf):
        assert e.engine_set_boundary(rig.engine, b"level", value) == e.OK
        want = f32(f32(f32(value) * 2.0) + 0.25)
        got = e.instance_read_at(rig.instance, b"result", 123456789)
        assert bits(got) == bits(want), (value, got, want)
        out = span_buffer(33)
        assert e.instance_read_span(rig.instance, b"result", -50, 5000, 33, out) == e.OK
        assert all(bits(v) == bits(got) for v in out)
    assert e.engine_set_boundary(rig.engine, b"level", float("nan")) == e.OK
    assert math.isnan(e.instance_read_at(rig.instance, b"result", 0))
    rig.close()


def test_py_unknown_names_the_wrong_kind_and_null_arguments_give_the_documented_statuses():
    rig = affine_rig()
    assert e.engine_set_boundary(rig.engine, b"nope", 1.0) == e.ERR_NODE
    assert e.engine_set_boundary(rig.engine, b"result", 1.0) == e.ERR_NODE            # an outlet cannot be written
    assert e.engine_set_boundary(rig.engine, None, 1.0) == e.ERR_ARGUMENT
    assert e.engine_set_boundary(None, b"level", 1.0) == e.ERR_ARGUMENT
    assert e.engine_set_boundary(rig.engine, b"level", 0.5) == e.OK
    assert e.instance_read_at(rig.instance, b"level", 0) == 0.0                         # an inlet cannot be read, whatever it holds
    out = span_buffer(16)
    for name, status in ((b"nope", e.ERR_NODE), (b"level", e.ERR_NODE), (None, e.ERR_ARGUMENT)):
        for i in range(16):
            out[i] = 99.0
        assert e.instance_read_span(rig.instance, name, 0, 16, 16, out) == status
        assert all(v == 0.0 for v in out)                                               # a failure zero-fills
    assert e.instance_read_span(rig.instance, b"result", 0, 16, 0, out) == e.ERR_N
    assert e.instance_read_span(rig.instance, b"result", -2, e.INT64_MAX, 16, out) == e.ERR_OVERFLOW
    rig.close()


def test_py_the_listing_is_sorted_by_name_and_reports_kind_and_node_id_with_a_cut_name_when_the_buffer_is_small():
    rig = Rig()
    for node_id, key, name in ((5, "boundary_inlet", b"zeta"), (9, "boundary_inlet", b"alpha"), (2, "boundary_outlet", b"Mid")):
        rig.node(node_id, key)
        assert e.graph_set_string(rig.graph, node_id, b"name", name) == e.OK
    rig.install()
    assert e.engine_boundary_count(rig.engine) == 3
    found = []
    for index in range(3):
        buffer, length, kind, node_id = ctypes.create_string_buffer(32), e.i32(), e.i32(), e.i64()
        assert e.engine_boundary_at(rig.engine, index, buffer, 32, ctypes.byref(length), ctypes.byref(kind), ctypes.byref(node_id)) == e.OK
        found.append((buffer.value, length.value, kind.value, node_id.value))
    assert found == [(b"Mid", 3, e.BOUNDARY_OUTLET, 2), (b"alpha", 5, e.BOUNDARY_INLET, 9), (b"zeta", 4, e.BOUNDARY_INLET, 5)]
    small, length = ctypes.create_string_buffer(3), e.i32()
    assert e.engine_boundary_at(rig.engine, 1, small, 3, ctypes.byref(length), None, None) == e.OK
    assert small.value == b"al" and length.value == 5
    assert e.engine_boundary_at(rig.engine, 3, None, 0, None, None, None) == e.ERR_INDEX
    rig.close()


def test_py_an_empty_or_repeated_boundary_name_is_refused_with_a_message_and_the_old_graph_keeps_running():
    rig = affine_rig()
    assert e.engine_set_boundary(rig.engine, b"level", 0.5) == e.OK
    bad = e.graph_new()
    for node_id, key, name in ((1, "boundary_inlet", b"dup"), (2, "boundary_outlet", b"dup")):
        assert e.graph_add_node(bad, node_id, key.encode()) == e.OK
        assert e.graph_set_string(bad, node_id, b"name", name) == e.OK
    assert e.engine_set_graph(rig.engine, bad) == e.ERR_GRAPH
    message = e.engine_last_error(rig.engine)
    assert b"dup" in message and b"node 1" in message and b"node 2" in message
    assert e.graph_add_node(bad, 3, b"boundary_inlet") == e.OK                          # no name at all
    assert e.graph_set_string(bad, 1, b"name", b"fine") == e.OK
    assert e.engine_set_graph(rig.engine, bad) == e.ERR_GRAPH
    assert b"node 3" in e.engine_last_error(rig.engine) and b"needs a name" in e.engine_last_error(rig.engine)
    assert e.instance_read_at(rig.instance, b"result", 0) == f32(f32(0.5 * 2.0) + 0.25)
    e.graph_free(bad)
    rig.close()


def test_py_a_writer_thread_against_reader_threads_every_value_read_was_written_and_never_goes_back():
    rig = Rig()
    rig.node(1, "boundary_inlet")
    rig.node(2, "boundary_outlet")
    rig.connect(1, "out", 2, "in")
    assert e.graph_set_string(rig.graph, 1, b"name", b"in") == e.OK
    assert e.graph_set_string(rig.graph, 2, b"name", b"out") == e.OK
    rig.install()
    stop, problems, reads = threading.Event(), [], [0, 0, 0]

    def reader(slot):
        instance = e.engine_new_instance(rig.engine)
        last = 0.0
        out = span_buffer(8)
        try:
            while not stop.is_set():
                now = e.instance_read_at(instance, b"out", 0)
                if now < last:
                    problems.append(("went back", slot, last, now))
                if e.instance_read_span(instance, b"out", 0, 80, 8, out) != e.OK:
                    problems.append(("status", slot))
                if len(set(out)) != 1 or out[0] < now:
                    problems.append(("torn or older", slot, list(out), now))
                last = max(last, out[0])
                reads[slot] += 1
        finally:
            e.instance_free(instance)

    threads = [threading.Thread(target=reader, args=(slot,)) for slot in range(3)]
    for thread in threads:
        thread.start()
    deadline = time.time() + 30
    try:
        for value in range(1, 2001):
            assert e.engine_set_boundary(rig.engine, b"in", float(value)) == e.OK
            if value % 40 == 0:
                before = list(reads)
                while any(r <= b for r, b in zip(reads, before)) and time.time() < deadline:
                    time.sleep(0.0002)
    finally:                                                                     # whatever happens, the readers must stop
        stop.set()
        for thread in threads:
            thread.join()
    assert not problems, problems[:3]
    assert min(reads) > 0
    assert e.instance_read_at(rig.instance, b"out", 0) == 2000.0
    rig.close()
