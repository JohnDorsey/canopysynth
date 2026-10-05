"""Tests: the graph model (plan step 8, design sections 14 and 15): nodes, connections, settings, knobs, IDs, loop protection, boundary names,
the saved form (a golden dict, a hand-written file pinned as a fixture, round trips through JSON), every rejection, migrations by type version,
and a cross-check against the real engine (what the model allows, the engine compiles; what the model calls a fault, the engine does too).

The expected values are written out by hand or come from independent models (a transitive closure for loops), not from the code under test."""
import copy
import json
import os
import random
import subprocess
import sys

import canopysynth
import engine_dll as e
import graph_dll
from canopysynth import BoundaryError, Graph, GraphError, NodeTypes
from canopysynth import _values

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CATALOG = graph_dll.make_catalog()
BUILT_IN = {"boundary_inlet", "boundary_outlet", "file_read", "realtime_preview"}
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1


def new():
    return Graph(types=CATALOG)


def refuses(function, *fragments, kind=GraphError):
    """Calls `function`, which must raise `kind` (GraphError unless told) whose message holds every fragment; returns the message."""
    try:
        function()
    except kind as error:
        for fragment in fragments:
            assert fragment in str(error), (fragment, str(error))
        return str(error)
    raise AssertionError("expected a GraphError, none was raised")


def untouched(graph, function, *fragments):
    """Like `refuses`, and the graph must be exactly as it was."""
    before = graph.to_dict()
    message = refuses(function, *fragments)
    assert graph.to_dict() == before
    return message


def load(data, **keywords):
    return Graph.from_dict(data, types=CATALOG, **keywords)


def good():
    """A small valid saved graph made by hand (not by to_dict)."""
    return {"format": "canopysynth-graph", "version": 1, "loop_protection": True,
            "nodes": [{"id": 1, "type": "boundary_inlet", "type_version": 1, "x": 1, "y": 2, "settings": {"name": "in"}, "knobs": {}},
                      {"id": 2, "type": "boundary_outlet", "type_version": 1, "x": 3.5, "y": 4, "settings": {"name": "out"},
                       "knobs": {"in": 0.5}}],
            "connections": [{"from": [1, "out"], "to": [2, "in"]}]}


# ---------------------------------------------------------------- the catalog

def test_py_the_default_catalog_is_the_dlls_built_in_types_and_nothing_else():
    types = canopysynth.catalog.default_types()
    assert set(types.keys()) == BUILT_IN
    assert types.get("test_filter") is None and "file_read" in types
    graph = Graph()
    assert graph.types is types
    node = graph.add("boundary_inlet", name="x")
    assert node.type == "boundary_inlet"
    refuses(lambda: graph.add("test_filter"), "test_filter", "not installed")


def test_py_importing_the_package_does_not_load_the_dll_and_a_graph_does():
    code = ("import sys, canopysynth; print(canopysynth.catalog._default is None); g = canopysynth.Graph(); "
            "print(canopysynth.catalog._default is not None)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT))
    assert result.stdout.split() == ["True", "True"], (result.stdout, result.stderr)


def test_py_a_catalog_reads_the_descriptors_the_dll_registered_including_the_internal_rate_the_registry_adds():
    mixer = CATALOG.get("py.mixer")
    assert [s["key"] for s in mixer.settings] == ["count", "gain", "label", "wav", "mode", "internal_sampling_rate"]
    assert mixer.setting["internal_sampling_rate"]["default"] == 48000
    assert [(i["key"], i["default_knob"]) for i in mixer.inlets] == [("a", 0.0), ("b", 0.25), ("c", -0.5)]
    assert [o["key"] for o in mixer.outlets] == ["out", "aux"] and mixer.type_version == 1
    assert mixer.defaults == {"count": 7, "gain": 1.5, "label": "hi", "wav": "", "mode": "square", "internal_sampling_rate": 48000}    # a choice by its text
    assert CATALOG.get("py.versioned").type_version == 3
    assert CATALOG.get("test_filter").has_internal_rate and not CATALOG.get("file_read").has_internal_rate
    try:
        CATALOG.add(copy.deepcopy(mixer.data))
    except ValueError as error:
        assert "py.mixer" in str(error)
    else:
        raise AssertionError("a second type with the same key was accepted")


# ---------------------------------------------------------------- nodes, settings, knobs

def test_py_a_new_node_has_the_defaults_of_its_type_and_ids_count_up_from_one():
    graph = new()
    a = graph.add("py.mixer")
    b = graph.add("py.mixer", x=10, y=-2.5, count=9, label="h\u00e9llo", mode="saw")
    assert (a.id, b.id) == (1, 2) and a.type == "py.mixer" and a.graph is graph
    assert dict(a.settings) == {"count": 7, "gain": 1.5, "label": "hi", "wav": "", "mode": "square", "internal_sampling_rate": 48000}
    assert dict(a.knobs) == {"a": 0.0, "b": 0.25, "c": -0.5} and (a.x, a.y) == (0, 0)
    assert dict(b.settings) == {"count": 9, "gain": 1.5, "label": "h\u00e9llo", "wav": "", "mode": "saw", "internal_sampling_rate": 48000}
    assert (b.x, b.y) == (10, -2.5) and [n.id for n in graph.nodes()] == [1, 2] and graph.node(2) is b
    refuses(lambda: graph.node(3), "no node 3")
    refuses(lambda: graph.node("1"), "no node")
    refuses(lambda: graph.node(True), "no node")


def test_py_node_ids_are_never_reused_even_after_the_highest_is_removed_or_all_are():
    graph = new()
    nodes = [graph.add("py.mixer") for _ in range(3)]
    graph.remove(nodes[2])
    assert graph.add("py.mixer").id == 4
    graph.remove(graph.node(1))
    graph.remove(graph.node(2))
    graph.remove(graph.node(4))
    assert graph.nodes() == [] and graph.add("py.mixer").id == 5


def test_py_a_setting_must_be_a_known_key_of_the_right_kind_and_range_and_a_refused_add_adds_nothing():
    graph = new()
    wrong = [("count", 7.0), ("count", "7"), ("count", True), ("count", None), ("count", 2 ** 63), ("count", -2 ** 63 - 1),
             ("gain", "1.5"), ("gain", True), ("gain", float("nan")), ("gain", float("inf")), ("gain", -float("inf")), ("gain", 10 ** 400),
             ("label", 5), ("label", None), ("label", "a\0b"), ("label", "lone \ud800 surrogate"), ("label", b"bytes"),
             ("wav", "song.wav"), ("wav", "C:song.wav"), ("wav", "\\song.wav"), ("wav", "/song.wav"), ("wav", "../x.wav"), ("wav", 3),
             ("mode", "triangle"), ("mode", 1), ("mode", ""), ("mode", None),
             ("internal_sampling_rate", 0), ("internal_sampling_rate", 384001), ("internal_sampling_rate", -1), ("internal_sampling_rate", 48000.0),
             ("nothing", 1), ("", 1)]
    for key, value in wrong:
        untouched(graph, lambda: graph.add("py.mixer", **{key: value}))
    assert graph.nodes() == [] and graph.add("py.mixer").id == 1                    # nothing was added, no ID was used up
    refuses(lambda: graph.add("py.mixer", x=float("nan")), "x")
    refuses(lambda: graph.add("py.mixer", y=True), "y")
    refuses(lambda: graph.add("py.mixer", x="3"), "x")
    refuses(lambda: graph.add("py.mixer", x=10 ** 400), "x", "finite")              # (an int too big for a float is not a position either)
    refuses(lambda: graph.add("py.mixer", y=-10 ** 400), "y", "finite")
    for key in (3, None, [], {}, b"py.mixer"):
        refuses(lambda: graph.add(key), "not installed")
    right = graph.add("py.mixer", count=-2 ** 63, gain=2, label="", wav="C:/a/b.wav", mode="sine", internal_sampling_rate=1)
    assert right.settings["count"] == -2 ** 63 and right.settings["gain"] == 2.0 and type(right.settings["gain"]) is float
    graph.add("py.mixer", count=2 ** 63 - 1, wav="C:\\a\\b.wav", internal_sampling_rate=384000)
    graph.add("py.mixer", wav="\\\\server\\share\\x.wav")
    graph.add("py.mixer", wav="//server/share/x.wav")
    graph.add("py.mixer", wav="d:/x.wav")


def test_py_the_messages_name_the_node_the_key_and_the_choices():
    graph = new()
    node = graph.add("py.mixer")
    refuses(lambda: node.set("mode", "triangle"), "node 1", "py.mixer", "mode", "sine", "square", "saw", "triangle")
    refuses(lambda: node.set("nothing", 1), "node 1", "nothing", "count", "gain")
    refuses(lambda: node.set("wav", "x.wav"), "absolute", "x.wav")
    refuses(lambda: node.set_knob("a", 1.5), "node 1", "'a'", "-1 to 1")
    refuses(lambda: node.set_knob("zzz", 0.0), "node 1", "zzz")
    refuses(lambda: node.inlet("out"), "inlet", "'a', 'b', 'c'")
    refuses(lambda: node.outlet("a"), "outlet", "'out', 'aux'")
    for key in ([], {}, None, 5, b"a"):                                             # keys that are not text: refused, not a TypeError
        refuses(lambda: node.set(key, 1), "node 1", "no setting")
        refuses(lambda: node.set_knob(key, 0.0), "node 1", "no inlet")
        refuses(lambda: node.inlet(key), "node 1", "no inlet")
        refuses(lambda: node.outlet(key), "node 1", "no outlet")


def test_py_set_changes_a_setting_and_knobs_hold_numbers_from_minus_one_to_one():
    graph = new()
    node = graph.add("py.mixer")
    node.set("count", -3)
    node.set("gain", 0.1)
    node.set("mode", "saw")
    node.set("label", "x")
    assert (node.settings["count"], node.settings["gain"], node.settings["mode"], node.settings["label"]) == (-3, 0.1, "saw", "x")
    for value, stored in ((0.7, 0.7), (-1, -1.0), (1, 1.0), (0, 0.0), (-0.0, -0.0)):
        node.set_knob("b", value)
        assert node.knobs["b"] == stored and type(node.knobs["b"]) is float
    for bad in (1.0000001, -1.01, float("nan"), float("inf"), "0.5", None, True, [0.5]):
        node.set_knob("b", 0.3)
        refuses(lambda: node.set_knob("b", bad), "-1 to 1")
        assert node.knobs["b"] == 0.3                                                # a refused value leaves the old one
    node.x, node.y = 5, 6.5
    assert (node.x, node.y) == (5, 6.5)
    refuses(lambda: setattr(node, "x", float("inf")), "x")
    refuses(lambda: setattr(node, "y", "up"), "y")
    assert (node.x, node.y) == (5, 6.5)
    try:
        node.settings["count"] = 1
    except TypeError:
        pass
    else:
        raise AssertionError("the settings view must be read-only")
    try:
        node.knobs["a"] = 1.0
    except TypeError:
        pass
    else:
        raise AssertionError("the knobs view must be read-only")


def test_py_numbers_that_are_subclasses_are_stored_as_plain_numbers():
    class Whole(int):
        pass

    class Real(float):
        pass

    graph = new()
    node = graph.add("py.mixer", count=Whole(4), gain=Real(0.5), x=Real(2.5))
    assert type(node.settings["count"]) is int and type(node.settings["gain"]) is float and type(node.x) is float
    node.set_knob("a", Real(0.25))
    assert type(node.knobs["a"]) is float
    assert json.dumps(graph.to_dict())                                              # and the result is plain JSON
    data = good()                                                                   # node IDs read from a file too
    data["nodes"][0]["id"] = Whole(1)
    data["connections"] = [{"from": [Whole(1), "out"], "to": [Whole(2), "in"]}]
    saved = load(data).to_dict()
    assert [type(n["id"]) for n in saved["nodes"]] == [int, int]
    assert [type(i) for i in saved["connections"][0]["from"][:1] + saved["connections"][0]["to"][:1]] == [int, int]


# ---------------------------------------------------------------- connections

def test_py_connections_fan_out_freely_fan_in_is_refused_and_each_refusal_names_the_inlet():
    graph = new()
    mixer, other = graph.add("py.mixer"), graph.add("py.mixer")
    out, aux = mixer.outlet("out"), mixer.outlet("aux")
    first = graph.connect(out, other.inlet("a"))
    graph.connect(out, other.inlet("b"))                                            # fan-out: one outlet, two inlets
    graph.connect(aux, other.inlet("c"))
    assert first.outlet == out and first.inlet == other.inlet("a")
    message = untouched(graph, lambda: graph.connect(aux, other.inlet("a")), "node 2", "inlet 'a'", "already connected", "node 1")
    assert "'out'" in message
    untouched(graph, lambda: graph.connect(out, other.inlet("a")), "already connected")   # the same connection again is a fan-in too
    assert [(c.outlet.node.id, c.outlet.key, c.inlet.node.id, c.inlet.key) for c in graph.connections()] == [
        (1, "out", 2, "a"), (1, "out", 2, "b"), (1, "aux", 2, "c")]


def test_py_connect_checks_what_it_is_given():
    graph, foreign = new(), new()
    a, b, z = graph.add("py.mixer"), graph.add("py.mixer"), foreign.add("py.mixer")
    untouched(graph, lambda: graph.connect(b.inlet("a"), a.outlet("out")), "inlet", "outlet")        # swapped
    untouched(graph, lambda: graph.connect(a.outlet("out"), b.outlet("aux")), "outlet")
    untouched(graph, lambda: graph.connect(a.inlet("a"), b.inlet("a")), "inlet")
    untouched(graph, lambda: graph.connect(a.outlet("out"), z.inlet("a")), "does not belong")
    untouched(graph, lambda: graph.connect(z.outlet("out"), b.inlet("a")), "does not belong")
    untouched(graph, lambda: graph.connect("out", "a"), "outlet")
    untouched(graph, lambda: graph.connect(a.outlet("out"), None), "inlet")
    untouched(graph, lambda: graph.disconnect(a.outlet("out"), b.inlet("a")), "not connected")
    graph.connect(a.outlet("out"), b.inlet("a"))
    untouched(graph, lambda: graph.disconnect(a.outlet("aux"), b.inlet("a")), "not connected")
    untouched(graph, lambda: graph.disconnect(b.outlet("out"), a.inlet("a")), "not connected")
    graph.disconnect(a.outlet("out"), b.inlet("a"))
    assert graph.connections() == []
    graph.connect(a.outlet("aux"), b.inlet("a"))                                    # the inlet is free again


def test_py_connection_into_and_connections_are_ordered_by_inlet_node_and_inlet_place():
    graph = new()
    s = graph.add("py.mixer")
    t = graph.add("py.mixer")
    u = graph.add("py.mixer")
    graph.connect(s.outlet("out"), u.inlet("c"))
    graph.connect(s.outlet("out"), t.inlet("b"))
    graph.connect(t.outlet("aux"), u.inlet("a"))
    graph.connect(s.outlet("aux"), t.inlet("a"))
    assert [(c.inlet.node.id, c.inlet.key) for c in graph.connections()] == [(2, "a"), (2, "b"), (3, "a"), (3, "c")]
    filt = graph.add("test_filter")                                                  # inlets `in`, `coef`: the type's order, not alphabetical
    graph.connect(s.outlet("out"), filt.inlet("coef"))
    graph.connect(s.outlet("aux"), filt.inlet("in"))
    assert [(c.inlet.node.id, c.inlet.key) for c in graph.connections()][-2:] == [(4, "in"), (4, "coef")]
    graph.disconnect(s.outlet("out"), filt.inlet("coef"))
    graph.disconnect(s.outlet("aux"), filt.inlet("in"))
    graph.remove(filt)
    found = graph.connection_into(u.inlet("a"))
    assert found.outlet == t.outlet("aux") and found.inlet == u.inlet("a")
    assert graph.connection_into(u.inlet("b")) is None
    assert t.inlet("a") == t.inlet("a") and t.inlet("a") != t.inlet("b") and t.inlet("a") != u.inlet("a") and t.outlet("out") != t.inlet("a")
    assert len({t.inlet("a"), t.inlet("a"), t.inlet("b")}) == 2
    twin = new()                                                                    # the same ID and key in another graph is another port
    twin.add("py.mixer")
    twin_node = twin.add("py.mixer")
    assert twin_node.id == t.id and twin_node.inlet("a") != t.inlet("a") and twin_node.outlet("out") != t.outlet("out")
    assert canopysynth.Port(t, "a", "inlet") != canopysynth.Port(t, "a", "outlet") and canopysynth.Port(t, "a", "inlet") == t.inlet("a")


def test_py_removing_a_node_removes_its_connections_and_the_node_and_its_ports_are_dead():
    graph = new()
    a, b, c = graph.add("py.mixer"), graph.add("py.mixer"), graph.add("py.mixer")
    graph.connect(a.outlet("out"), b.inlet("a"))
    graph.connect(b.outlet("out"), c.inlet("a"))
    graph.connect(a.outlet("aux"), c.inlet("b"))
    dead_inlet = b.inlet("c")
    graph.remove(b)
    assert [(x.outlet.node.id, x.inlet.node.id) for x in graph.connections()] == [(1, 3)]
    assert b.graph is None and [n.id for n in graph.nodes()] == [1, 3]
    refuses(lambda: b.set("count", 1), "node 2", "removed")
    refuses(lambda: b.set_knob("a", 0.0), "removed")
    refuses(lambda: b.inlet("a"), "removed")
    refuses(lambda: b.outlet("out"), "removed")
    refuses(lambda: setattr(b, "x", 1), "removed")
    untouched(graph, lambda: graph.connect(a.outlet("out"), dead_inlet), "does not belong")
    untouched(graph, lambda: graph.remove(b), "not a node of this graph")
    untouched(graph, lambda: graph.remove(new().add("py.mixer")), "not a node of this graph")
    untouched(graph, lambda: graph.remove(1), "not a node of this graph")
    assert graph.connection_into(c.inlet("a")) is None                              # the connection from b is gone: c's inlet is free
    graph.connect(a.outlet("out"), c.inlet("a"))


# ---------------------------------------------------------------- loops

def closure(edges, nodes):
    """Independent model: reach[a][b] is True if b can be reached from a by one or more edges (Warshall)."""
    reach = {a: {b: False for b in nodes} for a in nodes}
    for a, b in edges:
        reach[a][b] = True
    for k in nodes:
        for i in nodes:
            if reach[i][k]:
                for j in nodes:
                    if reach[k][j]:
                        reach[i][j] = True
    return reach


def test_py_loop_protection_refuses_a_connection_that_closes_a_loop_and_allows_everything_else():
    graph = new()
    assert graph.loop_protection is True
    n = [graph.add("test_filter") for _ in range(4)]
    untouched(graph, lambda: graph.connect(n[0].outlet("out"), n[0].inlet("in")), "loop", "loop_protection")          # a node into itself
    graph.connect(n[0].outlet("out"), n[1].inlet("in"))
    graph.connect(n[1].outlet("out"), n[2].inlet("in"))
    untouched(graph, lambda: graph.connect(n[2].outlet("out"), n[0].inlet("coef")), "loop")                             # a three-node loop
    untouched(graph, lambda: graph.connect(n[1].outlet("out"), n[0].inlet("in")), "loop")                               # a two-node loop
    graph.connect(n[0].outlet("out"), n[2].inlet("coef"))                                                                # a diamond is no loop
    graph.connect(n[2].outlet("out"), n[3].inlet("in"))
    graph.connect(n[1].outlet("out"), n[3].inlet("coef"))
    assert not graph.has_loop()
    graph.disconnect(n[0].outlet("out"), n[1].inlet("in"))
    untouched(graph, lambda: graph.connect(n[2].outlet("out"), n[0].inlet("coef")), "loop")                             # 0 still leads to 2 directly
    graph.disconnect(n[0].outlet("out"), n[2].inlet("coef"))
    graph.connect(n[2].outlet("out"), n[0].inlet("coef"))                                                                # allowed now: 0 leads nowhere
    assert not graph.has_loop()


def test_py_with_loop_protection_off_loops_are_allowed_and_it_cannot_be_turned_on_while_one_exists():
    graph = new()
    a, b = graph.add("test_filter"), graph.add("test_filter")
    graph.loop_protection = False
    assert graph.loop_protection is False
    graph.connect(a.outlet("out"), a.inlet("in"))                                   # a self-loop
    graph.connect(a.outlet("out"), b.inlet("in"))
    graph.connect(b.outlet("out"), a.inlet("coef"))
    assert graph.has_loop()
    refuses(lambda: setattr(graph, "loop_protection", True), "loop")
    assert graph.loop_protection is False
    graph.disconnect(a.outlet("out"), a.inlet("in"))
    refuses(lambda: setattr(graph, "loop_protection", True), "loop")                # the two-node loop is still there
    graph.disconnect(b.outlet("out"), a.inlet("coef"))
    assert not graph.has_loop()
    graph.loop_protection = True
    assert graph.loop_protection is True
    for bad in (1, 0, None, "yes"):
        refuses(lambda: setattr(graph, "loop_protection", bad), "True or False")
    assert graph.loop_protection is True


def test_py_loop_detection_agrees_with_a_transitive_closure_on_random_graphs():
    rng = random.Random(8)
    for round_number in range(60):
        protection = round_number % 3 != 0
        graph = new()
        graph.loop_protection = protection
        count = rng.randint(2, 7)
        for _ in range(count):
            graph.add("test_filter")
        edges = {}                                                                  # (to ID, inlet) -> from ID
        for _ in range(60):
            action = rng.random()
            ids = [node.id for node in graph.nodes()]
            if action < 0.08 and len(ids) > 2:
                gone = rng.choice(ids)
                graph.remove(graph.node(gone))
                edges = {k: v for k, v in edges.items() if k[0] != gone and v != gone}
                continue
            if action < 0.2 and edges:
                (to, inlet), source = rng.choice(sorted(edges.items()))
                graph.disconnect(graph.node(source).outlet("out"), graph.node(to).inlet(inlet))
                del edges[(to, inlet)]
                continue
            source, to, inlet = rng.choice(ids), rng.choice(ids), rng.choice(["in", "coef"])
            reach = closure(set((v, k[0]) for k, v in edges.items()), ids)
            would_loop = source == to or reach[to][source]
            try:
                graph.connect(graph.node(source).outlet("out"), graph.node(to).inlet(inlet))
                accepted = True
            except GraphError as error:
                accepted = False
                assert ("already connected" in str(error)) == ((to, inlet) in edges) and (
                    ("loop" in str(error)) == ((to, inlet) not in edges and protection and would_loop))
            if (to, inlet) in edges:
                assert not accepted
            elif protection and would_loop:
                assert not accepted
            else:
                assert accepted
                edges[(to, inlet)] = source
            reach = closure(set((v, k[0]) for k, v in edges.items()), ids)
            assert graph.has_loop() == any(reach[i][i] for i in ids), (round_number, edges)
            if protection:
                assert not graph.has_loop()
        assert len(graph.connections()) == len(edges)


def test_py_can_connect_says_exactly_what_connect_would_do_with_the_same_words_and_never_raises():
    rng = random.Random(10)
    asked = refused_loop = refused_fan_in = 0
    for round_number in range(40):
        graph = new()
        graph.loop_protection = round_number % 4 != 0
        for _ in range(rng.randint(2, 6)):
            graph.add("test_filter")
        for _ in range(60):
            nodes = graph.nodes()
            source, target = rng.choice(nodes), rng.choice(nodes)
            outlet, inlet = source.outlet("out"), target.inlet(rng.choice(["in", "coef"]))
            reason = graph.can_connect(outlet, inlet)
            clone = Graph.from_dict(graph.to_dict(), types=CATALOG)               # try it on a copy
            try:
                clone.connect(clone.node(source.id).outlet("out"), clone.node(target.id).inlet(inlet.key))
                assert reason is None, reason
            except GraphError as error:
                assert reason == str(error), (reason, str(error))
                refused_loop += "loop" in reason
                refused_fan_in += "already connected" in reason
            asked += 1
            if reason is None:
                graph.connect(outlet, inlet)
        assert not graph.loop_protection or not graph.has_loop()
    assert asked == 2400 and refused_loop > 50 and refused_fan_in > 100              # (the random graphs do reach both kinds of refusal)
    graph, foreign = new(), new()
    a, b, z = graph.add("py.mixer"), graph.add("py.mixer"), foreign.add("py.mixer")
    for first, second in ((b.inlet("a"), a.outlet("out")), (a.outlet("out"), b.outlet("aux")), (a.outlet("out"), z.inlet("a")), ("out", "a"), (None, None),
                          (a.outlet("out"), 5)):
        reason = graph.can_connect(first, second)
        assert isinstance(reason, str) and reason
        refuses(lambda: graph.connect(first, second), reason[:30])                  # connect refuses with the same sentence
    assert graph.can_connect(a.outlet("out"), b.inlet("a")) is None
    dead = b.inlet("a")
    graph.remove(b)
    assert "does not belong" in graph.can_connect(a.outlet("out"), dead)                  # a port of a removed node is not this graph's any more


# ---------------------------------------------------------------- boundary nodes

def test_py_boundary_nodes_are_listed_by_name_in_byte_order_with_their_kind_and_id():
    graph = new()
    graph.add("test_filter")
    names = [("b", "boundary_inlet"), ("B", "boundary_outlet"), ("\u00e9", "boundary_inlet"), ("a", "boundary_outlet"), ("Z", "boundary_inlet"),
             ("\U00010000", "boundary_outlet"), ("\uffff", "boundary_inlet")]
    for name, key in names:
        graph.add(key, name=name)
    listed = graph.boundary_nodes()
    assert [(b.name, b.kind, b.node_id) for b in listed] == [("B", "outlet", 3), ("Z", "inlet", 6), ("a", "outlet", 5), ("b", "inlet", 2),
                                                             ("\u00e9", "inlet", 4), ("\uffff", "inlet", 8), ("\U00010000", "outlet", 7)]
    assert all(isinstance(b, canopysynth.BoundaryInfo) for b in listed)
    graph.node(5).set("name", "renamed")
    assert "renamed" in [b.name for b in graph.boundary_nodes()] and "a" not in [b.name for b in graph.boundary_nodes()]
    graph.remove(graph.node(5))
    assert "renamed" not in [b.name for b in graph.boundary_nodes()]


def test_py_the_model_allows_empty_and_repeated_boundary_names_while_editing_and_validate_reports_them():
    graph = new()
    first, second, third = graph.add("boundary_inlet", name="x"), graph.add("boundary_outlet"), graph.add("boundary_outlet", name="x")
    assert [b.name for b in graph.boundary_nodes()] == ["", "x", "x"]
    refuses(graph.validate, "node 2", "boundary node", "needs a name", kind=BoundaryError)
    second.set("name", "y")
    refuses(graph.validate, '"x"', "node 1", "node 3", "unique", kind=BoundaryError)                    # across the two kinds, the first ID is named first
    third.set("name", "X")
    graph.validate()                                                                # case matters: "x" and "X" differ
    first.set("name", "y")
    refuses(graph.validate, '"y"', "node 1", "node 2", "unique", kind=BoundaryError)
    graph.remove(second)
    graph.validate()
    new().validate()


# ---------------------------------------------------------------- the saved form

def reference_graph():
    graph = new()
    song = graph.add("file_read", x=10, y=20.5, path="C:/audio/song.wav")
    left = graph.add("boundary_outlet", x=300, y=20, name="song_left")
    level = graph.add("boundary_inlet", x=0, y=100, name="intensity")
    play = graph.add("realtime_preview", x=300, y=200, device="Speakers (X)")
    play.set_knob("left", 0.5)
    graph.connect(song.outlet("left"), left.inlet("in"))
    graph.connect(level.outlet("out"), play.inlet("center"))
    return graph


def test_py_to_dict_is_exactly_the_documented_format_with_every_setting_and_knob_written_out():
    expected = {
        "format": "canopysynth-graph", "version": 1, "loop_protection": True,
        "nodes": [
            {"id": 1, "type": "file_read", "type_version": 1, "x": 10, "y": 20.5, "settings": {"path": "C:/audio/song.wav"}, "knobs": {}},
            {"id": 2, "type": "boundary_outlet", "type_version": 1, "x": 300, "y": 20, "settings": {"name": "song_left"}, "knobs": {"in": 0.0}},
            {"id": 3, "type": "boundary_inlet", "type_version": 1, "x": 0, "y": 100, "settings": {"name": "intensity"}, "knobs": {}},
            {"id": 4, "type": "realtime_preview", "type_version": 1, "x": 300, "y": 200, "settings": {"device": "Speakers (X)"},
             "knobs": {"left": 0.5, "right": 0.0, "center": 0.0}}],
        "connections": [{"from": [1, "left"], "to": [2, "in"]}, {"from": [3, "out"], "to": [4, "center"]}]}
    got = reference_graph().to_dict()
    assert got == expected
    assert list(got) == ["format", "version", "loop_protection", "nodes", "connections"]
    assert list(got["nodes"][0]) == ["id", "type", "type_version", "x", "y", "settings", "knobs"]
    assert list(got["connections"][0]) == ["from", "to"]
    assert list(got["nodes"][3]["knobs"]) == ["left", "right", "center"]            # the order of the type's inlets
    assert type(got["connections"][0]["from"]) is list
    assert json.loads(json.dumps(got)) == expected
    empty = new().to_dict()
    assert empty == {"format": "canopysynth-graph", "version": 1, "loop_protection": True, "nodes": [], "connections": []}
    other = new()
    other.loop_protection = False
    assert other.to_dict()["loop_protection"] is False


def test_py_to_dict_is_independent_of_the_order_things_were_made_in_and_hands_out_fresh_data():
    one, two = new(), new()
    for graph in (one, two):
        for _ in range(3):
            graph.add("py.mixer")
    one.connect(one.node(1).outlet("out"), one.node(3).inlet("c"))
    one.connect(one.node(2).outlet("out"), one.node(3).inlet("a"))
    one.connect(one.node(1).outlet("aux"), one.node(2).inlet("b"))
    two.connect(two.node(1).outlet("aux"), two.node(2).inlet("b"))                  # the same connections, made in another order
    two.connect(two.node(2).outlet("out"), two.node(3).inlet("a"))
    two.connect(two.node(1).outlet("out"), two.node(3).inlet("c"))
    assert two.to_dict() == one.to_dict() and json.dumps(two.to_dict()) == json.dumps(one.to_dict())
    assert [(c["from"], c["to"]) for c in one.to_dict()["connections"]] == [([1, "aux"], [2, "b"]), ([2, "out"], [3, "a"]), ([1, "out"], [3, "c"])]
    snapshot = one.to_dict()
    handed = one.to_dict()
    handed["nodes"][0]["settings"]["count"] = 99
    handed["nodes"][0]["knobs"]["a"] = 0.9
    handed["connections"].clear()
    handed["nodes"].clear()
    assert one.to_dict() == snapshot


def test_py_a_graph_survives_json_exactly_including_awkward_numbers_and_text():
    graph = new()
    node = graph.add("py.mixer", x=-0.0, y=1e-300, count=INT64_MIN, gain=5e-324, label="tab\t quote\" slash\\ \u00e9\u4e2d\U0001f600 \u0001",
                     wav="C:\\dir with spaces\\\u00e9.wav", mode="saw", internal_sampling_rate=44100)
    node.set_knob("a", 0.1)
    node.set_knob("b", -0.9999999999999999)
    other = graph.add("py.mixer", gain=1.7976931348623157e308, count=INT64_MAX, x=123456789012345678, y=2.5e-7)
    other.set_knob("c", 1.0)
    graph.connect(node.outlet("aux"), other.inlet("a"))
    text = json.dumps(graph.to_dict())
    back = Graph.from_dict(json.loads(text), types=CATALOG)
    assert back.to_dict() == graph.to_dict() and json.dumps(back.to_dict()) == text
    b1, b2 = back.node(1), back.node(2)
    assert b1.settings["gain"] == 5e-324 and b2.settings["gain"] == 1.7976931348623157e308 and b1.settings["count"] == INT64_MIN
    assert b2.settings["count"] == INT64_MAX and b1.knobs["a"] == 0.1 and b1.knobs["b"] == -0.9999999999999999
    assert b1.settings["label"] == graph.node(1).settings["label"] and str(b1.x) == "-0.0" and b2.x == 123456789012345678
    assert back.connections()[0].outlet == b1.outlet("aux") and back.connections()[0].inlet == b2.inlet("a")


def test_py_a_hand_written_version_1_file_is_pinned_as_a_fixture():
    with open(os.path.join(HERE, "fixtures", "graph_v1.json"), encoding="utf-8") as handle:
        written = json.load(handle)
    graph = Graph.from_dict(written)                                                # the built-in types only: the default catalog
    assert graph.to_dict() == written                                               # the file is in the canonical form, so it comes back as it was
    assert [n.id for n in graph.nodes()] == [1, 2, 3, 4, 5, 7]
    song = graph.node(1)
    assert song.settings["path"] == "C:/audio/does_not_exist_anymore.wav"           # a WAV that does not exist: loads without complaint
    assert not os.path.exists(song.settings["path"])
    assert (song.x, song.y) == (40, 60.5) and graph.node(5).settings["device"] == "Speakers (Test Device)"
    assert dict(graph.node(5).knobs) == {"left": 0.5, "right": -0.25, "center": 0.0} and graph.node(7).knobs["in"] == 1.0
    assert [(c.outlet.node.id, c.outlet.key, c.inlet.node.id, c.inlet.key) for c in graph.connections()] == [
        (1, "left", 2, "in"), (1, "right", 3, "in"), (4, "out", 5, "center"), (1, "left", 7, "in")]
    assert [(b.name, b.kind, b.node_id) for b in graph.boundary_nodes()] == [
        ("copy_of_left", "outlet", 7), ("intensity", "inlet", 4), ("song_left", "outlet", 2), ("song_right", "outlet", 3)]
    assert graph.loop_protection is True and graph.add("boundary_inlet", name="z").id == 8     # IDs go on after the highest, the gap (6) stays
    graph.validate()


def test_py_a_file_may_leave_out_settings_and_knobs_that_are_at_their_defaults():
    data = {"format": "canopysynth-graph", "version": 1, "loop_protection": False,
            "nodes": [{"id": 5, "type": "py.mixer", "type_version": 1, "x": 0, "y": 0, "settings": {"count": 1}, "knobs": {"c": 0.75}}]}
    data["connections"] = []
    node = load(data).node(5)
    assert dict(node.settings) == {"count": 1, "gain": 1.5, "label": "hi", "wav": "", "mode": "square", "internal_sampling_rate": 48000}
    assert dict(node.knobs) == {"a": 0.0, "b": 0.25, "c": 0.75}


def test_py_loading_gives_the_graph_its_next_id_from_the_highest_one_and_accepts_any_id_that_fits_64_bits():
    data = good()
    for node, value in zip(data["nodes"], (-7, 40)):
        node["id"] = value
    data["connections"] = [{"from": [-7, "out"], "to": [40, "in"]}]
    graph = load(data)
    assert graph.add("boundary_inlet", name="n").id == 41
    data["nodes"][0]["id"], data["nodes"][1]["id"] = 40, -7                          # (the file lists the higher ID first)
    data["connections"] = [{"from": [40, "out"], "to": [-7, "in"]}]
    graph = load(data)
    assert [n.id for n in graph.nodes()] == [-7, 40] and graph.add("boundary_inlet", name="n").id == 41
    assert [n["id"] for n in graph.to_dict()["nodes"]] == [-7, 40, 41]
    data["nodes"][0]["id"], data["nodes"][1]["id"] = -9, -3
    data["connections"] = [{"from": [-9, "out"], "to": [-3, "in"]}]
    assert load(data).add("boundary_inlet", name="n").id == 1                       # never below 1, never one of the loaded IDs
    data["nodes"][1]["id"] = INT64_MAX
    data["connections"] = [{"from": [-9, "out"], "to": [INT64_MAX, "in"]}]
    graph = load(data)
    assert graph.node(INT64_MAX).type == "boundary_outlet"
    refuses(lambda: graph.add("boundary_inlet", name="n"), "node ID")


def test_py_from_dict_does_not_change_what_it_is_given_and_keeps_nothing_of_it():
    data = good()
    data["nodes"][1]["settings"]["name"] = "kept"
    snapshot = copy.deepcopy(data)
    graph = load(data)
    assert data == snapshot
    data["nodes"][1]["settings"]["name"] = "changed afterwards"
    data["nodes"][1]["knobs"]["in"] = -1.0
    data["nodes"].pop()
    assert graph.node(2).settings["name"] == "kept" and graph.node(2).knobs["in"] == 0.5 and len(graph.nodes()) == 2
    load({**good(), "nodes": tuple(good()["nodes"]), "connections": ({"from": (1, "out"), "to": (2, "in")},)})      # tuples read as lists
    assert load(good(), base_dir=None).to_dict() == load(good(), base_dir="C:/unused").to_dict()                  # base_dir is accepted, unused


# ---------------------------------------------------------------- rejections

def test_py_a_file_that_is_not_in_the_format_is_rejected_as_a_whole_with_the_reason():
    def mutate(function):
        data = good()
        function(data)
        return data

    cases = [
        (lambda d: d.update(format="other"), "format"),
        (lambda d: d.pop("format"), "lacks: format"),
        (lambda d: d.update(version=2), "newer"),
        (lambda d: d.update(version=0), "version"),
        (lambda d: d.update(version="1"), "version"),
        (lambda d: d.update(version=True), "version"),
        (lambda d: d.update(version=1.0), "version"),
        (lambda d: d.pop("version"), "lacks: version"),
        (lambda d: d.update(loop_protection="yes"), "loop_protection"),
        (lambda d: d.pop("loop_protection"), "lacks: loop_protection"),
        (lambda d: d.update(nodes="x"), "lists"),
        (lambda d: d.update(connections=None), "lists"),
        (lambda d: d.pop("nodes"), "lacks: nodes"),
        (lambda d: d.pop("connections"), "lacks: connections"),
        (lambda d: d.update(extra=1), "unknown entries: extra"),
        (lambda d: d["nodes"].__setitem__(0, 5), "a node must be an object"),
        (lambda d: d["nodes"][0].pop("x"), "lacks: x"),
        (lambda d: d["nodes"][0].pop("type_version"), "lacks: type_version"),
        (lambda d: d["nodes"][0].update(color="red"), "unknown entries: color"),
        (lambda d: d["nodes"][0].update(id=1.0), "id"),
        (lambda d: d["nodes"][0].update(id="1"), "id"),
        (lambda d: d["nodes"][0].update(id=True), "id"),
        (lambda d: d["nodes"][0].update(id=2 ** 63), "64 bits"),
        (lambda d: d["nodes"][1].update(id=1), "ID 1 is used twice"),
        (lambda d: d["nodes"][0].update(type=7), "type must be text"),
        (lambda d: d["nodes"][0].update(type="nothing.such"), "nothing.such", "not installed"),
        (lambda d: d["nodes"][0].update(type_version=0), "type_version"),
        (lambda d: d["nodes"][0].update(type_version=True), "type_version"),
        (lambda d: d["nodes"][0].update(type_version="1"), "type_version"),
        (lambda d: d["nodes"][0].update(type_version=2), "newer than the installed version 1"),
        (lambda d: d["nodes"][0].update(x=float("nan")), "x"),
        (lambda d: d["nodes"][0].update(y="2"), "y"),
        (lambda d: d["nodes"][0].update(settings=[]), "settings and knobs must be objects"),
        (lambda d: d["nodes"][0].update(knobs=None), "settings and knobs must be objects"),
        (lambda d: d["nodes"][0]["settings"].update(name=5), "name", "text"),
        (lambda d: d["nodes"][0]["settings"].update(volume=5), "volume"),
        (lambda d: d["nodes"][1]["knobs"].update(in_=0.5), "in_"),
        (lambda d: d["nodes"][1]["knobs"].update({"in": 2.0}), "-1 to 1"),
        (lambda d: d["nodes"][1]["knobs"].update({"in": "0.5"}), "-1 to 1"),
        (lambda d: d["nodes"][1]["knobs"].update({"in": None}), "-1 to 1"),
        (lambda d: d["connections"].__setitem__(0, "x"), "a connection must be an object"),
        (lambda d: d["connections"][0].pop("to"), "lacks: to"),
        (lambda d: d["connections"][0].update(label="x"), "unknown entries: label"),
        (lambda d: d["connections"][0].update({"from": [1]}), "from"),
        (lambda d: d["connections"][0].update({"from": [1, "out", 3]}), "from"),
        (lambda d: d["connections"][0].update({"from": "1.out"}), "from"),
        (lambda d: d["connections"][0].update({"from": [1, 5]}), "from"),
        (lambda d: d["connections"][0].update({"from": ["1", "out"]}), "node"),
        (lambda d: d["connections"][0].update({"from": [9, "out"]}), "node 9", "does not exist"),
        (lambda d: d["connections"][0].update({"to": [9, "in"]}), "node 9", "does not exist"),
        (lambda d: d["connections"][0].update({"from": [1, "nothing"]}), "no outlet 'nothing'"),
        (lambda d: d["connections"][0].update({"from": [2, "in"]}), "no outlet 'in'"),
        (lambda d: d["connections"][0].update({"to": [2, "nothing"]}), "no inlet 'nothing'"),
        (lambda d: d["connections"][0].update({"to": [1, "out"]}), "no inlet 'out'"),
        (lambda d: d["connections"].append(copy.deepcopy(d["connections"][0])), "two connections"),
    ]
    for case in cases:
        function, fragments = case[0], case[1:]
        data = mutate(function)
        snapshot = copy.deepcopy(data)
        message = refuses(lambda: load(data), "cannot load the graph", *fragments)
        assert data == snapshot, message
    assert load(good()).to_dict()["connections"] == good()["connections"]                                         # and the unmutated one loads
    refuses(lambda: Graph.from_dict(None, types=CATALOG), "must be an object")
    refuses(lambda: Graph.from_dict([], types=CATALOG), "must be an object")
    refuses(lambda: Graph.from_dict(json.dumps(good()), types=CATALOG), "must be an object")                         # text is not a dict


def test_py_a_node_type_that_is_not_installed_rejects_the_whole_file_wherever_it_is_in_it():
    for position in (0, 1, 2):
        data = good()
        data["nodes"].insert(position, {"id": 9, "type": "vendor.ghost", "type_version": 1, "x": 0, "y": 0, "settings": {}, "knobs": {}})
        refuses(lambda: load(data), "cannot load the graph", "node 9", "vendor.ghost", "not installed")
    data = good()
    data["nodes"][0]["type"] = "test_filter"                                         # a real type, but not in the default catalog
    refuses(lambda: Graph.from_dict(data), "test_filter", "not installed")
    refuses(lambda: Graph.from_dict(data, types=NodeTypes()), "not installed")


def test_py_every_setting_kind_is_checked_when_loading_like_when_setting():
    def with_setting(key, value):
        return {"format": "canopysynth-graph", "version": 1, "loop_protection": True, "connections": [],
                "nodes": [{"id": 1, "type": "py.mixer", "type_version": 1, "x": 0, "y": 0, "settings": {key: value}, "knobs": {}}]}

    for key, value in (("count", 1.5), ("count", "1"), ("gain", "x"), ("gain", float("nan")), ("label", None), ("wav", "relative.wav"),
                       ("wav", "C:rel.wav"), ("mode", "triangle"), ("mode", 0), ("internal_sampling_rate", 0), ("internal_sampling_rate", 384001)):
        refuses(lambda: load(with_setting(key, value)), "cannot load the graph", key)
    node = load(with_setting("gain", 3)).node(1)
    assert node.settings["gain"] == 3.0 and type(node.settings["gain"]) is float


def test_py_corrupting_a_valid_file_at_random_gives_a_graph_error_or_a_graph_never_another_exception():
    rng = random.Random(14)
    junk = [None, True, False, 0, 1, -1, 2 ** 63, -2 ** 63 - 1, 10 ** 400, 1.5, float("nan"), float("inf"), "", "x", "in", "out", "C:/a.wav", "\ud800",
            "a\0b", [], [1], [1, "out"], ["1", "out"], {}, {"a": 1}, [[]], (1, "out")]
    base = reference_graph().to_dict()

    def leaves(value, path=()):
        if isinstance(value, dict):
            for key in list(value):
                yield from leaves(value[key], path + (key,))
        elif isinstance(value, list):
            for index in range(len(value)):
                yield from leaves(value[index], path + (index,))
        yield path

    paths = [p for p in leaves(base) if p]
    loaded = refused = 0
    for _ in range(3000):
        data = copy.deepcopy(base)
        for _ in range(rng.randint(1, 3)):
            path = rng.choice(paths)
            parent = data
            try:
                for step in path[:-1]:
                    parent = parent[step]
                action = rng.random()
                if action < 0.15 and isinstance(parent, dict):
                    del parent[path[-1]]
                elif action < 0.25 and isinstance(parent, list):
                    parent.append(rng.choice(junk))
                else:
                    parent[path[-1]] = rng.choice(junk)
            except (KeyError, IndexError, TypeError):
                pass                                                                    # (the structure was already changed under this path)
        try:
            graph = load(data)
        except GraphError:
            refused += 1
            continue
        loaded += 1
        again = graph.to_dict()
        assert load(json.loads(json.dumps(again))).to_dict() == again                 # whatever loads, saves and loads again unchanged
    assert loaded > 20 and refused > 1000, (loaded, refused)


def test_py_a_loop_in_a_file_is_refused_unless_loop_protection_is_off():
    def loop(protection):
        nodes = [{"id": i, "type": "test_filter", "type_version": 1, "x": 0, "y": 0, "settings": {}, "knobs": {}} for i in (1, 2, 3)]
        connections = [{"from": [1, "out"], "to": [2, "in"]}, {"from": [2, "out"], "to": [3, "in"]}, {"from": [3, "out"], "to": [1, "coef"]}]
        return {"format": "canopysynth-graph", "version": 1, "loop_protection": protection, "nodes": nodes, "connections": connections}

    refuses(lambda: load(loop(True)), "cannot load the graph", "loop")
    graph = load(loop(False))
    assert graph.has_loop() and graph.loop_protection is False
    assert sorted((c["from"], c["to"]) for c in graph.to_dict()["connections"]) == sorted((c["from"], c["to"]) for c in loop(False)["connections"])
    assert load(graph.to_dict()).to_dict() == graph.to_dict()                       # and a saved graph with a loop comes back
    data = loop(True)
    data["connections"][2] = {"from": [3, "out"], "to": [3, "coef"]}                 # a node into itself
    refuses(lambda: load(data), "loop")
    data["connections"] = data["connections"][:2]
    assert not load(data).has_loop()


def test_py_a_missing_wav_is_not_an_error_for_the_model_it_is_only_text_until_the_engine_loads_it():
    for path in ("C:/no/such/folder/gone.wav", "C:/", "D:\\\\", "\\\\no-such-host\\share\\x.wav", ""):
        data = {"format": "canopysynth-graph", "version": 1, "loop_protection": True, "connections": [],
                "nodes": [{"id": 1, "type": "file_read", "type_version": 1, "x": 0, "y": 0, "settings": {"path": path}, "knobs": {}}]}
        assert load(data).node(1).settings["path"] == path
    graph = new()
    graph.add("file_read", path="C:/no/such/folder/gone.wav")
    assert graph.to_dict()["nodes"][0]["settings"]["path"] == "C:/no/such/folder/gone.wav"


# ---------------------------------------------------------------- migrations

def versioned_file(version, settings, knobs, connections=(), extra_nodes=()):
    node = {"id": 1, "type": "py.versioned", "type_version": version, "x": 0, "y": 0, "settings": settings, "knobs": knobs}
    return {"format": "canopysynth-graph", "version": 1, "loop_protection": True,
            "nodes": [node, {"id": 2, "type": "py.mixer", "type_version": 1, "x": 0, "y": 0, "settings": {}, "knobs": {}}, *extra_nodes],
            "connections": list(connections)}


def migrating_catalog():
    """py.versioned at version 3. Version 1 had: setting `freq` (float), inlets `amp`, `pan`, `old`, outlets `signal` and `junk`. Version 2:
    `freq` became `frequency`, the inlet `amp` became `level`, `old` is gone, the outlet `signal` became `main`, `junk` is gone, and a setting
    `shape` (int 0/1) came. Version 3: `shape` became the choice `mode` ("a"/"b"), the outlet `main` became `out` and the outlet `aux` was added."""
    catalog = copy.copy(CATALOG)
    catalog._migrations = {}

    def to_two(settings, knobs):
        settings["frequency"] = settings.pop("freq")
        settings["shape"] = 0

    def to_three(settings, knobs):
        settings["mode"] = ["a", "b"][settings.pop("shape")]

    catalog.add_migration("py.versioned", 1, upgrade=to_two, inlets={"amp": "level", "old": None}, outlets={"signal": "main", "junk": None})
    catalog.add_migration("py.versioned", 2, upgrade=to_three, outlets={"main": "out"})
    return catalog


def test_py_a_file_saved_under_an_older_type_version_is_migrated_through_every_step_and_its_connections_follow():
    catalog = migrating_catalog()
    connections = [{"from": [2, "out"], "to": [1, "amp"]}, {"from": [2, "aux"], "to": [1, "old"]}, {"from": [1, "signal"], "to": [3, "a"]},
                   {"from": [1, "junk"], "to": [3, "b"]}]
    third = {"id": 3, "type": "py.mixer", "type_version": 1, "x": 0, "y": 0, "settings": {}, "knobs": {}}
    data = versioned_file(1, {"freq": 220.5}, {"amp": 0.5, "pan": -0.25, "old": 0.75}, connections, [third])
    snapshot = copy.deepcopy(data)
    graph = Graph.from_dict(data, types=catalog)
    assert data == snapshot                                                           # the file's dicts were not handed to the migrations
    node = graph.node(1)
    assert dict(node.settings) == {"frequency": 220.5, "mode": "a"}
    assert dict(node.knobs) == {"level": 0.5, "pan": -0.25}                           # `old` is gone with its knob; `amp` is `level`
    assert [(c.outlet.node.id, c.outlet.key, c.inlet.node.id, c.inlet.key) for c in graph.connections()] == [
        (2, "out", 1, "level"), (1, "out", 3, "a")]               # `signal` is `out` after two renames; the connections of `old` and `junk` are gone
    saved = graph.to_dict()
    assert saved["nodes"][0]["type_version"] == 3
    assert Graph.from_dict(saved, types=catalog).to_dict() == saved


def test_py_the_migrations_run_in_order_and_a_file_at_version_2_only_takes_the_later_ones():
    catalog = migrating_catalog()
    seen = []

    def one(settings, knobs):
        seen.append(1)
        settings.update(frequency=settings.pop("freq"), shape=1)

    def two(settings, knobs):
        seen.append(2)
        settings.update(mode=["a", "b"][settings.pop("shape")])

    catalog._migrations.clear()
    catalog.add_migration("py.versioned", 1, upgrade=one)
    catalog.add_migration("py.versioned", 2, upgrade=two)
    node = Graph.from_dict(versioned_file(1, {"freq": 1.0}, {}), types=catalog).node(1)
    assert seen == [1, 2] and dict(node.settings) == {"frequency": 1.0, "mode": "b"}
    del seen[:]
    node = Graph.from_dict(versioned_file(2, {"frequency": 2.0, "shape": 0}, {}), types=catalog).node(1)
    assert seen == [2] and dict(node.settings) == {"frequency": 2.0, "mode": "a"}
    del seen[:]
    node = Graph.from_dict(versioned_file(3, {"frequency": 3.0, "mode": "b"}, {}), types=catalog).node(1)
    assert seen == [] and dict(node.settings) == {"frequency": 3.0, "mode": "b"}


def test_py_a_file_that_cannot_be_brought_up_to_date_is_rejected_with_the_reason():
    catalog = migrating_catalog()
    refuses(lambda: Graph.from_dict(versioned_file(4, {}, {}), types=catalog), "newer than the installed version 3")
    bare = copy.copy(CATALOG)
    bare._migrations = {}
    refuses(lambda: Graph.from_dict(versioned_file(1, {"freq": 1.0}, {}), types=bare), "no migration from version 1 to 2")
    bare.add_migration("py.versioned", 2, upgrade=lambda s, k: s.update(mode="a"))
    refuses(lambda: Graph.from_dict(versioned_file(1, {"freq": 1.0}, {}), types=bare), "no migration from version 1 to 2")       # a gap in the chain
    node = Graph.from_dict(versioned_file(2, {"frequency": 1.0}, {}), types=bare).node(1)                                   # but from 2 it works
    assert node.settings["mode"] == "a"
    # what the migrations leave is checked against the current type like any file
    catalog = copy.copy(CATALOG)
    catalog._migrations = {}
    catalog.add_migration("py.versioned", 1, upgrade=lambda s, k: s.update(frequency="loud"))
    catalog.add_migration("py.versioned", 2)
    refuses(lambda: Graph.from_dict(versioned_file(1, {}, {}), types=catalog), "frequency")
    catalog._migrations = {}
    catalog.add_migration("py.versioned", 1)
    catalog.add_migration("py.versioned", 2, upgrade=lambda s, k: s.update(unknown_setting=1))
    refuses(lambda: Graph.from_dict(versioned_file(1, {}, {}), types=catalog), "unknown_setting")
    catalog._migrations = {}
    catalog.add_migration("py.versioned", 1, inlets={"amp": "nothing_like_it"})
    catalog.add_migration("py.versioned", 2)
    refuses(lambda: Graph.from_dict(versioned_file(1, {}, {"amp": 0.5}), types=catalog), "nothing_like_it")


def test_py_registering_a_migration_checks_the_type_the_version_and_the_arguments():
    catalog = copy.copy(CATALOG)
    catalog._migrations = {}

    def refused(*arguments, **keywords):
        try:
            catalog.add_migration(*arguments, **keywords)
        except ValueError:
            return
        raise AssertionError(f"accepted: {arguments} {keywords}")

    refused("vendor.nothing", 1)
    refused("py.mixer", 1)                                                           # version 1 is the current one: nothing to migrate from
    refused("py.versioned", 0)
    refused("py.versioned", 3)
    refused("py.versioned", "1")
    refused("py.versioned", True)
    refused("py.versioned", 1, upgrade="not callable")
    refused("py.versioned", 1, inlets={"a": 5})
    refused("py.versioned", 1, outlets={1: "a"})
    catalog.add_migration("py.versioned", 1)
    refused("py.versioned", 1)                                                       # twice
    catalog.add_migration("py.versioned", 2, upgrade=None, inlets={"a": None}, outlets={"b": "c"})
    assert catalog.migration("py.versioned", 2) is not None and catalog.migration("py.versioned", 3) is None


# ---------------------------------------------------------------- against the real engine

def test_py_a_graph_the_model_allows_is_compiled_by_the_engine_with_the_same_nodes_knobs_and_boundary_list():
    rig = e.Rig(*graph_dll.python_types(), test_nodes=True)
    graph = Graph(types=CATALOG)
    song = graph.add("file_read", path="C:/definitely/not/here.wav")
    out_left = graph.add("boundary_outlet", name="left")
    out_right = graph.add("boundary_outlet", name="Right")
    level = graph.add("boundary_inlet", name="level")
    play = graph.add("realtime_preview", device="(system default)")
    mixer = graph.add("py.mixer", count=-5, gain=0.25, label="\u00e9", wav="C:/x.wav", mode="saw", internal_sampling_rate=22050)
    filt = graph.add("test_filter", internal_sampling_rate=1000, initial=0.5)
    graph.add("py.versioned", frequency=100.0, mode="b")
    for node, key, value in ((play, "left", 0.5), (play, "right", -1.0), (mixer, "a", 0.3), (mixer, "c", 1.0), (filt, "coef", -0.125)):
        node.set_knob(key, value)
    graph.connect(song.outlet("left"), out_left.inlet("in"))
    graph.connect(song.outlet("right"), out_right.inlet("in"))
    graph.connect(level.outlet("out"), play.inlet("center"))
    graph.connect(mixer.outlet("aux"), filt.inlet("in"))
    status, text = graph_dll.compile_in(rig, graph)
    assert status == e.OK, text
    assert e.engine_node_count(rig.engine) == len(graph.nodes())
    for node in graph.nodes():
        for index, inlet in enumerate(node.info.inlets):
            value, generation = e.ctypes.c_float(), e.ctypes.c_uint64()
            assert e.engine_get_knob(rig.engine, node.id, index, e.ctypes.byref(value), e.ctypes.byref(generation)) == e.OK
            assert value.value == e.float32(node.knobs[inlet["key"]]), (node, inlet["key"])
    listed = []
    for index in range(e.engine_boundary_count(rig.engine)):
        name, length, kind, node_id = e.ctypes.create_string_buffer(64), e.ctypes.c_int32(), e.ctypes.c_int32(), e.ctypes.c_int64()
        assert e.engine_boundary_at(rig.engine, index, name, 64, e.ctypes.byref(length), e.ctypes.byref(kind), e.ctypes.byref(node_id)) == e.OK
        listed.append((name.value.decode(), "inlet" if kind.value == e.BOUNDARY_INLET else "outlet", node_id.value))
    assert listed == [tuple(b) for b in graph.boundary_nodes()]
    rig.close()


def test_py_a_boundary_value_reaches_a_boundary_outlet_through_a_graph_made_by_the_model_and_a_missing_wav_is_silent_and_flagged():
    rig = e.Rig(*graph_dll.python_types(), test_nodes=True)
    graph = Graph(types=CATALOG)
    level = graph.add("boundary_inlet", name="level")
    result = graph.add("boundary_outlet", name="result")
    graph.connect(level.outlet("out"), result.inlet("in"))
    song = graph.add("file_read", path="C:/definitely/not/here.wav")
    silent = graph.add("boundary_outlet", name="silent")
    graph.connect(song.outlet("left"), silent.inlet("in"))
    loose = graph.add("boundary_outlet", name="from_knob")
    loose.set_knob("in", -0.5)
    status, text = graph_dll.compile_in(rig, graph)
    assert status == e.OK, text
    rig.instance = e.engine_new_instance(rig.engine)
    assert e.engine_set_boundary(rig.engine, b"level", 0.7) == e.OK
    assert e.instance_read_at(rig.instance, b"result", 5) == e.float32(0.7)
    assert e.instance_read_at(rig.instance, b"silent", 5) == 0.0
    assert e.instance_read_at(rig.instance, b"from_knob", 5) == -0.5
    buffer, length = e.ctypes.create_string_buffer(200), e.ctypes.c_int32()
    assert e.engine_node_message(rig.engine, song.id, buffer, 200, e.ctypes.byref(length)) == e.OK
    assert "file not found" in buffer.value.decode(), buffer.value
    rig.close()


def test_py_what_the_model_calls_a_boundary_name_fault_the_engine_refuses_to_compile_with_the_same_words():
    for build in (lambda g: (g.add("boundary_inlet", name="ok"), g.add("boundary_outlet")),
                  lambda g: (g.add("boundary_inlet", name="x"), g.add("boundary_outlet", name="x")),
                  lambda g: (g.add("boundary_outlet", name="dup"), g.add("boundary_outlet", name="dup"), g.add("boundary_inlet", name="z")),
                  lambda g: (g.add("boundary_inlet", name="one"), g.add("boundary_inlet", name="two"), g.add("boundary_inlet", name="one")),
                  lambda g: (g.add("boundary_inlet", name="d"), g.add("boundary_inlet", name="d"), g.add("boundary_outlet"))):
        graph = Graph(types=CATALOG)
        build(graph)
        rig = e.Rig(test_nodes=True)
        status, text = graph_dll.compile_in(rig, graph)
        assert status == e.ERR_GRAPH
        try:
            graph.validate()
        except BoundaryError as error:
            assert text == str(error), (text, str(error))
        else:
            raise AssertionError("validate accepted what the engine refused: " + text)
        rig.close()


def test_py_absolute_paths_are_drive_paths_and_network_paths_and_nothing_else():
    for path in ("C:/x.wav", "C:\\x.wav", "c:/", "Z:\\", "\\\\server\\share\\x.wav", "//server/share/x.wav", "\\/server/x.wav", "/\\server/x.wav", "//", "\\\\"):
        assert _values.is_absolute_path(path), path
    for path in ("", "x.wav", "dir/x.wav", "./x.wav", "..\\x.wav", "\\x.wav", "/x.wav", "C:x.wav", "C:", "C", "1:/x.wav", ":/x.wav", "\u00e9:/x.wav",
                 " C:/x.wav", "CC:/x.wav", "\\", "/", "file:///x.wav"):
        assert not _values.is_absolute_path(path), path


def test_py_the_models_idea_of_an_absolute_path_is_the_file_nodes():
    paths = ["C:/x.wav", "C:\\x.wav", "c:/x.wav", "x.wav", "dir/x.wav", "dir\\x.wav", "./x.wav", "..\\x.wav", "\\x.wav", "/x.wav", "C:x.wav", "C:",
             "1:/x.wav", ":/x.wav", "\u00e9:/x.wav", "C", "\\", "/",
             "\\\\localhost\\c$\\x.wav", "//localhost/c$/x.wav", "\\/localhost/c$/x.wav", "/\\localhost/c$/x.wav"]
    # (the network paths name this machine: measured here, Windows answers for them in about 1 ms; a path to a host that does not exist takes a
    # full second, so none is used)
    for path in paths:
        graph = Graph(types=CATALOG)
        graph.add("file_read")
        rig = e.Rig(test_nodes=True)
        node = graph.node(1)
        modeled = _values.is_absolute_path(path)
        if modeled:
            node.set("path", path)
        else:
            refuses(lambda: node.set("path", path), "absolute")
            node._settings["path"] = path                                                    # (put it there anyway, to ask the engine)
        status, text = graph_dll.compile_in(rig, graph)
        assert status == e.OK, text
        buffer, length = e.ctypes.create_string_buffer(300), e.ctypes.c_int32()
        assert e.engine_node_message(rig.engine, 1, buffer, 300, e.ctypes.byref(length)) == e.OK
        said_relative = "must be absolute" in buffer.value.decode("utf-8", "replace")
        assert said_relative == (not modeled), (path, modeled, buffer.value)
        rig.close()


def random_graph(rng, serial):
    graph = Graph(types=CATALOG)
    graph.loop_protection = rng.random() < 0.7
    for _ in range(rng.randint(1, 12)):
        key = rng.choice(["py.mixer", "py.versioned", "boundary_inlet", "boundary_outlet", "file_read", "realtime_preview", "test_filter"])
        info = CATALOG.get(key)
        settings = {}
        for desc in info.settings:
            kind, name = desc["kind"], desc["key"]
            if name != "name" and rng.random() < 0.5:                                  # (a boundary node always gets its own name)
                continue
            if name == "name":
                settings[name] = f"b{serial}_{len(graph.nodes())}"
            elif kind == "int":
                settings[name] = rng.randint(1, 384000) if name == "internal_sampling_rate" else rng.randint(-2 ** 63, 2 ** 63 - 1)
            elif kind == "float":
                settings[name] = rng.choice([0.0, -0.0, 1e300, -1e-300, rng.uniform(-100, 100)])
            elif kind == "choice":
                settings[name] = rng.choice(desc["choices"])
            elif kind == "path":
                settings[name] = rng.choice(["", "C:/a/b.wav", "C:\\x\\\u00e9.wav"])
            else:
                settings[name] = "".join(rng.choice("ab \u00e9\u4e2d\U0001f600\"\\") for _ in range(rng.randint(0, 8)))
        node = graph.add(key, x=rng.uniform(-500, 500), y=rng.randint(-9, 9), **settings)
        for inlet in info.inlets:
            if rng.random() < 0.5:
                node.set_knob(inlet["key"], rng.choice([-1.0, 1.0, 0.0, rng.uniform(-1, 1)]))
    nodes = graph.nodes()
    for _ in range(rng.randint(0, 25)):
        source, target = rng.choice(nodes), rng.choice(nodes)
        if source.info.outlets and target.info.inlets:
            try:
                graph.connect(source.outlet(rng.choice(source.info.outlets)["key"]), target.inlet(rng.choice(target.info.inlets)["key"]))
            except GraphError:
                pass
    return graph


def test_py_random_graphs_survive_json_unchanged_and_the_engine_compiles_every_one_the_model_makes():
    rng = random.Random(81)
    compiled = 0
    for serial in range(120):
        graph = random_graph(rng, serial)
        saved = graph.to_dict()
        back = Graph.from_dict(json.loads(json.dumps(saved)), types=CATALOG)
        assert back.to_dict() == saved and back.loop_protection == graph.loop_protection
        assert [b for b in back.boundary_nodes()] == [b for b in graph.boundary_nodes()]
        rig = e.Rig(*graph_dll.python_types(), test_nodes=True)
        status, text = graph_dll.compile_in(rig, graph)
        assert status == e.OK, ascii((serial, text, saved))
        compiled += 1
        assert e.engine_node_count(rig.engine) == len(graph.nodes())
        rig.close()
    assert compiled == 120


def test_py_the_package_exports_what_design_section_15_names():
    assert canopysynth.Graph is Graph and canopysynth.GraphError is GraphError
    assert issubclass(GraphError, Exception)
    try:
        canopysynth.register_migration("file_read", 1)                                # it reaches the default catalog: its types are at version 1
    except ValueError as error:
        assert "file_read" in str(error) and "from 1 to 0" in str(error)
    else:
        raise AssertionError("a migration from the current version was accepted")
    graph = canopysynth.Graph()                                                     # the design's snippet, with the built-in types
    song = graph.add("file_read", path="C:/audio/song.wav")
    left = graph.add("boundary_outlet", name="song_left")
    level = graph.add("boundary_inlet", name="intensity")
    graph.connect(song.outlet("left"), left.inlet("in"))
    graph.loop_protection = True
    d = graph.to_dict()
    assert canopysynth.Graph.from_dict(d, base_dir=None).to_dict() == d
    assert level.id == 3 and [b.name for b in graph.boundary_nodes()] == ["intensity", "song_left"]
