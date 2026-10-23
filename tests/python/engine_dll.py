# SPDX-License-Identifier: GPL-3.0-or-later
"""ctypes bindings of the graph / engine / instance API (src/canopy_engine.h and the context calls of src/canopy_node.h) and a way to write
node types in Python, for the tests. Python nodes are only for tests: the real Python bridge is plan step 9, and version 1 has no Python tier.

A Python node type is a set of ctypes callbacks the DLL calls; inside them the context calls (canopy_inlet_at...) come back into the DLL.
An exception inside a callback is recorded in ERRORS (ctypes would otherwise print and ignore it); tests assert that ERRORS stays empty."""
import ctypes

from canopysynth import _descriptor as d
from canopysynth import _lib
from canopysynth import version

lib = _lib.load_dll()

OK, ERR_OVERFLOW, ERR_N, ERR_MEMORY, ERR_GRAPH, ERR_NODE, ERR_PORT, ERR_ARGUMENT, ERR_BUSY = 0, 2, 3, 9, 10, 11, 12, 13, 14
MAX_N = 65536
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1

vp, i32, i64, f32, f64, cstr = ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64, ctypes.c_float, ctypes.c_double, ctypes.c_char_p
p_float = ctypes.POINTER(ctypes.c_float)


def declare(name, restype, *argtypes):
    function = getattr(lib, name)
    function.restype = restype
    function.argtypes = list(argtypes)
    return function


registry_new = declare("canopy_registry_new", vp)
registry_free = declare("canopy_registry_free", None, vp)
registry_register = declare("canopy_registry_register", i32, vp, ctypes.POINTER(d.NodeType))
registry_last_error = declare("canopy_registry_last_error", cstr, vp)
registry_add_test_nodes = declare("canopy_registry_add_test_nodes", i32, vp)

graph_new = declare("canopy_graph_new", vp)
graph_free = declare("canopy_graph_free", None, vp)
graph_add_node = declare("canopy_graph_add_node", i32, vp, i64, cstr)
graph_set_int = declare("canopy_graph_set_int", i32, vp, i64, cstr, i64)
graph_set_float = declare("canopy_graph_set_float", i32, vp, i64, cstr, f64)
graph_set_string = declare("canopy_graph_set_string", i32, vp, i64, cstr, cstr)
graph_set_knob = declare("canopy_graph_set_knob", i32, vp, i64, cstr, f32)
graph_connect = declare("canopy_graph_connect", i32, vp, i64, cstr, i64, cstr)

engine_new = declare("canopy_engine_new", vp, vp)
engine_free = declare("canopy_engine_free", i32, vp)
engine_set_graph = declare("canopy_engine_set_graph", i32, vp, vp)
engine_last_error = declare("canopy_engine_last_error", cstr, vp)
engine_node_count = declare("canopy_engine_node_count", i32, vp)
engine_set_knob = declare("canopy_engine_set_knob", i32, vp, i64, i32, f32)
engine_get_knob = declare("canopy_engine_get_knob", i32, vp, i64, i32, ctypes.POINTER(f32), ctypes.POINTER(ctypes.c_uint64))
engine_action = declare("canopy_engine_action", i32, vp, i64, cstr)
engine_new_instance = declare("canopy_engine_new_instance", vp, vp)
engine_new_instance_into = declare("canopy_engine_new_instance_into", i32, vp, vp)
engine_collect = declare("canopy_engine_collect", i32, vp)
engine_graph_serial = declare("canopy_engine_graph_serial", i64, vp)
instance_graph_serial = declare("canopy_instance_graph_serial", i64, vp)
instance_free = declare("canopy_instance_free", None, vp)
instance_arena_floats = declare("canopy_instance_arena_floats", i64, vp)
_instance_inlet_at = declare("canopy_instance_inlet_at", i32, vp, i64, i32, i64, ctypes.POINTER(f32))
instance_inlet_span = declare("canopy_instance_inlet_span", i32, vp, i64, i32, i64, i64, i64, p_float)

BOUNDARY_INLET, BOUNDARY_OUTLET = 0, 1
ERR_INDEX = 4
engine_set_boundary = declare("canopy_engine_set_boundary", i32, vp, cstr, f32)
engine_boundary_count = declare("canopy_engine_boundary_count", i32, vp)
engine_boundary_at = declare("canopy_engine_boundary_at", i32, vp, i32, ctypes.c_char_p, i32, ctypes.POINTER(i32), ctypes.POINTER(i32),
                             ctypes.POINTER(i64))
engine_node_message = declare("canopy_engine_node_message", i32, vp, i64, ctypes.c_char_p, i32, ctypes.POINTER(i32))
_instance_read_at = declare("canopy_instance_read_at", i32, vp, cstr, i64, ctypes.POINTER(f32))
instance_read_span = declare("canopy_instance_read_span", i32, vp, cstr, i64, i64, i64, p_float)

AUDIO_SYSTEM, AUDIO_NULL = 0, 1
engine_set_audio_backend = declare("canopy_engine_set_audio_backend", i32, vp, i32)
engine_audio_devices = declare("canopy_engine_audio_devices", i32, vp, ctypes.c_char_p, i32, ctypes.POINTER(i32))
preview_state = declare("canopy_preview_state", i32, vp, i64, ctypes.POINTER(i32), ctypes.POINTER(i64))
preview_set_time = declare("canopy_preview_set_time", i32, vp, i64, i64)
preview_warning = declare("canopy_preview_warning", i32, vp, i64, ctypes.c_char_p, i32, ctypes.POINTER(i32))

_ctx_inlet_at = declare("canopy_inlet_at", i32, vp, i32, i64, ctypes.POINTER(f32))


# Point queries return a status and write their answer (ABI 2). Most tests only want the answer, so these give it (0.0 when the call fails);
# the `_status` versions return (status, answer).
def instance_inlet_at_status(instance, node_id, inlet, t):
    value = ctypes.c_float(9.0)
    status = _instance_inlet_at(instance, node_id, inlet, t, ctypes.byref(value))
    return status, value.value


def instance_read_at_status(instance, name, t):
    value = ctypes.c_float(9.0)
    status = _instance_read_at(instance, name, t, ctypes.byref(value))
    return status, value.value


def ctx_inlet_at_status(ctx, inlet, t):
    value = ctypes.c_float(9.0)
    status = _ctx_inlet_at(ctx, inlet, t, ctypes.byref(value))
    return status, value.value


def instance_inlet_at(instance, node_id, inlet, t):
    return instance_inlet_at_status(instance, node_id, inlet, t)[1]


def instance_read_at(instance, name, t):
    return instance_read_at_status(instance, name, t)[1]


def ctx_inlet_at(ctx, inlet, t):
    return ctx_inlet_at_status(ctx, inlet, t)[1]
ctx_inlet_span = declare("canopy_inlet_span", i32, vp, i32, i64, i64, i64, p_float)
ctx_scratch = declare("canopy_scratch", p_float, vp, i64)
ctx_state = declare("canopy_ctx_state", vp, vp)
ctx_shared = declare("canopy_ctx_shared", vp, vp)
ctx_int = declare("canopy_ctx_int", i64, vp, i32)
ctx_float = declare("canopy_ctx_float", f64, vp, i32)
ctx_string = declare("canopy_ctx_string", cstr, vp, i32)
ctx_stamp = declare("canopy_ctx_upstream_stamp", ctypes.c_uint64, vp)
ctx_shared_changed = declare("canopy_ctx_shared_changed", None, vp)

alloc_live = declare("canopy_alloc_live", i64)
alloc_total = declare("canopy_alloc_total", i64)

ERRORS = []                                   # exceptions raised inside callbacks


def guarded(function, default):
    """Wraps a callback so that an exception is recorded and a default returned instead of being swallowed by ctypes."""
    def wrapper(*args):
        try:
            return function(*args)
        except BaseException as error:        # noqa: BLE001
            ERRORS.append(repr(error))
            return default
    return wrapper


def guarded_point(function):
    """A point handler for the DLL from a Python function `function(ctx, outlet, t)` that returns the answer (a float: status 0) or a tuple
    `(status, answer)`. An exception is recorded in ERRORS and the status is ERR_ARGUMENT."""
    def wrapper(ctx, outlet, t, out):
        try:
            result = function(ctx, outlet, t)
        except BaseException as error:        # noqa: BLE001
            ERRORS.append(repr(error))
            return ERR_ARGUMENT
        status, value = result if isinstance(result, tuple) else (OK, result)
        out[0] = value
        return status
    return wrapper


def float32(value):
    """The float a C float holds after being given `value`."""
    return ctypes.c_float(value).value


class PyNodeType:
    """A node type whose handlers are Python functions. inlets: [(key, default_knob)], outlets: [key], settings: [(key, kind, default[,
    choices])] with kind one of "int", "float", "string", "path", "choice". `at(ctx, outlet, t)` and `span(ctx, outlet, t0, t1, n, out)` are
    the handlers (either may be None); `scratch` is the declared scratch_buffers."""

    def __init__(self, key, inlets=(), outlets=("out",), settings=(), at=None, span=None, scratch=0, flags=0):
        self.keep = []
        t = self.type = d.NodeType()
        t.abi_version = version.ABI_VERSION
        t.struct_size = ctypes.sizeof(d.NodeType)
        t.key, t.name, t.type_version, t.flags = key.encode(), key.encode(), 1, flags
        inlet_array = (d.InletDesc * max(1, len(inlets)))(*[d.InletDesc(k.encode(), k.encode(), v) for k, v in inlets])
        outlet_array = (d.OutletDesc * max(1, len(outlets)))(*[d.OutletDesc(k.encode(), k.encode()) for k in outlets])
        setting_descs = []
        for entry in settings:
            name, kind, default = entry[0], entry[1], entry[2]
            choices = entry[3] if len(entry) > 3 else []
            choice_array = (ctypes.c_char_p * max(1, len(choices)))(*[c.encode() for c in choices])
            self.keep.append(choice_array)
            kind_code = {"int": 0, "float": 1, "string": 2, "path": 3, "choice": 4}[kind]
            setting_descs.append(d.SettingDesc(name.encode(), kind_code, default if kind in ("int", "choice") else 0,
                                               default if kind == "float" else 0.0, default.encode() if kind in ("string", "path") else None,
                                               len(choices), ctypes.cast(choice_array, d.c_char_pp) if choices else None))
        setting_array = (d.SettingDesc * max(1, len(setting_descs)))(*setting_descs)
        self.keep += [inlet_array, outlet_array, setting_array]
        t.n_inlets, t.inlets = len(inlets), ctypes.cast(inlet_array, ctypes.POINTER(d.InletDesc))
        t.n_outlets, t.outlets = len(outlets), ctypes.cast(outlet_array, ctypes.POINTER(d.OutletDesc))
        t.n_settings, t.settings = len(settings), ctypes.cast(setting_array, ctypes.POINTER(d.SettingDesc))
        t.scratch_buffers = scratch
        if at:
            self.at = d.QUERY_AT(guarded_point(at))
            t.handlers.query_at = self.at
        if span:
            self.span = d.QUERY_SPAN(guarded(span, ERR_ARGUMENT))
            t.handlers.query_span = self.span

    def register(self, registry):
        status = registry_register(registry, ctypes.byref(self.type))
        assert status == OK, registry_last_error(registry)


class Rig:
    """A registry with Python node types, a graph description, an engine and (after install) an instance; close() frees them in order."""

    def __init__(self, *types, test_nodes=False):
        del ERRORS[:]                         # an error left by an earlier test must not fail this one
        self.types = types
        self.registry = registry_new()
        for t in types:
            t.register(self.registry)
        if test_nodes:                        # the hidden test-only node types of the DLL
            assert registry_add_test_nodes(self.registry) == OK
        self.graph = graph_new()
        self.engine = engine_new(self.registry)
        self.instance = None
        self.live_before = alloc_live()

    def node(self, node_id, key):
        assert graph_add_node(self.graph, node_id, key.encode()) == OK

    def connect(self, from_id, outlet, to_id, inlet):
        assert graph_connect(self.graph, from_id, outlet.encode(), to_id, inlet.encode()) == OK

    def install(self):
        status = engine_set_graph(self.engine, self.graph)
        assert status == OK, engine_last_error(self.engine)
        if self.instance:
            instance_free(self.instance)
        self.instance = engine_new_instance(self.engine)
        assert self.instance

    def update(self, graph=None):
        """Installs a (new) description into the engine; the existing instance adopts it at its next query."""
        status = engine_set_graph(self.engine, graph or self.graph)
        assert status == OK, engine_last_error(self.engine)

    def close(self):
        if self.instance:
            instance_free(self.instance)
        assert engine_free(self.engine) == OK
        graph_free(self.graph)
        registry_free(self.registry)
        assert not ERRORS, ERRORS


def span_buffer(n):
    return (ctypes.c_float * n)()
