"""The DLL as the Engine and Instance classes use it: loaded and version-checked once (`_lib.load_dll`), with the argument and result types of
every function declared, and the status codes of src/canopy.h.

`ctypes.CDLL` releases the GIL during every call, so a query in one thread does not stop the others (design section 8)."""
import ctypes
import threading

from . import _lib

OK, ERR_OVERFLOW, ERR_N, ERR_MEMORY, ERR_GRAPH, ERR_NODE, ERR_PORT, ERR_ARGUMENT, ERR_BUSY = 0, 2, 3, 9, 10, 11, 12, 13, 14
ERR_INDEX = 4
MAX_N = 65536
BOUNDARY_KINDS = {0: "inlet", 1: "outlet"}              # CANOPY_BOUNDARY_INLET, CANOPY_BOUNDARY_OUTLET
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1

_vp, _i32, _i64, _f32, _f64, _str = ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64, ctypes.c_float, ctypes.c_double, ctypes.c_char_p
_p_float, _p_i32, _p_i64 = ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int64)

_SIGNATURES = [
    ("canopy_status_message", _str, [_i32]),
    ("canopy_registry_new", _vp, []),
    ("canopy_registry_free", None, [_vp]),
    ("canopy_graph_new", _vp, []),
    ("canopy_graph_free", None, [_vp]),
    ("canopy_graph_add_node", _i32, [_vp, _i64, _str]),
    ("canopy_graph_set_int", _i32, [_vp, _i64, _str, _i64]),
    ("canopy_graph_set_float", _i32, [_vp, _i64, _str, _f64]),
    ("canopy_graph_set_string", _i32, [_vp, _i64, _str, _str]),
    ("canopy_graph_set_knob", _i32, [_vp, _i64, _str, _f32]),
    ("canopy_graph_connect", _i32, [_vp, _i64, _str, _i64, _str]),
    ("canopy_engine_new", _vp, [_vp]),
    ("canopy_engine_free", _i32, [_vp]),
    ("canopy_engine_set_graph", _i32, [_vp, _vp]),
    ("canopy_engine_last_error", _str, [_vp]),
    ("canopy_engine_set_boundary", _i32, [_vp, _str, _f32]),
    ("canopy_engine_boundary_count", _i32, [_vp]),
    ("canopy_engine_boundary_at", _i32, [_vp, _i32, ctypes.c_char_p, _i32, _p_i32, _p_i32, _p_i64]),
    ("canopy_engine_new_instance", _vp, [_vp]),
    ("canopy_instance_free", None, [_vp]),
    ("canopy_instance_read_at", _i32, [_vp, _str, _i64, _p_float]),
    ("canopy_instance_read_span", _i32, [_vp, _str, _i64, _i64, _i64, _p_float]),
]

_dll = None
_lock = threading.Lock()


def dll():
    """The loaded DLL with every function's types declared (made on first use; RuntimeError if it does not match this package)."""
    global _dll
    with _lock:
        if _dll is None:
            loaded = _lib.load_dll()
            for name, restype, argtypes in _SIGNATURES:
                function = getattr(loaded, name)
                function.restype, function.argtypes = restype, argtypes
            _dll = loaded
        return _dll


def message(status):
    """The DLL's fixed English sentence for a status code."""
    text = dll().canopy_status_message(status)
    return text.decode("utf-8") if text else f"status {status}"
