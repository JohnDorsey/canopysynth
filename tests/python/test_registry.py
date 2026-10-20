# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the node-type descriptor seen from Python (ctypes mirror), the registry through the DLL, and the version checks."""
import ctypes
import os
import re

import canopysynth
from canopysynth import _descriptor as d
from canopysynth import _lib

dll = _lib.load_dll()

dll.canopy_registry_new.restype = ctypes.c_void_p
dll.canopy_registry_free.argtypes = [ctypes.c_void_p]
dll.canopy_registry_register.argtypes = [ctypes.c_void_p, ctypes.POINTER(d.NodeType)]
dll.canopy_registry_register.restype = ctypes.c_int32
dll.canopy_registry_count.argtypes = [ctypes.c_void_p]
dll.canopy_registry_count.restype = ctypes.c_int32
dll.canopy_registry_at.argtypes = [ctypes.c_void_p, ctypes.c_int32]
dll.canopy_registry_at.restype = ctypes.POINTER(d.NodeType)
dll.canopy_registry_find.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
dll.canopy_registry_find.restype = ctypes.POINTER(d.NodeType)
dll.canopy_registry_last_error.argtypes = [ctypes.c_void_p]
dll.canopy_registry_last_error.restype = ctypes.c_char_p
dll.canopy_status_message.argtypes = [ctypes.c_int32]
dll.canopy_status_message.restype = ctypes.c_char_p

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OK, ERR_ABI, ERR_KEY, ERR_DUPLICATE, ERR_DESCRIPTOR = 0, 5, 6, 7, 8


def strings(*items):
    array = (ctypes.c_char_p * len(items))(*[s.encode() for s in items])
    return array


class Made:
    """A descriptor built from the ctypes classes, with everything it points to kept alive."""

    def __init__(self, key="python.thing"):
        self.keep = []
        self.type = d.NodeType()
        t = self.type
        t.abi_version = canopysynth.version.ABI_VERSION
        t.struct_size = ctypes.sizeof(d.NodeType)
        t.key, t.name, t.type_version, t.flags = key.encode(), b"Python Thing", 2, d.FLAG_REALTIME_SAFE | d.FLAG_HAS_INTERNAL_RATE
        inlets = (d.InletDesc * 2)(d.InletDesc(b"input", b"Input", 0.0), d.InletDesc(b"gain", b"Gain", -0.5))
        outlets = (d.OutletDesc * 2)(d.OutletDesc(b"left", b"Left"), d.OutletDesc(b"right", b"Right"))
        modes = strings("a", "b")
        settings = (d.SettingDesc * 3)(
            d.SettingDesc(b"count", 0, 7, 0.0, None, 0, None),
            d.SettingDesc(b"path", 3, 0, 0.0, b"C:/x.wav", 0, None),
            d.SettingDesc(b"mode", 4, 1, 0.0, None, 2, ctypes.cast(modes, d.c_char_pp)))
        widgets = (d.WidgetDesc * 2)(d.WidgetDesc(0, b"Open", None, b"open", 0, None),
                                     d.WidgetDesc(2, b"Mode", b"mode", None, 0, None))
        self.keep += [inlets, outlets, modes, settings, widgets]
        t.n_inlets, t.inlets = 2, ctypes.cast(inlets, ctypes.POINTER(d.InletDesc))
        t.n_outlets, t.outlets = 2, ctypes.cast(outlets, ctypes.POINTER(d.OutletDesc))
        t.n_settings, t.settings = 3, ctypes.cast(settings, ctypes.POINTER(d.SettingDesc))
        t.n_widgets, t.widgets = 2, ctypes.cast(widgets, ctypes.POINTER(d.WidgetDesc))
        t.scratch_buffers = 3
        self.at = d.QUERY_AT(lambda ctx, outlet, time, out: 0)
        t.handlers.query_at = self.at

    def register(self, registry):
        return dll.canopy_registry_register(registry, ctypes.byref(self.type))


def test_py_the_ctypes_descriptor_has_the_same_size_as_the_c_struct():
    # the registry refuses a struct_size smaller than the C struct, so a too-small mirror is caught below; a too-big one would pass silently,
    # so the exact size is pinned here and, with the same literal, in tests/c/test_registry.c (x64 MSVC)
    assert ctypes.sizeof(d.NodeType) == 160
    registry = dll.canopy_registry_new()
    try:
        made = Made()
        made.type.struct_size = ctypes.sizeof(d.NodeType) - 1
        assert made.register(registry) == ERR_ABI
        made.type.struct_size = ctypes.sizeof(d.NodeType)
        assert made.register(registry) == OK
    finally:
        dll.canopy_registry_free(registry)


def test_py_a_descriptor_registered_from_python_reads_back_with_all_its_metadata_and_the_added_internal_rate_setting():
    registry = dll.canopy_registry_new()
    try:
        base = dll.canopy_registry_count(registry)                  # the built-in node types are in a new registry already
        made = Made()
        assert made.register(registry) == OK and dll.canopy_registry_count(registry) == base + 1
        info = d.read_node_type(dll.canopy_registry_find(registry, b"python.thing"))
        assert info["key"] == "python.thing" and info["name"] == "Python Thing" and info["type_version"] == 2
        assert info["realtime_safe"] and info["has_internal_rate"]
        assert [(i["key"], i["label"], i["default_knob"]) for i in info["inlets"]] == [("input", "Input", 0.0), ("gain", "Gain", -0.5)]
        assert [(o["key"], o["label"]) for o in info["outlets"]] == [("left", "Left"), ("right", "Right")]
        assert [(s["key"], s["kind"], s["default"], s["choices"]) for s in info["settings"]] == [
            ("count", "int", 7, []), ("path", "path", "C:/x.wav", []), ("mode", "choice", 1, ["a", "b"]),
            (d.INTERNAL_RATE_KEY, "int", d.INTERNAL_RATE_DEFAULT, [])]
        assert [(w["kind"], w["label"], w["setting"], w["action"]) for w in info["widgets"]] == [
            ("button", "Open", None, "open"), ("choice", "Mode", "mode", None)]
        assert info["scratch_buffers"] == 3
        assert info["handlers"]["query_at"] and not info["handlers"]["query_span"] and not info["handlers"]["create_shared"]
        same = dll.canopy_registry_at(registry, base)
        assert d.read_node_type(same) == info
    finally:
        dll.canopy_registry_free(registry)


def test_py_the_registry_refuses_bad_registrations_with_the_documented_codes_and_a_message():
    registry = dll.canopy_registry_new()
    try:
        base = dll.canopy_registry_count(registry)
        assert Made("nodots").register(registry) == ERR_KEY
        assert Made("Vendor.Thing").register(registry) == ERR_KEY
        assert Made("python.ok").register(registry) == OK
        assert Made("python.ok").register(registry) == ERR_DUPLICATE
        assert b"python.ok" in dll.canopy_registry_last_error(registry)
        bad_abi = Made("python.abi")
        bad_abi.type.abi_version = 99
        assert bad_abi.register(registry) == ERR_ABI
        bad_name = Made("python.noname")
        bad_name.type.name = b""
        assert bad_name.register(registry) == ERR_DESCRIPTOR
        assert dll.canopy_registry_count(registry) == base + 1
        for code in range(15):                          # 0 .. CANOPY_ERR_BUSY (14), the last status code
            assert len(dll.canopy_status_message(code)) > 3
        assert dll.canopy_status_message(15) == b"unknown status code"
    finally:
        dll.canopy_registry_free(registry)


def test_py_the_dll_and_the_package_agree_on_the_build_number_and_the_descriptor_layout_version():
    with open(os.path.join(ROOT, "src", "canopy_node.h"), encoding="utf-8") as handle:
        in_header = int(re.search(r"#define CANOPY_ABI_VERSION (\d+)", handle.read()).group(1))
    assert canopysynth.version.ABI_VERSION == in_header == dll.canopy_abi_version()
    assert dll.canopy_build_number() == canopysynth.CANOPYSYNTH_BUILD


class Settable:
    def __init__(self, value):
        self.value = value
        self.restype = None

    def __call__(self):
        return self.value


def fake(build, abi):
    dll_stub = type("Stub", (), {})()
    dll_stub.canopy_build_number = Settable(build)
    dll_stub.canopy_abi_version = Settable(abi)
    return dll_stub


def test_py_a_dll_of_another_build_or_descriptor_layout_is_refused_when_loading():
    good = fake(canopysynth.CANOPYSYNTH_BUILD, canopysynth.version.ABI_VERSION)
    _lib.check_versions(good)
    for stub, text in ((fake(canopysynth.CANOPYSYNTH_BUILD + 1, canopysynth.version.ABI_VERSION), "build"),
                       (fake(canopysynth.CANOPYSYNTH_BUILD, canopysynth.version.ABI_VERSION + 1), "layout version")):
        try:
            _lib.check_versions(stub)
        except RuntimeError as error:
            assert text in str(error)
        else:
            raise AssertionError("a mismatching DLL was accepted")
