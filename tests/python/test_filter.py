# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the hidden test filter of the DLL (a one-pole low-pass with unbounded memory and checkpoints, src/canopy_test_nodes.c) through ctypes,
against an independent model written here in Python: exact integer arithmetic for the grid times and the position between two samples,
float32 arithmetic emulated step by step. It checks that answers never depend on how the filter was asked (start points, densities,
earlier queries, other threads), that edits made through the engine are followed exactly, and that unrelated installs do not disturb it."""
import random
import struct
import threading
import time

import engine_dll as e
from engine_dll import PyNodeType, Rig, float32 as f32, span_buffer

PERIOD = 250_000_000


def saw(t):
    return f32((t % PERIOD) * (2.0 / PERIOD) - 1.0)


def grid_ns(k, rate):
    """The time of sample k of a grid of `rate` Hz anchored at t = 0, in ns, rounded half up (k >= 0)."""
    return (2 * k * 10 ** 9 + rate) // (2 * rate)


class Model:
    """The filter written out: y[k] = y[k-1] + a * (x[k] - y[k-1]) in float32, y = initial before the first sample, linear between samples."""

    def __init__(self, rate, initial, coef, source=saw):
        self.rate, self.initial, self.source = rate, f32(initial), source
        self.a = min(max(f32(f32(f32(coef) + 1.0) * 0.5), 0.0), 1.0)
        self.y = []

    def y_at(self, k):
        if k < 0:
            return self.initial
        while len(self.y) <= k:
            previous = self.y[-1] if self.y else self.initial
            x = self.source(grid_ns(len(self.y), self.rate))
            self.y.append(f32(previous + f32(self.a * f32(x - previous))))
        return self.y[k]

    def out(self, t):
        scaled = t * self.rate
        k, fraction = scaled // 10 ** 9, (scaled % 10 ** 9) / 10 ** 9
        y0, y1 = self.y_at(k), self.y_at(k + 1)
        return f32(y0 + fraction * (y1 - y0))


def span_times(t0, t1, n):
    return [t0 + (i * (t1 - t0)) // n for i in range(n)]


def jitter(t):
    """A value that moves by 0.001 with every nanosecond: a time that is one nanosecond off changes it far more than a float's resolution."""
    return f32((t % 1000) / 1000.0)


def saw_type():
    return PyNodeType("py.saw", at=lambda ctx, outlet, t: saw(t))


def jitter_type():
    return PyNodeType("py.jitter", at=lambda ctx, outlet, t: jitter(t))


def sink_type():
    return PyNodeType("py.sink", inlets=[("in0", 0.0), ("in1", 0.5)], outlets=[])


def filter_rig(rate, seconds, initial, coef, jittery=False):
    """saw (1) -> filter (2) -> sink (3), the filter set up as given; with `jittery` the source is the jitter instead of the saw."""
    rig = Rig(jitter_type() if jittery else saw_type(), sink_type(), test_nodes=True)
    rig.node(1, "py.jitter" if jittery else "py.saw")
    rig.node(2, "test_filter")
    rig.node(3, "py.sink")
    rig.connect(1, "out", 2, "in")
    rig.connect(2, "out", 3, "in0")
    set_filter(rig.graph, rate, seconds, initial, coef)
    rig.install()
    return rig


def set_filter(graph, rate, seconds, initial, coef):
    assert e.graph_set_int(graph, 2, b"internal_sampling_rate", rate) == e.OK
    assert e.graph_set_int(graph, 2, b"checkpoint_seconds", seconds) == e.OK
    assert e.graph_set_float(graph, 2, b"initial", initial) == e.OK
    assert e.graph_set_knob(graph, 2, b"coef", coef) == e.OK


def bits(value):
    return struct.pack("<f", value)


def check_point(rig, model, t):
    got = e.instance_inlet_at(rig.instance, 3, 0, t)
    assert bits(got) == bits(model.out(t)), (t, got, model.out(t))


def test_py_the_filter_matches_the_model_at_random_times_and_spans_for_several_rates():
    rng = random.Random(31337)
    for rate, seconds, initial, coef, horizon_s in ((1, 1, 0.5, -0.5, 30.0), (7, 3, -0.25, 0.9, 40.0), (200, 2, 0.0, 0.0, 8.0), (48000, 1, 0.1, -0.9, 0.03)):
        rig = filter_rig(rate, seconds, initial, coef)
        model = Model(rate, initial, coef)
        horizon = int(horizon_s * 1e9)
        for _ in range(120):
            check_point(rig, model, rng.randint(-int(0.6e9), horizon))
        for _ in range(25):
            t0, t1 = rng.randint(-int(0.6e9), horizon), rng.randint(-int(0.6e9), horizon)
            if rng.random() < 0.15:
                t1 = t0
            n = rng.randint(1, 60)
            out = span_buffer(n)
            assert e.instance_inlet_span(rig.instance, 3, 0, t0, t1, n, out) == e.OK
            assert [bits(v) for v in out] == [bits(model.out(t)) for t in span_times(t0, t1, n)], (rate, t0, t1, n)
        rig.close()


def test_py_the_filter_reads_its_input_at_grid_times_rounded_half_up_to_the_nanosecond():
    """With a source that moves by 0.001 per nanosecond a grid time that is one nanosecond off shows at once. At 1024 Hz every odd sample
    lies exactly half a nanosecond between two (a tie, which goes up); the other rates have fractions of every size."""
    rng = random.Random(1024)
    for rate, horizon_s in ((1024, 0.5), (7, 4.0), (3, 5.0), (48000, 0.02), (384000, 0.005)):
        rig = filter_rig(rate, 1, 0.1, 0.3, jittery=True)
        model = Model(rate, 0.1, 0.3, source=jitter)
        for k in range(min(int(horizon_s * rate), 400)):
            check_point(rig, model, grid_ns(k, rate))                            # exactly at the grid times
        for _ in range(60):
            check_point(rig, model, rng.randint(0, int(horizon_s * 1e9)))        # and in between
        rig.close()


def test_py_what_the_filter_has_been_asked_before_never_changes_its_answers():
    rig = filter_rig(100, 2, 0.3, 0.25)
    other = e.engine_new_instance(rig.engine)
    model = Model(100, 0.3, 0.25)
    rng = random.Random(5)
    times = [rng.randint(0, 9 * 10 ** 9) for _ in range(60)]
    first = [e.instance_inlet_at(rig.instance, 3, 0, t) for t in times]         # one instance asked in this order...
    backwards = [e.instance_inlet_at(other, 3, 0, t) for t in reversed(times)]   # ...another asked cold, in the opposite order
    assert [bits(v) for v in first] == [bits(model.out(t)) for t in times]
    assert [bits(v) for v in backwards] == [bits(model.out(t)) for t in reversed(times)]
    e.instance_free(other)
    rig.close()


def test_py_edits_made_through_the_engine_are_followed_exactly_and_never_answered_from_stale_history():
    rig = filter_rig(100, 2, 0.0, 0.0)
    times = [3_217_000_000, 1_000_000_000, 6_999_999_999, 123_456_789, 4_500_000_000]
    model = Model(100, 0.0, 0.0)
    for t in times:
        check_point(rig, model, t)
    # a knob move on the filter's free coef inlet
    assert e.engine_set_knob(rig.engine, 2, 1, 0.6) == e.OK
    model = Model(100, 0.0, f32(0.6))
    for t in times:
        check_point(rig, model, t)
    # the engine's knob generation is what told the filter: moving it back restores the first model's answers
    assert e.engine_set_knob(rig.engine, 2, 1, 0.0) == e.OK
    model = Model(100, 0.0, 0.0)
    for t in times:
        check_point(rig, model, t)
    # settings changed by installing a description again: the initial value, then the rate, then the checkpoint interval
    for rate, seconds, initial in ((100, 2, -0.75), (50, 2, -0.75), (50, 3, -0.75)):
        set_filter(rig.graph, rate, seconds, initial, 0.0)
        rig.update()
        model = Model(rate, initial, 0.0)
        for t in times:
            check_point(rig, model, t)
    assert e.instance_graph_serial(rig.instance) == e.engine_graph_serial(rig.engine) == 4
    rig.close()


def test_py_installing_the_same_description_or_adding_unrelated_nodes_does_not_change_a_single_answer():
    rig = filter_rig(100, 2, 0.2, -0.3)
    model = Model(100, 0.2, -0.3)
    rng = random.Random(77)
    for step in range(30):
        if step == 10:
            rig.node(50, "py.saw")                                               # an unrelated node joins the description
        rig.update()
        for _ in range(4):
            check_point(rig, model, rng.randint(0, 9 * 10 ** 9))
    rig.close()


def test_py_instances_in_other_threads_get_exact_answers_while_graphs_are_installed():
    rate, seconds, initial, coef = 100, 2, 0.1, 0.4
    rig = filter_rig(rate, seconds, initial, coef)
    model = Model(rate, initial, coef)
    horizon = 8 * 10 ** 9
    model.y_at(horizon * rate // 10 ** 9 + 2)                                    # the whole table, so that threads only read it
    problems, answered = [], [0] * 3
    stop = threading.Event()

    def worker(slot):
        instance = e.engine_new_instance(rig.engine)
        rng = random.Random(1000 + slot)
        try:
            while not stop.is_set():
                t = rng.randint(-10 ** 9, horizon)
                got = e.instance_inlet_at(instance, 3, 0, t)
                if bits(got) != bits(model.out(t)):
                    problems.append((slot, t, got, model.out(t)))
                answered[slot] += 1
        finally:
            e.instance_free(instance)

    threads = [threading.Thread(target=worker, args=(slot,)) for slot in range(3)]
    for thread in threads:
        thread.start()
    deadline = time.time() + 60
    try:
        for step in range(60):                                                   # the same graph again, from step 20 with an extra node
            if step == 20:
                rig.node(60, "py.saw")
            rig.update()
            e.engine_collect(rig.engine)
            while min(answered) < step * 4 and time.time() < deadline:          # let every worker make progress between installs
                time.sleep(0.0005)
    finally:                                                                     # whatever happens, the workers must stop
        stop.set()
        for thread in threads:
            thread.join()
    assert not problems, problems[:3]
    assert min(answered) >= 200, answered
    assert e.engine_collect(rig.engine) > 1                                      # the rig's own instance has not been asked yet: it holds the old graphs
    check_point(rig, model, 1_000_000_000)                                       # now it adopts the newest one
    assert e.engine_collect(rig.engine) == 1
    rig.close()
