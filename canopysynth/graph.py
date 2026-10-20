# SPDX-License-Identifier: GPL-3.0-or-later
"""The graph model (design sections 14 and 15): nodes, connections, settings and knobs as plain Python data, and the saved form.

A Graph knows nothing about the engine or the DLL: it is the thing the editor edits, the host stores (`to_dict()` / `Graph.from_dict(d)`)
and the engine compiles. Everything is named by permanent string keys (node type, inlet, outlet, setting); node IDs are whole numbers that
are never reused while the Graph object lives. Faults are GraphError (BoundaryError for boundary names), with a message that names the node and the key.

What a Graph guarantees at every moment: every node has a known type; every setting and knob has a valid value; no inlet has two connections
(fan-in is impossible); and, while `loop_protection` is on, no loop. What it leaves to the engine's compile (as design section 16 says):
boundary names that are empty or used twice (a graph being edited may pass through such a state; `validate()` reports it)."""
import copy
import weakref
from collections import namedtuple
from types import MappingProxyType

from . import _values
from .catalog import default_types
from .errors import BoundaryError, GraphError

FORMAT = "canopysynth-graph"
VERSION = 1

BOUNDARY_KINDS = {"boundary_inlet": "inlet", "boundary_outlet": "outlet"}      # type key -> kind, as BoundaryInfo.kind says
BOUNDARY_NAME = "name"

Connection = namedtuple("Connection", "outlet inlet")
Connection.__doc__ = "A connection: `outlet` and `inlet` are the two Ports."
BoundaryInfo = namedtuple("BoundaryInfo", "name kind node_id")
BoundaryInfo.__doc__ = "A boundary node: its name, its kind ('inlet': the host writes it; 'outlet': the host reads it) and its node ID."

_NODE_KEYS = {"id", "type", "type_version", "x", "y", "settings", "knobs"}
_TOP_KEYS = {"format", "version", "loop_protection", "nodes", "connections"}


class Port:
    """One inlet or outlet of a node, made by `node.inlet(key)` / `node.outlet(key)`; what `Graph.connect` takes."""
    __slots__ = ("node", "key", "kind")

    def __init__(self, node, key, kind):
        self.node, self.key, self.kind = node, key, kind

    def __eq__(self, other):
        return isinstance(other, Port) and self.node is other.node and self.key == other.key and self.kind == other.kind

    def __hash__(self):
        return hash((id(self.node), self.key, self.kind))

    def __repr__(self):
        return f"<{self.kind} {self.key!r} of node {self.node.id}>"


class Node:
    """A node of a graph. Made by `Graph.add`. `settings` and `knobs` are read-only views of the current values (every setting and every
    inlet is always present, at its default until changed); change them with `set` and `set_knob`."""

    def __init__(self, graph, node_id, info, x, y, settings, knobs):
        self._graph, self._id, self._info, self._x, self._y = graph, node_id, info, x, y
        self._settings, self._knobs = settings, knobs

    def _live(self):
        if self._graph is None:
            raise GraphError(f"node {self._id} ({self._info.key}) was removed from its graph")
        return self._graph

    def _where(self):
        return f"node {self._id} ({self._info.key})"

    @property
    def id(self):
        return self._id

    @property
    def type(self):
        """The node type's permanent key, for example "file_read"."""
        return self._info.key

    @property
    def info(self):
        """The node type's TypeInfo (inlets, outlets, settings, widgets...)."""
        return self._info

    @property
    def graph(self):
        """The Graph the node is in; None once it was removed."""
        return self._graph

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._live()
        self._x = _values.coordinate("x", value, self._where())

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        self._live()
        self._y = _values.coordinate("y", value, self._where())

    @property
    def settings(self):
        return MappingProxyType(self._settings)

    @property
    def knobs(self):
        return MappingProxyType(self._knobs)

    def set(self, key, value):
        """Changes a setting (GraphError for an unknown key or a bad value). A path must be absolute; a choice is its text."""
        self._live()
        self._settings[key] = _values.setting(self._info, key, value, self._where())

    def set_knob(self, inlet_key, value):
        """Moves the knob of an inlet: a number from -1 to 1. (It matters only while the inlet has no connection.)"""
        self._live()
        if not isinstance(inlet_key, str) or inlet_key not in self._info.inlet:
            raise GraphError(f"{self._where()} has no inlet {inlet_key!r}")
        self._knobs[inlet_key] = _values.knob(inlet_key, value, self._where())

    def inlet(self, key):
        self._live()
        if not isinstance(key, str) or key not in self._info.inlet:
            known = ", ".join(repr(k) for k in self._info.inlet) or "none"
            raise GraphError(f"{self._where()} has no inlet {key!r} (its inlets: {known})")
        return Port(self, key, "inlet")

    def outlet(self, key):
        self._live()
        if not isinstance(key, str) or key not in self._info.outlet:
            known = ", ".join(repr(k) for k in self._info.outlet) or "none"
            raise GraphError(f"{self._where()} has no outlet {key!r} (its outlets: {known})")
        return Port(self, key, "outlet")

    def __repr__(self):
        return f"<Node {self._id} {self._info.key}{'' if self._graph is not None else ' (removed)'}>"


class Graph:
    """A graph of nodes and connections. `types` is the catalog of node types it may name (default: the built-in ones)."""

    def __init__(self, *, types=None):
        self._types = types if types is not None else default_types()
        self._nodes = {}                    # node ID -> Node
        self._links = {}                    # (to node ID, inlet key) -> (from node ID, outlet key)
        self._next_id = 1
        self._loop_protection = True
        self._engines = weakref.WeakSet()           # the Engines made over this graph (see `engines`)

    @property
    def types(self):
        return self._types

    def engines(self):
        """The open Engines made over this Graph (`Engine(graph)`), as a list. An editor of the graph keeps them up to date: it recompiles after
        every edit that changes what an engine compiles, moves knobs live and sends buttons to them (design section 15)."""
        return [engine for engine in self._engines if not engine.closed]

    # ---- loop protection ----

    @property
    def loop_protection(self):
        """True (the default): a connection that would close a loop is refused. Saved with the graph."""
        return self._loop_protection

    @loop_protection.setter
    def loop_protection(self, value):
        if not isinstance(value, bool):
            raise GraphError(f"loop_protection must be True or False, not {value!r}")
        if value and self.has_loop():
            raise GraphError("loop protection cannot be turned on while the graph contains a loop: remove a connection of the loop first")
        self._loop_protection = value

    def _edges(self):
        """The connections as (from node ID, to node ID), one per connection."""
        return [(source, target) for (target, _inlet), (source, _outlet) in self._links.items()]

    def _reaches(self, start, goal):
        """True if `goal` can be reached from `start` by following connections forward (a node reaches itself)."""
        follow = {}
        for source, target in self._edges():
            follow.setdefault(source, []).append(target)
        seen, pending = {start}, [start]
        while pending:
            here = pending.pop()
            if here == goal:
                return True
            for there in follow.get(here, ()):
                if there not in seen:
                    seen.add(there)
                    pending.append(there)
        return False

    def has_loop(self):
        """True if some chain of connections leads from a node back to itself."""
        edges = self._edges()
        waiting = {node_id: 0 for node_id in self._nodes}
        follow = {}
        for source, target in edges:
            waiting[target] += 1
            follow.setdefault(source, []).append(target)
        ready = [node_id for node_id, count in waiting.items() if count == 0]
        done = 0
        while ready:
            here = ready.pop()
            done += 1
            for there in follow.get(here, ()):
                waiting[there] -= 1
                if waiting[there] == 0:
                    ready.append(there)
        return done < len(self._nodes)

    # ---- nodes ----

    def nodes(self):
        """The nodes, in order of node ID."""
        return [self._nodes[node_id] for node_id in sorted(self._nodes)]

    def node(self, node_id):
        """The node with this ID; GraphError if there is none."""
        node = self._nodes.get(node_id) if _values.is_int(node_id) else None
        if node is None:
            raise GraphError(f"the graph has no node {node_id!r}")
        return node

    def add(self, type_key, /, *, x=0, y=0, **settings):
        """Adds a node of the type with this key and returns it. `x` and `y` are its canvas position; every other keyword is one of the
        type's settings (`graph.add("file_read", path="C:/audio/song.wav")`; a type with a setting called x or y sets it with `node.set`).
        GraphError for a type that is not installed or a bad setting; nothing is added then."""
        info = self._types.get(type_key) if isinstance(type_key, str) else None
        if info is None:
            raise GraphError(f"the node type {type_key!r} is not installed")
        if self._next_id > _values.INT64_MAX:
            raise GraphError("the graph has used every node ID that fits in 64 bits")
        where = f"a new node ({type_key})"
        values = {key: _values.setting(info, key, value, where) for key, value in settings.items()}
        return self._make(self._next_id, info, _values.coordinate("x", x, where), _values.coordinate("y", y, where), values, {})

    def _make(self, node_id, info, x, y, settings, knobs):
        """Puts a node in the graph: the given settings and knobs (already checked) over the type's defaults."""
        all_settings = dict(info.defaults)
        all_settings.update(settings)
        all_knobs = {i["key"]: i["default_knob"] for i in info.inlets}
        all_knobs.update(knobs)
        node = Node(self, node_id, info, x, y, all_settings, all_knobs)
        self._nodes[node_id] = node
        self._next_id = max(self._next_id, node_id + 1)
        return node

    def remove(self, node):
        """Removes a node and every connection that touches it. Its ID is not used again."""
        if not isinstance(node, Node) or node._graph is not self:
            raise GraphError(f"{node!r} is not a node of this graph")
        node_id = node._id
        for link in [k for k, v in self._links.items() if k[0] == node_id or v[0] == node_id]:
            del self._links[link]
        del self._nodes[node_id]
        node._graph = None

    # ---- connections ----

    def _own_port(self, port, kind, role):
        if not isinstance(port, Port):
            raise GraphError(f"connect expects an {role}, made by node.{role}(key), not {port!r}")
        if port.kind != kind:
            raise GraphError(f"connect(outlet, inlet): the {role} argument is {port!r}, which is an {port.kind}")
        if port.node._graph is not self:
            raise GraphError(f"{port!r} does not belong to this graph")

    def connect(self, outlet, inlet):
        """Connects an outlet to an inlet and returns the Connection. An outlet may feed any number of inlets; an inlet takes only one
        connection (GraphError if it has one already). While `loop_protection` is on, a connection that would close a loop is refused."""
        self._own_port(outlet, "outlet", "outlet")
        self._own_port(inlet, "inlet", "inlet")
        reason = self._refusal(outlet, inlet)
        if reason is not None:
            raise GraphError(reason)
        self._links[(inlet.node._id, inlet.key)] = (outlet.node._id, outlet.key)
        return Connection(outlet, inlet)

    def _refusal(self, outlet, inlet):
        """Why `connect` would refuse these two ports of this graph (the sentence of the GraphError), or None if it would not."""
        source_ref = self._links.get((inlet.node._id, inlet.key))
        if source_ref is not None:
            source, key = source_ref
            return (f"{inlet.node._where()}: inlet {inlet.key!r} is already connected (to outlet {key!r} of node {source}); "
                    "an inlet takes one connection")
        if self._loop_protection and self._reaches(inlet.node._id, outlet.node._id):
            return (f"this connection would close a loop (node {inlet.node._id} already leads to node {outlet.node._id}); "
                    "turn loop_protection off to allow loops")
        return None

    def can_connect(self, outlet, inlet):
        """None if `connect(outlet, inlet)` would succeed, else the reason it would refuse, as a sentence (never raises: ports that are not an outlet
        and an inlet of this graph are refused with the sentence `connect` would raise). An editor uses it to show which inlets a connection may go to."""
        try:
            self._own_port(outlet, "outlet", "outlet")
            self._own_port(inlet, "inlet", "inlet")
        except GraphError as error:
            return str(error)
        return self._refusal(outlet, inlet)

    def disconnect(self, outlet, inlet):
        """Removes the connection between this outlet and this inlet; GraphError if there is none."""
        self._own_port(outlet, "outlet", "outlet")
        self._own_port(inlet, "inlet", "inlet")
        target = (inlet.node._id, inlet.key)
        if self._links.get(target) != (outlet.node._id, outlet.key):
            raise GraphError(f"{outlet!r} is not connected to {inlet!r}")
        del self._links[target]

    def connections(self):
        """Every connection, in order of the inlet's node ID and the inlet's place in its node type."""
        order = sorted(self._links, key=lambda link: (link[0], self._nodes[link[0]]._info.inlet_index[link[1]]))
        result = []
        for target, inlet_key in order:
            source, outlet_key = self._links[(target, inlet_key)]
            result.append(Connection(Port(self._nodes[source], outlet_key, "outlet"), Port(self._nodes[target], inlet_key, "inlet")))
        return result

    def connection_into(self, inlet):
        """The Connection that ends at this inlet, or None."""
        self._own_port(inlet, "inlet", "inlet")
        link = self._links.get((inlet.node._id, inlet.key))
        return None if link is None else Connection(Port(self._nodes[link[0]], link[1], "outlet"), inlet)

    # ---- boundary nodes ----

    def boundary_nodes(self):
        """The boundary nodes as BoundaryInfo(name, kind, node_id), sorted by name (byte order of the UTF-8 text, like the engine's list)."""
        found = [BoundaryInfo(node._settings[BOUNDARY_NAME], BOUNDARY_KINDS[node.type], node._id)
                 for node in self._nodes.values() if node.type in BOUNDARY_KINDS]
        return sorted(found, key=lambda b: (b.name.encode("utf-8"), b.node_id))

    def validate(self):
        """Raises BoundaryError for what the engine would refuse to compile and the model allows while editing: a boundary node without a name,
        or two boundary nodes (of either kind) with the same name."""
        first_with = {}
        by_id = sorted(self.boundary_nodes(), key=lambda b: b.node_id)
        for info in by_id:                                  # (the engine looks for a missing name in all nodes before it looks for repeats)
            if info.name == "":
                raise BoundaryError(f"node {info.node_id} ({self._nodes[info.node_id].type}) is a boundary node and needs a name")
        for info in by_id:
            if info.name in first_with:
                raise BoundaryError(f"the boundary name \"{info.name}\" is used by node {first_with[info.name]} and by node {info.node_id}; "
                                 "boundary names must be unique")
            first_with[info.name] = info.node_id

    # ---- saving and loading ----

    def to_dict(self):
        """The graph as a dict of plain data (design section 14), safe to write as JSON and to keep: a new structure each time.
        Nodes are in order of ID; every setting and knob is written out."""
        nodes = []
        for node in self.nodes():
            info = node._info
            nodes.append({"id": node._id, "type": info.key, "type_version": info.type_version, "x": node._x, "y": node._y,
                          "settings": {s["key"]: node._settings[s["key"]] for s in info.settings},
                          "knobs": {i["key"]: node._knobs[i["key"]] for i in info.inlets}})
        connections = [{"from": [c.outlet.node._id, c.outlet.key], "to": [c.inlet.node._id, c.inlet.key]} for c in self.connections()]
        return {"format": FORMAT, "version": VERSION, "loop_protection": self._loop_protection, "nodes": nodes, "connections": connections}

    @classmethod
    def from_dict(cls, data, base_dir=None, *, types=None):
        """A Graph from a dict made by `to_dict` (or written by hand to the same format). `base_dir` is accepted for later versions and not used:
        version 1 has no relative paths. GraphError rejects the whole file for: a wrong format or version; a node type that is not installed
        (and a node saved under a newer type version, or under an older one with no migration up to the current one); an unknown or ill-typed
        setting or knob; a duplicate node ID; a connection to a node or port that is not there, or into an inlet that already has one; and
        a loop when `loop_protection` is on. A WAV file that no longer exists is not checked here (the node is silent and flagged when the
        engine loads it, design section 14). Boundary names are not checked (see `validate`). `data` is not changed."""
        try:
            return cls._load(data, types if types is not None else default_types())
        except GraphError as error:
            raise GraphError(f"cannot load the graph: {error}") from None

    @classmethod
    def _load(cls, data, types):
        _keys(data, _TOP_KEYS, "the graph")
        if data["format"] != FORMAT:
            raise GraphError(f"the format is {data['format']!r}, not {FORMAT!r}")
        if not _values.is_int(data["version"]) or data["version"] < 1:
            raise GraphError(f"the version must be a whole number from 1, not {data['version']!r}")
        if data["version"] > VERSION:
            raise GraphError(f"the file is version {data['version']}, made by a newer canopysynth; this one reads version {VERSION}")
        if not isinstance(data["loop_protection"], bool):
            raise GraphError(f"loop_protection must be true or false, not {data['loop_protection']!r}")
        if not isinstance(data["nodes"], (list, tuple)) or not isinstance(data["connections"], (list, tuple)):
            raise GraphError("nodes and connections must be lists")
        graph = cls(types=types)
        graph._loop_protection = data["loop_protection"]
        renames = {}                                           # node ID -> [(inlet renames, outlet renames), ...] from its migrations
        for entry in data["nodes"]:
            cls._load_node(graph, entry, renames)
        for entry in data["connections"]:
            _keys(entry, {"from", "to"}, "a connection")
            source, outlet_key = _end(entry["from"], "from", renames, 1)
            target, inlet_key = _end(entry["to"], "to", renames, 0)
            if source is None or target is None:               # an end whose port a migration removed: the connection goes with it
                continue
            graph._link(source, outlet_key, target, inlet_key)
        if graph._loop_protection and graph.has_loop():
            raise GraphError("the graph contains a loop but loop_protection is on")
        return graph

    @classmethod
    def _load_node(cls, graph, entry, renames):
        _keys(entry, _NODE_KEYS, "a node")
        node_id = _values.node_id(entry["id"], "a node's id")
        if node_id in graph._nodes:
            raise GraphError(f"the node ID {node_id} is used twice")
        if not isinstance(entry["type"], str):
            raise GraphError(f"node {node_id}: the type must be text, not {entry['type']!r}")
        info = graph._types.get(entry["type"])
        if info is None:
            raise GraphError(f"node {node_id} has the node type {entry['type']!r}, which is not installed")
        where = f"node {node_id} ({info.key})"
        version = entry["type_version"]
        if not _values.is_int(version) or version < 1:
            raise GraphError(f"{where}: type_version must be a whole number from 1, not {version!r}")
        if version > info.type_version:
            raise GraphError(f"{where} was saved under version {version} of its type, newer than the installed version {info.type_version}")
        saved_settings, saved_knobs = entry["settings"], entry["knobs"]
        if not isinstance(saved_settings, dict) or not isinstance(saved_knobs, dict):
            raise GraphError(f"{where}: settings and knobs must be objects")
        if version < info.type_version:
            saved_settings, saved_knobs = copy.deepcopy(saved_settings), copy.deepcopy(saved_knobs)
            for old in range(version, info.type_version):
                migration = graph._types.migration(info.key, old)
                if migration is None:
                    raise GraphError(f"{where} was saved under version {version} of its type and there is no migration from version {old} "
                                     f"to {old + 1} (the installed version is {info.type_version})")
                if migration.upgrade is not None:
                    migration.upgrade(saved_settings, saved_knobs)
                saved_knobs = {migration.inlets.get(key, key): value for key, value in saved_knobs.items()
                               if migration.inlets.get(key, key) is not None}
                renames.setdefault(node_id, []).append((migration.inlets, migration.outlets))
        settings = {key: _values.setting(info, key, value, where) for key, value in saved_settings.items()}
        knobs = {}
        for key, value in saved_knobs.items():
            if key not in info.inlet:
                raise GraphError(f"{where} has no inlet {key!r} for a knob")
            knobs[key] = _values.knob(key, value, where)
        x = _values.coordinate("x", entry["x"], where)
        y = _values.coordinate("y", entry["y"], where)
        graph._make(node_id, info, x, y, settings, knobs)

    def _link(self, source, outlet_key, target, inlet_key):
        """A connection read from a file: checked like `connect` except for loops (the caller checks them once at the end)."""
        for node_id, role in ((source, "from"), (target, "to")):
            if node_id not in self._nodes:
                raise GraphError(f"a connection {role} node {node_id}, which does not exist")
        out_node, in_node = self._nodes[source], self._nodes[target]
        if outlet_key not in out_node._info.outlet:
            raise GraphError(f"a connection from {out_node._where()}, which has no outlet {outlet_key!r}")
        if inlet_key not in in_node._info.inlet:
            raise GraphError(f"a connection to {in_node._where()}, which has no inlet {inlet_key!r}")
        if (target, inlet_key) in self._links:
            raise GraphError(f"{in_node._where()}: inlet {inlet_key!r} has two connections; an inlet takes one")
        self._links[(target, inlet_key)] = (source, outlet_key)


def _keys(obj, wanted, what):
    """`obj` must be a dict with exactly the keys in `wanted`."""
    if not isinstance(obj, dict):
        raise GraphError(f"{what} must be an object, not {obj!r}")
    missing, extra = sorted(wanted - set(obj)), sorted(str(k) for k in set(obj) - wanted)
    if missing:
        raise GraphError(f"{what} lacks: {', '.join(missing)}")
    if extra:
        raise GraphError(f"{what} has unknown entries: {', '.join(extra)}")


def _end(value, role, renames, which):
    """One end of a saved connection, [node ID, port key], with the port renames of the node's migrations applied (which = 0 for inlet
    renames, 1 for outlet renames). Returns (node ID, key), or (None, None) if a migration removed the port."""
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not isinstance(value[1], str):
        raise GraphError(f"a connection's {role!r} must be [node id, port key], not {value!r}")
    node_id, key = _values.node_id(value[0], f"a connection's {role!r} node"), value[1]
    for pair in renames.get(node_id, ()):
        key = pair[which].get(key, key)
        if key is None:
            return None, None
    return node_id, key
