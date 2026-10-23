# SPDX-License-Identifier: GPL-3.0-or-later
"""The Engine and Instance classes (design sections 8, 10, 15 and 16): the bridge between a Graph and the C engine.

    engine = canopysynth.Engine(graph)      # compiles the graph and installs it; GraphError (with the engine's reason) if it cannot
    engine.set_boundary("intensity", 0.7)   # any thread
    engine.action(node_id, "play")          # a button of a node (the editor does this for its buttons); also set_knob, node_message, preview_state...
    inst = engine.new_instance()            # one per querying thread
    inst.value("song_left", t_ns)           # a point query: a float
    inst.audio("song_left", t0, t1, n)      # a span query: a memoryview of n float32 (QueryError on a nonzero status)

Threads: every method of Engine except `update` and `close` may be called from any thread (the C engine takes its lock inside); `update` reads
the Graph, which is not thread-safe, so call it from the thread that edits it. An Instance is for one thread at a time: a second thread using
it at the same moment gets QueryError (status CANOPY_ERR_BUSY). The GIL is released while the C engine works, so queries in several threads
run in parallel. Close the instances before the engine (an Instance keeps its Engine alive, so dropping them in any order is safe too)."""
import array
import ctypes
import threading

from . import _native as native
from . import _values
from .errors import BoundaryError, GraphError, QueryError
from .graph import BoundaryInfo


def _name_bytes(name):
    """A boundary name as UTF-8 for C. A name that cannot be one (not text, a NUL, a lone surrogate) names no boundary node."""
    if not isinstance(name, str):
        raise BoundaryError(f"a boundary name is text, not {name!r}")
    try:
        data = name.encode("utf-8")
    except UnicodeEncodeError:
        raise BoundaryError("there is no boundary node with that name (it is not valid text)") from None
    if b"\0" in data:
        raise BoundaryError(f"there is no boundary node called {name!r}")
    return data


def _time(value, what):
    if not _values.is_int(value) or not native.INT64_MIN <= value <= native.INT64_MAX:
        raise ValueError(f"{what} must be a signed 64-bit integer of nanoseconds, not {value!r}")
    return int(value)


def _check(status):
    """Turns a status of a graph-description call into an exception."""
    if status == native.ERR_MEMORY:
        raise MemoryError("out of memory while describing the graph to the engine")
    if status != native.OK:
        raise GraphError(native.message(status))


def _describe(lib, c_graph, graph):
    """Describes `graph` (a canopysynth.Graph) in the C graph `c_graph`: every node with its settings and knobs, every connection. A choice goes
    by the index of its text; everything else as it is (the engine checks it all again when it compiles)."""
    for node in graph.nodes():
        _check(lib.canopy_graph_add_node(c_graph, node.id, node.type.encode("utf-8")))
        for desc in node.info.settings:
            key, kind, value = desc["key"].encode("utf-8"), desc["kind"], node.settings[desc["key"]]
            if kind == "int":
                _check(lib.canopy_graph_set_int(c_graph, node.id, key, value))
            elif kind == "choice":
                _check(lib.canopy_graph_set_int(c_graph, node.id, key, desc["choices"].index(value)))
            elif kind == "float":
                _check(lib.canopy_graph_set_float(c_graph, node.id, key, value))
            else:
                _check(lib.canopy_graph_set_string(c_graph, node.id, key, value.encode("utf-8")))
        for inlet in node.info.inlets:
            _check(lib.canopy_graph_set_knob(c_graph, node.id, inlet["key"].encode("utf-8"), node.knobs[inlet["key"]]))
    for connection in graph.connections():
        _check(lib.canopy_graph_connect(c_graph, connection.outlet.node.id, connection.outlet.key.encode("utf-8"),
                                        connection.inlet.node.id, connection.inlet.key.encode("utf-8")))


class Engine:
    """Keeps the latest compiled version of a Graph and answers for it. `registry` is for tests and for node types registered in C by a host: a
    pointer from canopy_registry_new that the caller owns and keeps alive for the life of the engine (default: the DLL's built-in node types)."""

    def __init__(self, graph, *, registry=None):
        self._lib = native.dll()
        self._graph = graph
        self._lock = threading.Lock()                      # serialises update and close, and guards the instance count
        self._instances = 0
        self._engine = None
        self._registry = registry
        self._own_registry = registry is None
        if registry is None:
            self._registry = self._lib.canopy_registry_new()
            if not self._registry:
                raise MemoryError("the node-type registry could not be made")
        handle = self._lib.canopy_engine_new(self._registry)
        if not handle:
            self._free_registry()
            raise MemoryError("the engine could not be made")
        self._engine = handle
        try:
            self.update()
        except BaseException:
            self.close()
            raise
        graph._engines.add(self)                           # an editor of this graph finds the engine through it and keeps it up to date

    @property
    def graph(self):
        """The Graph this engine compiles."""
        return self._graph

    @property
    def closed(self):
        """True once `close` has run."""
        return self._engine is None

    def _handle(self):
        if self._engine is None:
            raise RuntimeError("the engine is closed")
        return self._engine

    def _node_status(self, status, node_id, what):
        """Turns the status of a call about one node into an exception (GraphError: the installed graph may be older than the edited one)."""
        if status == native.OK:
            return
        if status == native.ERR_NODE:
            raise GraphError(f"the installed graph has no node {node_id} (it may be older than the one edited: see the last compile error)")
        if status == native.ERR_PORT:
            raise GraphError(f"the installed graph's node {node_id} has no such inlet")
        if status == native.ERR_ARGUMENT:
            raise GraphError(f"{what}: node {node_id} cannot do that ({native.message(status)})")
        raise GraphError(f"{what}: {native.message(status)}")

    def _text(self, function, *args):
        """Calls a C function that copies text into (buffer, capacity, &length) after `args`, asking again with a bigger buffer if it was cut; returns
        (status, the text)."""
        capacity = 256
        while True:
            buffer, length = ctypes.create_string_buffer(capacity), ctypes.c_int32()
            status = function(*args, buffer, capacity, ctypes.byref(length))
            if status != native.OK or length.value < capacity:
                return status, buffer.value.decode("utf-8", "replace")
            capacity = length.value + 1

    def _free_registry(self):
        if self._own_registry and self._registry:
            self._lib.canopy_registry_free(self._registry)
        self._registry = None

    def update(self):
        """Compiles the graph as it is now and swaps it in: instances take it up at the start of their next query, and the state of a node that
        is in both versions carries over. GraphError, with the engine's reason, if the graph cannot be compiled: the previous version then keeps
        running. Call it after editing the Graph. BoundaryError (the same sentences as the engine's) if a boundary node has no name or two have the same."""
        with self._lock:
            handle = self._handle()
            self._graph.validate()
            lib = self._lib
            c_graph = lib.canopy_graph_new()
            if not c_graph:
                raise MemoryError("out of memory while describing the graph to the engine")
            try:
                _describe(lib, c_graph, self._graph)
                status = lib.canopy_engine_set_graph(handle, c_graph)
                if status == native.ERR_MEMORY:
                    raise MemoryError("out of memory while installing the graph")
                if status != native.OK:
                    reason = lib.canopy_engine_last_error(handle)
                    raise GraphError(reason.decode("utf-8", "replace") if reason else native.message(status))
            finally:
                lib.canopy_graph_free(c_graph)

    def set_knob(self, node_id, inlet_key, value):
        """Moves the knob of an inlet of the installed graph (an atomic store: queries that start later see it, from any thread, and nothing is
        recompiled). `value` is -1 to 1. GraphError if the Graph has no such node or inlet, or the installed graph is older and lacks the node;
        ValueError for a value that is not a number from -1 to 1."""
        handle = self._handle()
        node = self._graph.node(node_id)
        if not isinstance(inlet_key, str) or inlet_key not in node.info.inlet:
            raise GraphError(f"node {node_id} has no inlet {inlet_key!r}")
        if not _values.is_number(value) or not -1 <= value <= 1:
            raise ValueError(f"a knob position is a number from -1 to 1, not {value!r}")
        self._node_status(self._lib.canopy_engine_set_knob(handle, node_id, node.info.inlet_index[inlet_key], float(value)), node_id, "set_knob")

    def action(self, node_id, action):
        """A button of a node was pressed: calls the node type's action handler with this name ("open" of the file node; "play", "pause" and
        "device" of the preview node). GraphError if the installed graph has no such node, if `node_id` is not a whole number that fits in 64 bits
        or if `action` is not text."""
        handle = self._handle()
        node_id = _values.node_id(node_id)
        raw = _values.text(action, f"node {node_id}", "the name of an action").encode("utf-8")
        self._node_status(self._lib.canopy_engine_action(handle, node_id, raw), node_id, f"action {action!r}")

    def node_message(self, node_id):
        """What a node of the installed graph last said about itself ("file not found: ...", a device that cannot be opened); "" for nothing.
        GraphError for a node ID that is not a whole number in 64 bits or that the installed graph does not have."""
        handle = self._handle()
        node_id = _values.node_id(node_id)
        status, text = self._text(self._lib.canopy_engine_node_message, handle, node_id)
        self._node_status(status, node_id, "node_message")
        return text

    def collect(self):
        """Frees what the engine no longer needs (old compiled graphs no instance uses, the shared resources of deleted nodes: the device of a deleted
        preview node is closed). Returns the number of compiled graphs still held."""
        return self._lib.canopy_engine_collect(self._handle())

    def set_audio_backend(self, backend):
        """Chooses the audio system the preview nodes open devices in: "system" (the default: the operating system's) or "null" (no sound hardware: the
        audio is taken in real time and played nowhere; for tests and hosts without a sound card). Takes effect for devices opened afterwards."""
        if backend not in native.AUDIO_BACKENDS:
            raise ValueError(f"the audio backend is 'system' or 'null', not {backend!r}")
        status = self._lib.canopy_engine_set_audio_backend(self._handle(), native.AUDIO_BACKENDS[backend])
        if status != native.OK:
            raise RuntimeError(native.message(status))

    def audio_devices(self):
        """The names of the playback devices the machine has now, as a list (empty for none). It takes a moment: ask when a list is wanted."""
        status, text = self._text(self._lib.canopy_engine_audio_devices, self._handle())
        if status != native.OK:
            raise RuntimeError(native.message(status))
        return text.split("\n") if text else []

    def preview_state(self, node_id):
        """(playing, time_ns) of a realtime preview node of the installed graph: playing is a bool, time_ns the playback time in nanoseconds.
        GraphError for a node ID that is not a whole number in 64 bits, that the installed graph does not have, or that is not a preview node."""
        handle = self._handle()
        node_id = _values.node_id(node_id)
        playing, time_ns = ctypes.c_int32(), ctypes.c_int64()
        self._node_status(self._lib.canopy_preview_state(handle, node_id, ctypes.byref(playing), ctypes.byref(time_ns)), node_id, "preview_state")
        return bool(playing.value), time_ns.value

    def preview_set_time(self, node_id, time_ns):
        """Moves the playback time of a realtime preview node (nanoseconds, any value; rounded to a frame of 48000 Hz). GraphError and ValueError as
        for `preview_state` (ValueError for a time that is not a whole number in 64 bits)."""
        handle = self._handle()
        node_id = _values.node_id(node_id)
        self._node_status(self._lib.canopy_preview_set_time(handle, node_id, _time(time_ns, "time_ns")), node_id, "preview_set_time")

    def preview_warning(self, node_id):
        """The warning of design section 9 for a realtime preview node: the nodes that feed it and are not flagged realtime safe, as a sentence; ""
        when there are none. GraphError as for `preview_state`."""
        handle = self._handle()
        node_id = _values.node_id(node_id)
        status, text = self._text(self._lib.canopy_preview_warning, handle, node_id)
        self._node_status(status, node_id, "preview_warning")
        return text

    def boundary_nodes(self):
        """The boundary nodes of the installed graph as BoundaryInfo(name, kind, node_id), sorted by name."""
        handle = self._handle()
        lib = self._lib
        for _attempt in range(10):                         # (a graph installed between two calls shortens the list: ask again)
            found, changed = [], False
            for index in range(lib.canopy_engine_boundary_count(handle)):
                capacity = 256
                while True:
                    buffer = ctypes.create_string_buffer(capacity)
                    length, kind, node_id = ctypes.c_int32(), ctypes.c_int32(), ctypes.c_int64()
                    status = lib.canopy_engine_boundary_at(handle, index, buffer, capacity, ctypes.byref(length), ctypes.byref(kind),
                                                           ctypes.byref(node_id))
                    if status == native.ERR_INDEX:
                        changed = True
                        break
                    if status != native.OK:
                        raise BoundaryError(native.message(status))
                    if length.value < capacity:
                        break
                    capacity = length.value + 1
                if changed:
                    break
                found.append(BoundaryInfo(buffer.value.decode("utf-8", "replace"), native.BOUNDARY_KINDS[kind.value], node_id.value))
            if not changed:
                return found
        raise BoundaryError("the boundary nodes kept changing while they were listed")

    def _missing(self, name, wanted):
        """BoundaryError for a boundary name the installed graph does not have (as `wanted`, 'inlet' or 'outlet'), saying so if it is the other kind."""
        other = {b.name: b.kind for b in self.boundary_nodes()}.get(name)
        if other is None:
            return BoundaryError(f"the graph has no boundary node called {name!r}")
        return BoundaryError(f"the boundary node {name!r} is a boundary {other}, not a boundary {wanted}")

    def set_boundary(self, name, value):
        """Writes `value` (any float) to the boundary inlet called `name`: an atomic store, visible to every query that starts after it, from any
        thread. BoundaryError if the graph has no boundary inlet of that name."""
        handle = self._handle()
        raw = _name_bytes(name)
        if not _values.is_number(value):
            raise TypeError(f"a boundary value is a number, not {value!r}")
        try:
            number = float(value)
        except OverflowError:
            raise ValueError(f"a boundary value must fit in a float, not {value!r}"[:80]) from None
        status = self._lib.canopy_engine_set_boundary(handle, raw, number)
        if status == native.OK:
            return
        if status == native.ERR_NODE:
            raise self._missing(name, "inlet")
        raise BoundaryError(native.message(status))

    def new_instance(self):
        """An Instance over the installed graph, for the thread that will query it (one instance per querying thread)."""
        with self._lock:
            handle = self._handle()
            # Everything Python has to allocate is made BEFORE the C call, so that when memory has really run out the failure comes while there is nothing in C to lose;
            # after the call only stores into slots that already exist are left, and those allocate nothing. That includes the pointer: a function that RETURNS it makes
            # ctypes build a Python int, which can fail after the instance exists and lose it (it did, in about one run in sixty of the real out-of-memory test), so
            # the C function writes it into a slot made here, and the slot itself is kept as the instance's handle (ctypes takes it wherever a pointer goes).
            instance = Instance(self, None)
            count = self._instances + 1
            slot = ctypes.c_void_p()
            reference = ctypes.byref(slot)
            status = self._lib.canopy_engine_new_instance_into(handle, reference)
            if status == native.ERR_MEMORY:
                raise MemoryError("the engine could not make an instance")
            if status != native.OK:
                raise RuntimeError(native.message(status))
            self._instances = count
            instance._pointer = slot
        return instance

    def _instance_closed(self):
        with self._lock:
            self._instances -= 1

    def close(self):
        """Frees the engine (stopping any preview device). RuntimeError, and nothing is freed, while instances are open. Safe to call twice."""
        with self._lock:
            if self._engine is None:
                return
            if self._instances:
                raise RuntimeError(f"the engine still has {self._instances} open instance(s): close them first")
            status = self._lib.canopy_engine_free(self._engine)
            if status != native.OK:
                raise RuntimeError(native.message(status))
            self._engine = None
            self._free_registry()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:                                  # noqa: BLE001 - nothing useful can be done in a finaliser
            pass


class Instance:
    """One thread's queries over the engine's graph (made by `Engine.new_instance`)."""

    def __init__(self, engine, pointer):
        self._engine, self._pointer, self._lib = engine, pointer, engine._lib

    def _handle(self):
        if self._pointer is None:
            raise RuntimeError("the instance is closed")
        return self._pointer

    def _fail(self, status, name, what):
        if status == native.ERR_NODE:
            return self._engine._missing(name, "outlet")
        return QueryError(status, f"{native.message(status)} ({what})")

    def value(self, name, t_ns):
        """A point query of the boundary outlet `name` at time `t_ns` (integer nanoseconds): a float. BoundaryError if there is no such boundary
        outlet; QueryError on any other nonzero status (a node's own failure, an instance in use by another thread), as for `audio`."""
        handle = self._handle()
        raw, t = _name_bytes(name), _time(t_ns, "t_ns")
        out = ctypes.c_float()
        status = self._lib.canopy_instance_read_at(handle, raw, t, ctypes.byref(out))
        if status != native.OK:
            raise self._fail(status, name, f"point query of {name!r} at {t} ns")
        return out.value

    def audio(self, name, t0_ns, t1_ns, n):
        """A span query of the boundary outlet `name`: `n` samples for the span [t0_ns, t1_ns) (design section 5 says where sample i falls; t1 may
        be before t0 to play the span backwards). Returns a memoryview of n float32 (format 'f'; a host with numpy can wrap it for free). QueryError
        on a nonzero status: n outside 1 to 65536, a span that overflows, a node's own failure, an instance in use by another thread; BoundaryError
        if there is no such boundary outlet."""
        handle = self._handle()
        raw, t0, t1 = _name_bytes(name), _time(t0_ns, "t0_ns"), _time(t1_ns, "t1_ns")
        if not _values.is_int(n):
            raise ValueError(f"n must be a whole number of samples, not {n!r}")
        what = f"span query of {name!r}, n = {n}"
        if not 1 <= n <= native.MAX_N:
            raise QueryError(native.ERR_N, f"{native.message(native.ERR_N)} ({what})")
        samples = array.array("f", bytes(4 * n))
        status = self._lib.canopy_instance_read_span(handle, raw, t0, t1, n, (ctypes.c_float * n).from_buffer(samples))
        if status != native.OK:
            raise self._fail(status, name, what)
        return memoryview(samples)

    def close(self):
        """Frees the instance. Safe to call twice. Do not call it while another thread is still querying it."""
        if self._pointer is not None:
            pointer, self._pointer = self._pointer, None
            self._lib.canopy_instance_free(pointer)
            self._engine._instance_closed()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:                                  # noqa: BLE001
            pass
