"""Tests (plan step 13, error behaviours): the C API as a whole, as the DLL exports it.
1. The export table of the DLL (read from the PE file) is the list of functions the three public headers declare, both ways, and every ctypes declaration
   made in Python (the package's own, canopysynth/_native.py, and the tests', engine_dll.py) has the argument and result widths of the header's prototype: a
   declaration of the wrong width cuts a number without a sound.
2. Every exported function is called with NULL and with extreme arguments (the first one is NULL, the integers are the edges of their ranges, floats are NaN and
   infinities, texts are empty, not UTF-8 or a megabyte long, counts are negative or enormous, a buffer that must not be written has a canary round it) and
   must neither crash nor leak, and answer with the status the header promises. A table below names the function of each call, and a test checks that no
   exported function is missing from it, so a new export cannot be added without being swept."""
import ctypes
import math
import os
import re
import struct

import engine_dll as e
from canopysynth import _native as native
from engine_dll import i32, i64, f32, vp, cstr, lib
from test_fileread import write_wav

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DLL = os.path.join(ROOT, "canopysynth", "canopysynth.dll")
HEADERS = ("canopy.h", "canopy_node.h", "canopy_engine.h")
INT32_MIN, INT32_MAX = -2 ** 31, 2 ** 31 - 1
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1
OK, ERR_RATE, ERR_OVERFLOW, ERR_N, ERR_INDEX, ERR_GRAPH, ERR_NODE, ERR_PORT, ERR_ARGUMENT = 0, 1, 2, 3, 4, 10, 11, 12, 13


# ---- 1. the export table, the headers and the ctypes declarations ----

def pe_exports(path):
    """The names the DLL exports, read from its PE export directory (a 64-bit file)."""
    data = open(path, "rb").read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    sections_count, optional_size = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    assert struct.unpack_from("<H", data, optional)[0] == 0x20B, "a 64-bit (PE32+) file"
    export_rva = struct.unpack_from("<I", data, optional + 112)[0]
    table, sections = optional + optional_size, []
    for index in range(sections_count):
        _name, size, address, raw_size, pointer = struct.unpack_from("<8sIIII", data, table + 40 * index)
        sections.append((address, max(size, raw_size), pointer))

    def offset(rva):
        for address, size, pointer in sections:
            if address <= rva < address + size:
                return rva - address + pointer
        raise ValueError(hex(rva))

    base = offset(export_rva)
    count, names_rva = struct.unpack_from("<I", data, base + 24)[0], struct.unpack_from("<I", data, base + 32)[0]
    names = []
    for index in range(count):
        start = offset(struct.unpack_from("<I", data, offset(names_rva) + 4 * index)[0])
        names.append(data[start:data.index(b"\0", start)].decode("ascii"))
    return names


def header_prototypes():
    """name -> (result class, [argument classes]) of every CANOPY_API function of the three public headers."""
    found = {}
    for header in HEADERS:
        text = open(os.path.join(ROOT, "src", header), encoding="utf-8").read()
        for match in re.finditer(r"CANOPY_API\s+([^;{}]*?)\b(canopy_\w+)\s*\(([^;{}]*?)\)\s*;", text, re.S):
            result, name, params = " ".join(match.group(1).split()), match.group(2), " ".join(match.group(3).split())
            assert name not in found, f"{name} is declared twice"
            found[name] = (c_class(result), [] if params in ("", "void") else [c_class(p) for p in split_params(params)])
    return found


def split_params(text):
    """The parameters of a prototype (a function-pointer parameter has no comma of its own)."""
    return [p.strip() for p in text.split(",")]


def c_class(text):
    """The class of a C type written in a prototype: its kind and width, or 'ptr' for any pointer."""
    if "*" in text:
        return "ptr"
    words = [w for w in re.findall(r"[A-Za-z_]\w*", text) if w not in ("const", "unsigned")]
    base = words[0] if words else ""
    if base == "void" and len(words) == 1 and text.strip() == "void":
        return "void"
    table = {"int32_t": "i32", "int": "i32", "int64_t": "i64", "uint64_t": "u64", "uint32_t": "u32", "float": "f32", "double": "f64", "size_t": "u64"}
    assert base in table or len(words) == 2, f"a type the check does not know: {text!r}"
    return table.get(base, base)


def ctype_class(ctype):
    if ctype is None:
        return "void"
    if ctype in (ctypes.c_int32, ctypes.c_int):
        return "i32"
    if ctype is ctypes.c_int64:
        return "i64"
    if ctype is ctypes.c_uint64:
        return "u64"
    if ctype is ctypes.c_uint32:
        return "u32"
    if ctype is ctypes.c_float:
        return "f32"
    if ctype is ctypes.c_double:
        return "f64"
    if ctype in (ctypes.c_void_p, ctypes.c_char_p) or (isinstance(ctype, type) and issubclass(ctype, ctypes._Pointer)):
        return "ptr"
    raise AssertionError(f"a ctypes type the check does not know: {ctype!r}")


def test_py_the_dll_exports_exactly_what_the_headers_declare_and_every_python_declaration_has_the_headers_widths():
    exported, prototypes = pe_exports(DLL), header_prototypes()
    assert len(exported) == len(set(exported)) >= 60, len(exported)
    assert set(exported) == set(prototypes), (f"exported but not declared: {sorted(set(exported) - set(prototypes))}; "
                                                f"declared but not exported: {sorted(set(prototypes) - set(exported))}")
    mismatches, checked = [], 0
    for name, restype, argtypes in native._SIGNATURES:                                          # the package's own declarations
        want = prototypes[name]
        have = (ctype_class(restype), [ctype_class(a) for a in argtypes])
        checked += 1
        if have != want:
            mismatches.append(f"native {name}: declared {have}, the header says {want}")
    declared = {name: function for name, function in vars(lib).items() if name.startswith("canopy_") and getattr(function, "argtypes", None) is not None}
    for name, function in declared.items():                                                     # the tests' declarations (engine_dll.declare)
        want = prototypes[name]
        have = (ctype_class(function.restype), [ctype_class(a) for a in function.argtypes])
        checked += 1
        if have != want:
            mismatches.append(f"engine_dll {name}: declared {have}, the header says {want}")
    assert checked >= 60 and not mismatches, mismatches


# ---- 2. the sweep ----

class World:
    """A registry (with the hidden test types), an engine on the null audio backend, an installed graph and an instance: boundary inlet "x" (node 1),
    boundary outlet "y" (2) fed by it, a file node (3) with a good file, a realtime preview (4), a test filter (5) feeding boundary outlet "f" (6)."""

    def __init__(self, directory):
        self.base = e.alloc_live()
        self.wav = os.path.join(directory, "sweep.wav")
        write_wav(self.wav, 1, 16, 2, 8000, b"\x01\x02\x03\x04" * 400)
        self.registry = call(lib.canopy_registry_new)
        assert e.registry_add_test_nodes(self.registry) == OK
        self.graph = call(lib.canopy_graph_new)
        for node_id, key in ((1, b"boundary_inlet"), (2, b"boundary_outlet"), (3, b"file_read"), (4, b"realtime_preview"), (5, b"test_filter"), (6, b"boundary_outlet")):
            assert e.graph_add_node(self.graph, node_id, key) == OK
        for node_id, name in ((1, b"x"), (2, b"y"), (6, b"f")):
            assert e.graph_set_string(self.graph, node_id, b"name", name) == OK
        assert e.graph_set_string(self.graph, 3, b"path", self.wav.encode("utf-8")) == OK
        assert e.graph_connect(self.graph, 1, b"out", 2, b"in") == OK and e.graph_connect(self.graph, 5, b"out", 6, b"in") == OK
        self.engine = e.engine_new(self.registry)
        assert e.engine_set_audio_backend(self.engine, e.AUDIO_NULL) == OK
        assert e.engine_set_graph(self.engine, self.graph) == OK, e.engine_last_error(self.engine)
        self.instance = e.engine_new_instance(self.engine)
        assert self.instance

    def close(self):
        e.instance_free(self.instance)
        assert e.engine_free(self.engine) == OK
        e.graph_free(self.graph)
        e.registry_free(self.registry)
        assert e.alloc_live() == self.base, "the sweep left allocations behind"


CANARY = 12345.0


class Floats:
    """n floats with four canary floats on each side: `pointer` is the data, `intact()` tells whether the canaries are untouched."""

    def __init__(self, n=4):
        self.n, self.block = n, (ctypes.c_float * (n + 8))(*([CANARY] * (n + 8)))
        self.pointer = ctypes.cast(ctypes.byref(self.block, 16), ctypes.POINTER(ctypes.c_float))

    def guards_intact(self):
        return all(self.block[i] == CANARY for i in (0, 1, 2, 3)) and all(self.block[self.n + 4 + i] == CANARY for i in range(4))

    def untouched(self):
        return all(v == CANARY for v in self.block)

    def zero(self):
        return all(self.pointer[i] == 0.0 for i in range(self.n))


TEXTS = [b"", b"x", b"\xff\xfe\xfd", b"\xc3\x28", b"caf\xc3\xa9", b"a" * 70000, b"boundary_inlet"]
BIG = b"z" * 1_000_000
FLOATS = [0.0, -0.0, 1.0, -1.0, 1.0000001, -1.0000001, 2.0, 1e30, 3.4e38, 1e-45, float("nan"), float("inf"), float("-inf")]
INTS64 = [0, 1, -1, 2, 7, 65536, 65537, INT32_MAX, INT32_MIN, 2 ** 32, INT64_MAX, INT64_MIN, INT64_MAX - 1, INT64_MIN + 1]
INTS32 = [0, 1, -1, 2, 3, 100, 65536, INT32_MAX, INT32_MIN]
CALLED = set()
FAILS = {}                                                  # (function, what happened) -> how many times: the sweep goes on after a deviation and reports them all
LAST = [""]


def call(function, *args):
    """Calls a function of the DLL, noting it (a crash would show as an OSError from ctypes: an access violation)."""
    CALLED.add(function.__name__)
    LAST[0] = function.__name__
    return function(*args)


def allowed(status, *statuses):
    if status not in statuses:
        key = (LAST[0], f"status {status}, expected one of {statuses}")
        FAILS[key] = FAILS.get(key, 0) + 1


def check(condition, what):
    if not condition:
        key = (LAST[0], what)
        FAILS[key] = FAILS.get(key, 0) + 1


def failed(status):
    """Any status but OK (a call the header says may give one of several failures, or does not name which)."""
    check(status != OK, "expected a failure, got OK")


def sweep_graph_description(world):
    g = e.graph_new()
    for node_id in INTS64:
        allowed(call(lib.canopy_graph_add_node, g, node_id, b"boundary_inlet"), OK)
    for text in TEXTS + [BIG]:
        allowed(call(lib.canopy_graph_add_node, g, 7, text), OK)
        for setting in (lib.canopy_graph_set_string,):
            allowed(call(setting, g, 7, text, text), OK)
            allowed(call(setting, g, 7, b"name", text), OK)
        allowed(call(lib.canopy_graph_set_knob, g, 7, text, 0.5), OK)
        allowed(call(lib.canopy_graph_connect, g, 7, text, 8, text), OK)
    for value in INTS64:
        allowed(call(lib.canopy_graph_set_int, g, 7, b"count", value), OK)
    for value in FLOATS:
        allowed(call(lib.canopy_graph_set_float, g, 7, b"level", value), OK)
        allowed(call(lib.canopy_graph_set_knob, g, 7, b"in", value), OK)
    for node_id in INTS64:
        allowed(call(lib.canopy_graph_connect, g, node_id, b"out", node_id, b"in"), OK)
    for bad in (None,):                                                                               # NULL graph and NULL texts
        allowed(call(lib.canopy_graph_add_node, bad, 1, b"x"), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_int, bad, 1, b"x", 1), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_float, bad, 1, b"x", 1.0), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_string, bad, 1, b"x", b"y"), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_knob, bad, 1, b"x", 0.5), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_connect, bad, 1, b"x", 2, b"y"), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_add_node, g, 1, bad), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_int, g, 1, bad, 1), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_float, g, 1, bad, 1.0), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_string, g, 1, bad, b"y"), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_string, g, 1, b"x", bad), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_set_knob, g, 1, bad, 0.5), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_connect, g, 1, bad, 2, b"y"), ERR_ARGUMENT)
        allowed(call(lib.canopy_graph_connect, g, 1, b"x", 2, bad), ERR_ARGUMENT)
    call(lib.canopy_graph_free, None)
    # what was recorded is nonsense, and compiling it is a GraphError that changes nothing
    before = e.engine_graph_serial(world.engine)
    allowed(call(lib.canopy_engine_set_graph, world.engine, g), ERR_GRAPH)
    assert e.engine_graph_serial(world.engine) == before and e.engine_last_error(world.engine)
    assert e.instance_read_at(world.instance, b"y", 0) == 0.0
    e.graph_free(g)


def sweep_registry(world):
    r = world.registry
    check(call(lib.canopy_registry_count, None) == 0, 'call(lib.canopy_registry_count, None) == 0')
    call(lib.canopy_registry_free, None)
    failed(call(lib.canopy_registry_register, None, None))                                                  # (the header names ABI, KEY, DUPLICATE, DESCRIPTOR and MEMORY)
    failed(call(lib.canopy_registry_register, r, None))
    failed(call(lib.canopy_registry_add_test_nodes, None))
    count = call(lib.canopy_registry_count, r)
    assert count > 3
    for index in (-1, count, count + 1, INT32_MAX, INT32_MIN):
        check(not call(lib.canopy_registry_at, r, index), 'not call(lib.canopy_registry_at, r, index)')
    check(not call(lib.canopy_registry_at, None, 0), 'not call(lib.canopy_registry_at, None, 0)')
    for text in TEXTS + [BIG, None]:
        call(lib.canopy_registry_find, r, text)
        call(lib.canopy_registry_find, None, text)
    check(call(lib.canopy_registry_find, r, b"file_read"), 'call(lib.canopy_registry_find, r, b"file_read")')
    call(lib.canopy_registry_last_error, None)
    call(lib.canopy_registry_last_error, r)
    # a second add of the hidden types is refused (their keys are taken), without harm
    check(call(lib.canopy_registry_add_test_nodes, r) != OK, 'call(lib.canopy_registry_add_test_nodes, r) != OK')


def sweep_engine(world):
    eng, g = world.engine, world.graph
    check(not call(lib.canopy_engine_new, None), 'not call(lib.canopy_engine_new, None)')
    check(call(lib.canopy_engine_free, None) == OK, 'call(lib.canopy_engine_free, None) == OK')
    allowed(call(lib.canopy_engine_set_graph, None, g), ERR_ARGUMENT)
    allowed(call(lib.canopy_engine_set_graph, eng, None), ERR_ARGUMENT)
    check(call(lib.canopy_engine_collect, None) == 0 and call(lib.canopy_engine_graph_serial, None) == 0 and call(lib.canopy_engine_node_count, None) == 0, 'call(lib.canopy_engine_collect, None) == 0 and call(lib.canopy_engine_graph_serial, None) == 0 and call(lib.canopy_engine_node_count, None) == 0')
    check(call(lib.canopy_engine_last_error, None) in (b"", None), 'call(lib.canopy_engine_last_error, None) in (b"", None)')
    check(call(lib.canopy_engine_boundary_count, None) == 0, 'call(lib.canopy_engine_boundary_count, None) == 0')
    # knobs
    allowed(call(lib.canopy_engine_set_knob, None, 2, 0, 0.5), ERR_ARGUMENT)
    value, generation = f32(), ctypes.c_uint64()
    for node_id in INTS64:
        for inlet in INTS32:
            for number in (0.5, float("nan"), 1.0000001):
                allowed(call(lib.canopy_engine_set_knob, eng, node_id, inlet, number), OK, ERR_ARGUMENT, ERR_NODE, ERR_PORT)
            allowed(call(lib.canopy_engine_get_knob, eng, node_id, inlet, ctypes.byref(value), ctypes.byref(generation)), OK, ERR_NODE, ERR_PORT)
            allowed(call(lib.canopy_engine_get_knob, eng, node_id, inlet, None, None), OK, ERR_NODE, ERR_PORT)
    allowed(call(lib.canopy_engine_get_knob, None, 2, 0, None, None), ERR_ARGUMENT)
    for number in FLOATS:                                                                       # node 2's knob exists: -1 .. 1 is taken, anything else (NaN included) refused
        allowed(call(lib.canopy_engine_set_knob, eng, 2, 0, number), OK if math.isfinite(number) and -1.0 <= number <= 1.0 else ERR_ARGUMENT)
    assert e.engine_set_knob(eng, 2, 0, 0.0) == OK
    # actions
    allowed(call(lib.canopy_engine_action, None, 3, b"open"), ERR_ARGUMENT)
    allowed(call(lib.canopy_engine_action, eng, 3, None), ERR_ARGUMENT)
    for node_id in INTS64:
        allowed(call(lib.canopy_engine_action, eng, node_id, b"nothing"), OK, ERR_NODE)
    for text in TEXTS + [BIG]:
        for node_id in (1, 3, 4, 99):
            allowed(call(lib.canopy_engine_action, eng, node_id, text), OK, ERR_NODE)
    # messages, boundary nodes, devices: the buffer rules (a NULL buffer with capacity 0 is allowed, with a capacity above 0 it is not, a negative capacity never)
    for function, args in ((lib.canopy_engine_node_message, (eng, 3)), (lib.canopy_engine_audio_devices, (eng,)), (lib.canopy_preview_warning, (eng, 4))):
        length = i32()
        allowed(call(function, *args, None, 0, None), OK)
        allowed(call(function, *args, None, 0, ctypes.byref(length)), OK)
        for capacity in (1, 2, 5):
            buffer = ctypes.create_string_buffer(capacity)
            allowed(call(function, *args, buffer, capacity, ctypes.byref(length)), OK)
            assert len(buffer.value) <= capacity - 1
        for capacity in (1, 100, INT32_MAX):
            allowed(call(function, *args, None, capacity, None), ERR_ARGUMENT)
        for capacity in (-1, INT32_MIN):
            allowed(call(function, *args, ctypes.create_string_buffer(4), capacity, None), ERR_ARGUMENT)
    allowed(call(lib.canopy_engine_node_message, None, 3, None, 0, None), ERR_ARGUMENT)
    for node_id in INTS64:
        allowed(call(lib.canopy_engine_node_message, eng, node_id, None, 0, None), OK, ERR_NODE)
    # boundary
    allowed(call(lib.canopy_engine_set_boundary, None, b"x", 0.5), ERR_ARGUMENT)
    allowed(call(lib.canopy_engine_set_boundary, eng, None, 0.5), ERR_ARGUMENT)
    for text in TEXTS + [BIG]:
        allowed(call(lib.canopy_engine_set_boundary, eng, text, 0.5), OK, ERR_NODE)
    for number in FLOATS:
        allowed(call(lib.canopy_engine_set_boundary, eng, b"x", number), OK)                                  # any float, nothing clamped
    allowed(call(lib.canopy_engine_set_boundary, eng, b"y", 0.5), ERR_NODE)                                  # an outlet is not an inlet
    assert e.engine_set_boundary(eng, b"x", 0.0) == OK
    count = call(lib.canopy_engine_boundary_count, eng)
    assert count == 3
    name, length, kind, node_id = ctypes.create_string_buffer(8), i32(), i32(), i64()
    for index in (-1, count, count + 1, INT32_MAX, INT32_MIN):
        allowed(call(lib.canopy_engine_boundary_at, eng, index, name, 8, ctypes.byref(length), ctypes.byref(kind), ctypes.byref(node_id)), ERR_INDEX)
    for index in range(count):
        allowed(call(lib.canopy_engine_boundary_at, eng, index, None, 0, None, None, None), OK)
        allowed(call(lib.canopy_engine_boundary_at, eng, index, name, 2, ctypes.byref(length), None, None), OK)
        allowed(call(lib.canopy_engine_boundary_at, eng, index, None, 5, None, None, None), ERR_ARGUMENT)
        allowed(call(lib.canopy_engine_boundary_at, eng, index, name, -1, None, None, None), ERR_ARGUMENT)
    allowed(call(lib.canopy_engine_boundary_at, None, 0, name, 8, None, None, None), ERR_ARGUMENT)
    # the audio backend (the system's is never chosen here: a Play would open the real device)
    allowed(call(lib.canopy_engine_set_audio_backend, None, e.AUDIO_NULL), ERR_ARGUMENT)
    for backend in (-1, 2, 3, INT32_MAX, INT32_MIN):
        allowed(call(lib.canopy_engine_set_audio_backend, eng, backend), ERR_ARGUMENT)
    allowed(call(lib.canopy_engine_audio_devices, None, None, 0, None), ERR_ARGUMENT)


def sweep_preview(world):
    eng = world.engine
    playing, time_ns = i32(), i64()
    allowed(call(lib.canopy_preview_state, None, 4, None, None), ERR_ARGUMENT)
    allowed(call(lib.canopy_preview_set_time, None, 4, 0), ERR_ARGUMENT)
    allowed(call(lib.canopy_preview_warning, None, 4, None, 0, None), ERR_ARGUMENT)
    for node_id in INTS64:
        if node_id != 4:
            allowed(call(lib.canopy_preview_state, eng, node_id, ctypes.byref(playing), ctypes.byref(time_ns)), ERR_NODE, ERR_ARGUMENT)
            allowed(call(lib.canopy_preview_set_time, eng, node_id, 0), ERR_NODE, ERR_ARGUMENT)
            allowed(call(lib.canopy_preview_warning, eng, node_id, None, 0, None), ERR_NODE, ERR_ARGUMENT)
    for node_id in (1, 2, 3, 5):                                                                   # nodes that are not preview nodes
        allowed(call(lib.canopy_preview_state, eng, node_id, None, None), ERR_ARGUMENT)
    allowed(call(lib.canopy_preview_state, eng, 4, None, None), OK)
    for time in INTS64 + [-10 ** 15, 10 ** 15, INT64_MAX // 48000, INT64_MIN // 48000]:
        allowed(call(lib.canopy_preview_set_time, eng, 4, time), OK)
        allowed(call(lib.canopy_preview_state, eng, 4, ctypes.byref(playing), ctypes.byref(time_ns)), OK)
        check(playing.value == 0 and (abs(time_ns.value - time) <= 20_834 or abs(time) > 2 ** 62), f"set_time {time} was read back as {time_ns.value}")        # to the nearest frame of 48000 Hz
    assert e.preview_set_time(eng, 4, 0) == OK


def sweep_instance(world):
    inst, eng = world.instance, world.engine
    check(not call(lib.canopy_engine_new_instance, None), 'not call(lib.canopy_engine_new_instance, None)')
    call(lib.canopy_instance_free, None)
    check(call(lib.canopy_instance_arena_floats, None) == 0 and call(lib.canopy_instance_graph_serial, None) == 0, 'call(lib.canopy_instance_arena_floats, None) == 0 and call(lib.canopy_instance_graph_serial, None) == 0')
    check(call(lib.canopy_instance_graph_serial, inst) == e.engine_graph_serial(eng), 'call(lib.canopy_instance_graph_serial, inst) == e.engine_graph_serial(eng)')
    one = f32(9.0)
    allowed(call(lib.canopy_instance_inlet_at, None, 2, 0, 0, ctypes.byref(one)), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_read_at, None, b"y", 0, ctypes.byref(one)), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_read_at, inst, None, 0, ctypes.byref(one)), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_read_at, inst, b"y", 0, None), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_inlet_at, inst, 2, 0, 0, None), ERR_ARGUMENT)
    for node_id in INTS64:
        for inlet in INTS32:
            one.value = 9.0
            allowed(call(lib.canopy_instance_inlet_at, inst, node_id, inlet, 5, ctypes.byref(one)), OK, ERR_NODE, ERR_PORT)
            if node_id not in (1, 2, 3, 4, 5, 6) or inlet not in (0, 1):
                check(one.value == 0.0, 'one.value == 0.0')                                                      # a failed point query writes 0.0
    for t in INTS64:
        one.value = 9.0
        allowed(call(lib.canopy_instance_read_at, inst, b"y", t, ctypes.byref(one)), OK)
        allowed(call(lib.canopy_instance_inlet_at, inst, 2, 0, t, ctypes.byref(one)), OK)
    for text in TEXTS + [BIG]:
        one.value = 9.0
        allowed(call(lib.canopy_instance_read_at, inst, text, 0, ctypes.byref(one)), OK, ERR_NODE)
    for name in (b"x", b"nothing"):                                                                  # an inlet's name, and a name that is not there
        one.value = 9.0
        allowed(call(lib.canopy_instance_read_at, inst, name, 0, ctypes.byref(one)), ERR_NODE)
        check(one.value == 0.0, 'one.value == 0.0')
    # spans: the counts and times at the edges, with a canary round a buffer of 4 floats (n is 4 where the call may write)
    out = Floats(4)
    for n in (0, -1, 65537, INT32_MAX, 2 ** 40, INT64_MAX, INT64_MIN):                              # n outside 1 .. 65536: nothing is written at all
        out = Floats(4)
        allowed(call(lib.canopy_instance_read_span, inst, b"y", 0, 100, n, out.pointer), ERR_N)
        allowed(call(lib.canopy_instance_inlet_span, inst, 2, 0, 0, 100, n, out.pointer), ERR_N)
        check(out.untouched(), f"n = {n}: the buffer was written")
    for t0, t1 in ((INT64_MIN, INT64_MAX), (INT64_MAX, INT64_MIN), (INT64_MIN, 1), (-1, INT64_MAX), (1, INT64_MIN), (INT64_MAX, -2)):          # t1 - t0 overflows
        out = Floats(4)
        allowed(call(lib.canopy_instance_read_span, inst, b"y", t0, t1, 4, out.pointer), ERR_OVERFLOW)
        check(out.zero() and out.guards_intact(), f"the overflow of [{t0}, {t1}) did not zero-fill n floats and nothing else")
    for t0 in INTS64:
        for t1 in (t0, 0, 1000, INT64_MAX // 2, INT64_MIN // 2):
            out = Floats(4)
            status = call(lib.canopy_instance_read_span, inst, b"y", t0, t1, 4, out.pointer)
            allowed(status, OK, ERR_OVERFLOW)
            check(out.guards_intact() and (status == OK or out.zero()), f"[{t0}, {t1}): the buffer was written wrongly")
    # the test filter, a node with a history, at times a few seconds either side of 0 (far ones would take as long as the distance: it recomputes from its last checkpoint)
    for t in (-10 ** 12, -1, 0, 1, 10 ** 9, 3 * 10 ** 9):
        one.value = 9.0
        allowed(call(lib.canopy_instance_read_at, inst, b"f", t, ctypes.byref(one)), OK)
        out = Floats(4)
        allowed(call(lib.canopy_instance_read_span, inst, b"f", t, t + 1000, 4, out.pointer), OK)
        check(out.guards_intact(), 'out.guards_intact()')
    out = Floats(4)
    allowed(call(lib.canopy_instance_read_span, inst, b"nothing", 0, 100, 4, out.pointer), ERR_NODE)
    check(out.zero() and out.guards_intact(), 'out.zero() and out.guards_intact()')
    for text in TEXTS + [BIG]:
        out = Floats(4)
        allowed(call(lib.canopy_instance_read_span, inst, text, 0, 100, 4, out.pointer), OK, ERR_NODE)
        check(out.guards_intact(), 'out.guards_intact()')
    allowed(call(lib.canopy_instance_read_span, inst, None, 0, 100, 4, Floats(4).pointer), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_read_span, None, b"y", 0, 100, 4, Floats(4).pointer), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_read_span, inst, b"y", 0, 100, 4, None), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_inlet_span, None, 2, 0, 0, 100, 4, Floats(4).pointer), ERR_ARGUMENT)
    allowed(call(lib.canopy_instance_inlet_span, inst, 2, 0, 0, 100, 4, None), ERR_ARGUMENT)
    for node_id in INTS64 + [3, 99]:
        for inlet in INTS32:
            out = Floats(4)
            allowed(call(lib.canopy_instance_inlet_span, inst, node_id, inlet, 0, 100, 4, out.pointer), OK, ERR_NODE, ERR_PORT)
            check(out.guards_intact(), 'out.guards_intact()')
    # the biggest span, at the very limits of the times, through a filter (it must answer, not hang or overrun)
    big = Floats(65536)
    allowed(call(lib.canopy_instance_read_span, inst, b"y", INT64_MIN // 2, INT64_MAX // 2, 65536, big.pointer), OK)
    check(big.guards_intact(), 'big.guards_intact()')


def sweep_helpers_and_nulls(world):
    for status in list(range(-3, 30)) + [INT32_MAX, INT32_MIN]:
        text = call(lib.canopy_status_message, status)
        check(text and isinstance(text, bytes), 'text and isinstance(text, bytes)')
    check(call(lib.canopy_build_number) > 0 and call(lib.canopy_abi_version) > 0, 'call(lib.canopy_build_number) > 0 and call(lib.canopy_abi_version) > 0')
    check(call(lib.canopy_alloc_live) >= 0 and call(lib.canopy_alloc_total) >= call(lib.canopy_alloc_live), 'call(lib.canopy_alloc_live) >= 0 and call(lib.canopy_alloc_total) >= call(lib.canopy_alloc_live)')
    out, fraction, frame, time = i64(), ctypes.c_double(), i64(), i64()
    rates = [INT64_MIN, -1, 0, 1, 48000, 9223372036, 9223372037, INT64_MAX]
    for ns in INTS64:
        for rate in rates:
            allowed(call(lib.canopy_ns_to_frame, ns, rate, ctypes.byref(out)), OK, ERR_RATE, ERR_OVERFLOW)
            allowed(call(lib.canopy_ns_to_frame_fraction, ns, rate, ctypes.byref(frame), ctypes.byref(fraction)), OK, ERR_RATE, ERR_OVERFLOW)
            if rate in (1, 48000):
                allowed(call(lib.canopy_ns_to_frame, ns, rate, ctypes.byref(out)), OK, ERR_OVERFLOW)
    for n in INTS64:
        for index in (0, 1, -1, 65535, 65536, INT64_MAX, INT64_MIN):
            for t0, t1 in ((0, 100), (INT64_MIN, INT64_MAX), (INT64_MAX, INT64_MIN)):
                allowed(call(lib.canopy_sample_time, t0, t1, n, index, ctypes.byref(time)), OK, ERR_N, ERR_INDEX, ERR_OVERFLOW)
    # the calls a node makes, with no context: every one of them says so and does nothing
    one = f32(9.0)
    allowed(call(lib.canopy_inlet_at, None, 0, 0, ctypes.byref(one)), ERR_ARGUMENT)
    allowed(call(lib.canopy_inlet_span, None, 0, 0, 100, 4, Floats(4).pointer), ERR_ARGUMENT)
    check(not call(lib.canopy_scratch, None, 4) and not call(lib.canopy_ctx_state, None) and not call(lib.canopy_ctx_shared, None), 'not call(lib.canopy_scratch, None, 4) and not call(lib.canopy_ctx_state, None) and not call(lib.canopy_ctx_shared, None)')
    check(call(lib.canopy_ctx_upstream_stamp, None) == 0 and call(lib.canopy_ctx_int, None, 0) == 0 and call(lib.canopy_ctx_float, None, 0) == 0.0, 'call(lib.canopy_ctx_upstream_stamp, None) == 0 and call(lib.canopy_ctx_int, None, 0) == 0 and call(lib.canopy_ctx_float, None, 0) == 0.0')
    check(call(lib.canopy_ctx_string, None, 0) in (b"", None), 'call(lib.canopy_ctx_string, None, 0) in (b"", None)')
    call(lib.canopy_ctx_shared_changed, None)
    call(lib.canopy_ctx_retire, None, None, None)
    call(lib.canopy_ctx_set_message, None, b"nobody hears this")
    call(lib.canopy_ctx_set_message, None, None)


def declare_the_rest():
    """The functions of the DLL that engine_dll does not declare, with the types of their prototypes."""
    for name, header in header_prototypes().items():
        function = getattr(lib, name)
        if getattr(function, "argtypes", None) is None:
            kinds = {"i32": i32, "i64": i64, "u64": ctypes.c_uint64, "f32": f32, "f64": ctypes.c_double, "ptr": vp, "void": None, "u32": ctypes.c_uint32}
            function.restype = kinds[header[0]] if header[0] != "ptr" else vp
            function.argtypes = [kinds[k] for k in header[1]]


def test_py_every_exported_function_survives_null_and_extreme_arguments_and_answers_with_the_status_the_header_promises():
    import tempfile
    CALLED.clear()
    FAILS.clear()
    declare_the_rest()
    # (a few functions return text or pointers: say so before they are called)
    for name in ("canopy_status_message", "canopy_registry_last_error", "canopy_engine_last_error", "canopy_ctx_string"):
        getattr(lib, name).restype = cstr
    with tempfile.TemporaryDirectory() as directory:
        world = World(directory)
        try:
            for sweep in (sweep_graph_description, sweep_registry, sweep_engine, sweep_preview, sweep_instance, sweep_helpers_and_nulls):
                sweep(world)
        finally:
            world.close()
    problems = [f"{count} x {function}: {what}" for (function, what), count in sorted(FAILS.items())]
    missing = sorted(set(pe_exports(DLL)) - CALLED)
    if missing:
        problems.append(f"exported functions the sweep never calls: {missing}")
    assert not problems, "\n" + "\n".join(problems)
