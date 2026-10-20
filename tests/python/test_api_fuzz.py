# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests (plan step 13, error behaviours): the public Python API (Graph, Node, Port, Engine, Instance and the helpers) called with garbage as well as with
good arguments, in random order, against a live engine with its audio on the null backend. The rule it checks (design sections 14 to 16: faults are GraphError,
BoundaryError and QueryError with a sentence that names the fault): a call either does what it says or raises one of the documented exceptions, never any
other kind (an AttributeError, a ctypes ArgumentError, a KeyError...), never crashes the process, and leaves the graph, the engine and the instances usable;
and when everything is closed nothing the engine allocated is left. A saved graph that is damaged in a random place must be refused with a GraphError or be a
graph that saves again to the same text and that the engine accepts (the model's promise: what it stores, the engine compiles).
The seeds are fixed; CANOPY_API_FUZZ_OPS (default 3000) and CANOPY_API_FUZZ_DICTS (default 2500) set how many calls and damaged files a run makes."""
import copy
import json
import math
import os
import random
import tempfile
import traceback

import canopysynth
import engine_dll as e
from canopysynth import BoundaryError, Engine, Graph, GraphError, QueryError
from test_fileread import write_wav

DOCUMENTED = (GraphError, BoundaryError, QueryError, ValueError, RuntimeError, MemoryError, OverflowError)
BOUNDARY_TYPE_ERROR = "a boundary value is a number"                  # the one TypeError the API raises on purpose (plan step 9, decision 3)


def documented(error):
    return isinstance(error, DOCUMENTED) or (isinstance(error, TypeError) and str(error).startswith(BOUNDARY_TYPE_ERROR))
NAN, INF = float("nan"), float("inf")

GARBAGE = [None, True, False, 0, 1, -1, 7, 2 ** 31, 2 ** 32 + 5, 2 ** 63, -2 ** 63 - 1, 2 ** 64 + 5, 10 ** 40, 0.0, -0.0, 0.5, 1.5, -1.5, NAN, INF, -INF, 1e308,
           "", "x", "y", "out", "in", "name", "path", "play", "open", "device", "a" * 300, "\0", "a\0b", "é中", "\ud800", b"x", bytearray(b"x"), [], [1, 2],
           (), (1, "out"), {}, {"a": 1}, object(), len, range(3), Graph, int, slice(1, 2)]
TYPE_KEYS = ["boundary_inlet", "boundary_outlet", "file_read", "realtime_preview"]
SETTING_KEYS = {"boundary_inlet": ["name"], "boundary_outlet": ["name"], "file_read": ["path"], "realtime_preview": ["device"]}
NAMES = ["x", "y", "z", "", "a" * 300, "é中", "x y", "X"]


class World:
    """A graph with one of each kind of node, an engine over it (audio on the null backend), an instance, files to point file nodes at."""

    def __init__(self, directory):
        self.directory = directory
        self.wav = os.path.join(directory, "good.wav")
        write_wav(self.wav, 1, 16, 2, 8000, b"".join(bytes([k % 256, k // 256 % 128]) * 2 for k in range(4000)))
        self.not_wav = os.path.join(directory, "text.wav")
        with open(self.not_wav, "w") as handle:
            handle.write("not a wav file")
        self.paths = [self.wav, self.not_wav, os.path.join(directory, "missing.wav"), directory, "", "relative.wav", "C:rel.wav"]
        self.graph = Graph()
        self.make_basic()
        self.engine = Engine(self.graph)
        self.engine.set_audio_backend("null")
        self.instances = [self.engine.new_instance()]
        self.old_nodes = []                                  # nodes that were removed (stale handles)
        self.foreign = Graph()
        self.foreign_node = self.foreign.add("boundary_outlet", name="foreign")

    def make_basic(self):
        graph = self.graph
        x = graph.add("boundary_inlet", name="x")
        y = graph.add("boundary_outlet", name="y")
        graph.connect(x.outlet("out"), y.inlet("in"))
        song = graph.add("file_read", path=self.wav)
        left = graph.add("boundary_outlet", name="left")
        graph.connect(song.outlet("left"), left.inlet("in"))
        graph.add("realtime_preview")

    def close(self):
        for instance in self.instances:
            instance.close()
        self.engine.close()


# ---- the arguments: good ones, wrong ones and garbage ----

def garbage(rng):
    return rng.choice(GARBAGE)


def node_arg(world, rng):
    roll = rng.random()
    nodes = world.graph.nodes()
    if roll < 0.7 and nodes:
        return rng.choice(nodes)
    if roll < 0.8 and world.old_nodes:
        return rng.choice(world.old_nodes)
    if roll < 0.85:
        return world.foreign_node
    return garbage(rng)


def receiver_arg(world, rng):
    """A Node to call a method of (a method of garbage is not the API's to refuse): a live one, a removed one, one of another graph."""
    roll = rng.random()
    nodes = world.graph.nodes()
    if roll < 0.8 and nodes:
        return rng.choice(nodes)
    if roll < 0.9 and world.old_nodes:
        return rng.choice(world.old_nodes)
    return world.foreign_node


def node_id_arg(world, rng):
    roll = rng.random()
    nodes = world.graph.nodes()
    if roll < 0.6 and nodes:
        return rng.choice(nodes).id
    if roll < 0.7:
        return rng.choice([0, -1, 10 ** 6, 2 ** 63 - 1, -2 ** 63])
    return garbage(rng)


def port_arg(world, rng, kind):
    nodes = world.graph.nodes()
    if rng.random() < 0.75 and nodes:
        node = rng.choice(nodes)
        keys = node.info.inlet if kind == "inlet" else node.info.outlet
        if keys:
            key = rng.choice(list(keys))
            return node.inlet(key) if kind == "inlet" else node.outlet(key)
    if rng.random() < 0.3:
        return world.foreign_node.outlet("out") if kind == "outlet" else world.foreign_node.inlet("in")
    return garbage(rng)


def key_arg(rng, node, which):
    """A key of the node's settings ('setting'), inlets ('inlet') or outlets ('outlet'), or a wrong one."""
    if isinstance(node, canopysynth.Node) and rng.random() < 0.75:
        keys = {"setting": node.settings, "inlet": node.info.inlet, "outlet": node.info.outlet}[which]
        if keys:
            return rng.choice(list(keys))
    return garbage(rng)


def setting_value(world, rng, node):
    roll = rng.random()
    if roll < 0.55 and isinstance(node, canopysynth.Node):
        if node.type in ("boundary_inlet", "boundary_outlet"):
            return rng.choice(NAMES)
        if node.type == "file_read":
            return rng.choice(world.paths)
        return rng.choice(["(system default)", "", "no such device", "NULL Playback Device"])
    return garbage(rng)


def number_arg(rng):
    roll = rng.random()
    if roll < 0.45:
        return rng.uniform(-1, 1)
    if roll < 0.6:
        return rng.choice([-1, 1, 0, -1.0, 1.0, 0.5])
    if roll < 0.75:
        return rng.choice([1.0000001, -1.0000001, 2, -2, 1e300, 5])
    return garbage(rng)


def name_arg(world, rng):
    if rng.random() < 0.6:
        names = [b.name for b in world.graph.boundary_nodes()] or ["x"]
        return rng.choice(names)
    if rng.random() < 0.5:
        return rng.choice(NAMES + ["left", "foreign"])
    return garbage(rng)


def time_arg(rng):
    roll = rng.random()
    if roll < 0.55:
        return rng.randint(-10 ** 9, 10 ** 9)
    if roll < 0.7:
        return rng.choice([2 ** 63 - 1, -2 ** 63, 2 ** 40, 0])
    return garbage(rng)


def count_arg(rng):
    roll = rng.random()
    if roll < 0.55:
        return rng.randint(1, 300)
    if roll < 0.7:
        return rng.choice([0, 1, 65536, 65537, -1])
    return garbage(rng)


# ---- the calls ----

def op_add(world, rng):
    type_key = rng.choice(TYPE_KEYS) if rng.random() < 0.85 else garbage(rng)
    settings = {}
    for _ in range(rng.choice([0, 0, 1, 2])):
        keys = (SETTING_KEYS.get(type_key, ["name"]) if isinstance(type_key, str) else ["name"]) + ["nonsense"]
        key = rng.choice(keys)
        settings[key] = rng.choice(NAMES) if key == "name" and rng.random() < 0.7 else (rng.choice(world.paths) if key == "path" and rng.random() < 0.7 else garbage(rng))
    extra = {}
    if rng.random() < 0.15:
        extra = {"x": garbage(rng) if rng.random() < 0.5 else rng.uniform(-100, 100), "y": garbage(rng) if rng.random() < 0.5 else rng.uniform(-100, 100)}
    world.graph.add(type_key, **settings, **extra)


def op_remove(world, rng):
    node = node_arg(world, rng)
    world.graph.remove(node)
    if isinstance(node, canopysynth.Node):
        world.old_nodes.append(node)


def op_connect(world, rng):
    world.graph.connect(port_arg(world, rng, "outlet"), port_arg(world, rng, "inlet"))


def op_can_connect(world, rng):
    reason = world.graph.can_connect(port_arg(world, rng, "outlet"), port_arg(world, rng, "inlet"))       # never raises
    assert reason is None or isinstance(reason, str)


def op_disconnect(world, rng):
    world.graph.disconnect(port_arg(world, rng, "outlet"), port_arg(world, rng, "inlet"))


def op_connection_into(world, rng):
    world.graph.connection_into(port_arg(world, rng, "inlet"))


def op_node_set(world, rng):
    node = receiver_arg(world, rng)
    node.set(key_arg(rng, node, "setting"), setting_value(world, rng, node))


def op_node_set_knob(world, rng):
    node = receiver_arg(world, rng)
    node.set_knob(key_arg(rng, node, "inlet"), number_arg(rng))


def op_node_ports(world, rng):
    node = receiver_arg(world, rng)
    node.inlet(key_arg(rng, node, "inlet"))
    node.outlet(key_arg(rng, node, "outlet"))


def op_node_xy(world, rng):
    node = receiver_arg(world, rng)
    if rng.random() < 0.5:
        node.x = number_arg(rng)
    else:
        node.y = number_arg(rng)


def op_graph_misc(world, rng):
    roll = rng.randrange(6)
    if roll == 0:
        world.graph.loop_protection = rng.choice([True, False, garbage(rng)])
    elif roll == 1:
        world.graph.node(node_id_arg(world, rng))
    elif roll == 2:
        world.graph.validate()
    elif roll == 3:
        world.graph.has_loop()
        world.graph.connections()
    elif roll == 4:
        repr(node_arg(world, rng))
        world.graph.boundary_nodes()
    else:
        Graph.from_dict(garbage(rng))


def op_update(world, rng):
    world.engine.update()


def op_engine_set_knob(world, rng):
    node_id = node_id_arg(world, rng)
    node = world.graph._nodes.get(node_id) if isinstance(node_id, int) and not isinstance(node_id, bool) else None
    world.engine.set_knob(node_id, key_arg(rng, node, "inlet") if node is not None else garbage(rng), number_arg(rng))


def op_engine_action(world, rng):
    action = rng.choice(["open", "play", "pause", "device", "nonsense"]) if rng.random() < 0.8 else garbage(rng)
    world.engine.action(node_id_arg(world, rng), action)


def op_engine_node_info(world, rng):
    node_id = node_id_arg(world, rng)
    roll = rng.randrange(5)
    if roll == 0:
        world.engine.node_message(node_id)
    elif roll == 1:
        world.engine.preview_state(node_id)
    elif roll == 2:
        world.engine.preview_set_time(node_id, time_arg(rng))
    elif roll == 3:
        world.engine.preview_warning(node_id)
    else:
        world.engine.collect()


def op_engine_boundary(world, rng):
    roll = rng.randrange(4)
    if roll == 0:
        world.engine.set_boundary(name_arg(world, rng), number_arg(rng) if rng.random() < 0.7 else rng.choice([NAN, INF, -INF, 1e300, 1e308 * 10]))
    elif roll == 1:
        world.engine.boundary_nodes()
    elif roll == 2:
        world.engine.set_audio_backend(rng.choice(["null", None, 1, "NULL", ""]))               # (never "system": a Play would open the real device)
    else:
        world.engine.audio_devices()


def op_instance_query(world, rng):
    instance = rng.choice(world.instances)
    if rng.random() < 0.4:
        instance.value(name_arg(world, rng), time_arg(rng))
    else:
        instance.audio(name_arg(world, rng), time_arg(rng), time_arg(rng), count_arg(rng))


def op_instances(world, rng):
    if len(world.instances) < 4 and rng.random() < 0.6:
        world.instances.append(world.engine.new_instance())
    elif len(world.instances) > 1:
        world.instances.pop(rng.randrange(len(world.instances))).close()


def op_helpers(world, rng):
    helper = rng.choice([canopysynth.ns_to_frame, canopysynth.ns_to_frame_fraction])
    helper(time_arg(rng), rng.choice([1, 48000, 9223372036, 9223372037, 0, -5]) if rng.random() < 0.6 else garbage(rng))


OPS = [(op_add, 8), (op_remove, 4), (op_connect, 10), (op_can_connect, 4), (op_disconnect, 3), (op_connection_into, 2), (op_node_set, 10), (op_node_set_knob, 4),
       (op_node_ports, 3), (op_node_xy, 3), (op_graph_misc, 5), (op_update, 5), (op_engine_set_knob, 5), (op_engine_action, 8), (op_engine_node_info, 8),
       (op_engine_boundary, 8), (op_instance_query, 12), (op_instances, 3), (op_helpers, 4)]
CHOICES = [op for op, weight in OPS for _ in range(weight)]


def check_consistent(world):
    """What must hold after any sequence of calls: the graph saves and loads to the same text, and the engine and its instances still answer."""
    saved = world.graph.to_dict()
    json.dumps(saved)                                                                  # plain data: JSON-safe
    assert Graph.from_dict(saved).to_dict() == saved
    world.engine.boundary_nodes()
    world.engine.collect()
    for instance in world.instances:
        for b in world.engine.boundary_nodes():
            if b.kind == "outlet":
                try:
                    instance.value(b.name, 0)
                except QueryError:
                    pass
                break


def settle(world):
    """Gives every boundary node whose name is empty or used twice a name of its own, installs the graph (it must compile: what the model stores, the engine
    accepts) and checks that the engine's list of boundary nodes is the model's, name for name."""
    seen = set()
    for node in world.graph.nodes():
        if node.type in ("boundary_inlet", "boundary_outlet"):
            name = node.settings["name"]
            if name == "" or name in seen:
                node.set("name", f"fixed{node.id}")
            seen.add(node.settings["name"])
    world.engine.update()
    assert world.engine.boundary_nodes() == world.graph.boundary_nodes()


def run_ops(seed, count, directory):
    rng = random.Random(seed)
    world = World(directory)
    escaped, seen = [], {}
    try:
        for step in range(count):
            op = rng.choice(CHOICES)
            try:
                op(world, rng)
            except Exception as error:                                               # noqa: BLE001 - sorted below
                if documented(error):
                    seen[(op.__name__, type(error).__name__)] = seen.get((op.__name__, type(error).__name__), 0) + 1
                else:
                    escaped.append((step, op.__name__, type(error).__name__, str(error)[:120], traceback.format_exc().splitlines()[-3:-1]))
            if step % 40 == 39:
                check_consistent(world)
            if step % 400 == 399:
                settle(world)
        settle(world)
        check_consistent(world)
    finally:
        world.close()
    return escaped, seen


# ---- damaged files ----

def slots(tree, path=()):
    """Every (container, key) in a tree of dicts and lists."""
    found = []
    if isinstance(tree, dict):
        for key in list(tree):
            found.append((tree, key))
            found += slots(tree[key], path + (key,))
    elif isinstance(tree, list):
        for index in range(len(tree)):
            found.append((tree, index))
            found += slots(tree[index], path + (index,))
    return found


JSON_GARBAGE = [None, True, False, 0, 1, -1, 2 ** 63, -2 ** 63 - 1, 10 ** 40, 0.5, 1e400, "", "x", "out", "a" * 100, "\0", "\ud800", [], [1], [1, "out"], ["x"],
                {}, {"a": 1}, [[]], 1.5, -0.0, NAN, INF]


def damage(rng, data):
    for _ in range(rng.choice([1, 1, 2, 3])):
        found = slots(data)
        container, key = rng.choice(found)
        roll = rng.random()
        if roll < 0.45:
            container[key] = copy.deepcopy(rng.choice(JSON_GARBAGE))                  # (a copy: the pool's own lists and dicts are never put into the data and then changed)
        elif roll < 0.6 and isinstance(container, dict):
            del container[key]
        elif roll < 0.7 and isinstance(container, list):
            container.pop(key)
        elif roll < 0.8:
            container[key] = copy.deepcopy(rng.choice(found)[0])                   # a whole other part of the file in this place
        elif roll < 0.9 and isinstance(container, dict):
            container[rng.choice(["extra", "id", "type", "name", 3])] = copy.deepcopy(rng.choice(JSON_GARBAGE))
        else:
            container[key] = [container[key]]                                        # one level deeper
    return data


def run_dicts(seed, count, directory):
    rng = random.Random(seed)
    world = World(directory)
    base = world.graph.to_dict()
    world.close()
    escaped, accepted, refused = [], 0, 0
    for step in range(count):
        data = damage(rng, copy.deepcopy(base))
        before = copy.deepcopy(data)
        try:
            graph = Graph.from_dict(data)
        except GraphError:
            refused += 1
            assert data == before or repr(data) == repr(before)                       # the dict handed in is not changed
            continue
        except BaseException as error:                                               # noqa: BLE001
            escaped.append((step, type(error).__name__, str(error)[:120], traceback.format_exc().splitlines()[-3:-1]))
            continue
        accepted += 1
        try:
            saved = graph.to_dict()
            json.dumps(saved, allow_nan=False)
            assert Graph.from_dict(saved).to_dict() == saved
            try:
                Engine(graph).close()                                                # what the model stores, the engine compiles (boundary names apart)
            except BoundaryError:
                pass
        except BaseException as error:                                               # noqa: BLE001
            escaped.append((step, "after loading: " + type(error).__name__, str(error)[:120], traceback.format_exc().splitlines()[-3:-1]))
    return escaped, accepted, refused


def report(escaped):
    return "\n".join(str(item) for item in escaped[:8])


def test_py_random_calls_with_garbage_arguments_raise_only_documented_exceptions_and_leave_everything_usable():
    ops = int(os.environ.get("CANOPY_API_FUZZ_OPS", "3000"))
    base = e.alloc_live()
    for seed in (1, 2, 3):
        with tempfile.TemporaryDirectory() as directory:
            escaped, seen = run_ops(20261006 + seed, ops, directory)
        assert not escaped, f"seed {seed}: {len(escaped)} calls raised something undocumented:\n" + report(escaped)
        assert len(seen) > 20, sorted(seen)                                          # (the garbage does reach the checks: many different refusals)
    assert e.alloc_live() == base, "something the engine allocated was not freed"


def test_py_saved_graphs_damaged_in_random_places_are_refused_with_graph_error_or_are_graphs_the_engine_accepts():
    count = int(os.environ.get("CANOPY_API_FUZZ_DICTS", "2500"))
    base = e.alloc_live()
    with tempfile.TemporaryDirectory() as directory:
        escaped, accepted, refused = run_dicts(77, count, directory)
    assert not escaped, f"{len(escaped)} damaged files raised something other than GraphError:\n" + report(escaped)
    assert refused > count // 3 and accepted >= count // 100, (accepted, refused)    # (both outcomes happen: the damage is neither always fatal nor always harmless)
    assert e.alloc_live() == base, "something the engine allocated was not freed"
