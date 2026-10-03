"""ctypes mirror of the node-type descriptor in src/canopy_node.h, and a reader that turns a registered descriptor into plain Python data.

The C header is the single source of truth: the layout below must match it field for field (a test registers a descriptor built from these
classes and reads it back, and compares sizes with the DLL's own view)."""
import ctypes

c_char_pp = ctypes.POINTER(ctypes.c_char_p)

# CANOPY_FLAG_*
FLAG_REALTIME_SAFE = 1
FLAG_HAS_INTERNAL_RATE = 2

# CANOPY_SETTING_* and CANOPY_WIDGET_*
SETTING_KINDS = {0: "int", 1: "float", 2: "string", 3: "path", 4: "choice"}
WIDGET_KINDS = {0: "button", 1: "text", 2: "choice", 3: "label"}

INTERNAL_RATE_KEY = "internal_sampling_rate"
INTERNAL_RATE_MIN, INTERNAL_RATE_MAX, INTERNAL_RATE_DEFAULT = 1, 384000, 48000


class InletDesc(ctypes.Structure):
    _fields_ = [("key", ctypes.c_char_p), ("label", ctypes.c_char_p), ("default_knob", ctypes.c_float)]


class OutletDesc(ctypes.Structure):
    _fields_ = [("key", ctypes.c_char_p), ("label", ctypes.c_char_p)]


class SettingDesc(ctypes.Structure):
    _fields_ = [("key", ctypes.c_char_p), ("kind", ctypes.c_int32), ("default_int", ctypes.c_int64),
                ("default_float", ctypes.c_double), ("default_string", ctypes.c_char_p),
                ("n_choices", ctypes.c_int32), ("choices", c_char_pp)]


class WidgetDesc(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int32), ("label", ctypes.c_char_p), ("setting", ctypes.c_char_p), ("action", ctypes.c_char_p),
                ("n_choices", ctypes.c_int32), ("choices", c_char_pp)]


CTX = ctypes.c_void_p
CREATE = ctypes.CFUNCTYPE(ctypes.c_void_p, CTX)
DESTROY = ctypes.CFUNCTYPE(None, CTX, ctypes.c_void_p)
QUERY_AT = ctypes.CFUNCTYPE(ctypes.c_float, CTX, ctypes.c_int32, ctypes.c_int64)
QUERY_SPAN = ctypes.CFUNCTYPE(ctypes.c_int32, CTX, ctypes.c_int32, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64,
                              ctypes.POINTER(ctypes.c_float))
ON_ACTION = ctypes.CFUNCTYPE(None, CTX, ctypes.c_char_p)


class Handlers(ctypes.Structure):
    _fields_ = [("create_shared", CREATE), ("destroy_shared", DESTROY), ("create_instance", CREATE), ("destroy_instance", DESTROY),
                ("query_at", QUERY_AT), ("query_span", QUERY_SPAN), ("on_action", ON_ACTION)]


class NodeType(ctypes.Structure):
    _fields_ = [("abi_version", ctypes.c_uint32), ("struct_size", ctypes.c_uint32), ("key", ctypes.c_char_p), ("name", ctypes.c_char_p),
                ("type_version", ctypes.c_int32), ("flags", ctypes.c_uint32),
                ("n_inlets", ctypes.c_int32), ("inlets", ctypes.POINTER(InletDesc)),
                ("n_outlets", ctypes.c_int32), ("outlets", ctypes.POINTER(OutletDesc)),
                ("n_settings", ctypes.c_int32), ("settings", ctypes.POINTER(SettingDesc)),
                ("n_widgets", ctypes.c_int32), ("widgets", ctypes.POINTER(WidgetDesc)),
                ("scratch_buffers", ctypes.c_int32), ("handlers", Handlers)]


def _text(value):
    return None if value is None else value.decode("utf-8")


def _choices(count, pointer):
    return [pointer[i].decode("utf-8") for i in range(count)] if count else []


def read_node_type(pointer):
    """A registered descriptor (a pointer to the registry's copy) as plain Python data: dicts and lists of str, int, float, bool."""
    t = pointer.contents if hasattr(pointer, "contents") else pointer
    settings = []
    for i in range(t.n_settings):
        s = t.settings[i]
        kind = SETTING_KINDS[s.kind]
        default = {"int": s.default_int, "float": s.default_float, "string": _text(s.default_string) or "",
                   "path": _text(s.default_string) or "", "choice": s.default_int}[kind]
        settings.append({"key": _text(s.key), "kind": kind, "default": default, "choices": _choices(s.n_choices, s.choices)})
    widgets = []
    for i in range(t.n_widgets):
        w = t.widgets[i]
        widgets.append({"kind": WIDGET_KINDS[w.kind], "label": _text(w.label), "setting": _text(w.setting), "action": _text(w.action),
                        "choices": _choices(w.n_choices, w.choices)})
    h = t.handlers
    return {
        "key": _text(t.key), "name": _text(t.name), "type_version": t.type_version,
        "realtime_safe": bool(t.flags & FLAG_REALTIME_SAFE), "has_internal_rate": bool(t.flags & FLAG_HAS_INTERNAL_RATE),
        "inlets": [{"key": _text(t.inlets[i].key), "label": _text(t.inlets[i].label), "default_knob": t.inlets[i].default_knob}
                   for i in range(t.n_inlets)],
        "outlets": [{"key": _text(t.outlets[i].key), "label": _text(t.outlets[i].label)} for i in range(t.n_outlets)],
        "settings": settings, "widgets": widgets, "scratch_buffers": t.scratch_buffers,
        "handlers": {name: bool(getattr(h, name)) for name, _type in Handlers._fields_},
    }
