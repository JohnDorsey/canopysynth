# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the skeleton - the DLL builds, loads through ctypes, and agrees with the Python package."""
import ctypes
import os
import re

import canopysynth

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_py_the_dll_loads_through_ctypes_and_its_build_number_matches_the_header_and_the_package():
    dll = ctypes.CDLL(os.path.join(ROOT, "canopysynth", "canopysynth.dll"))
    dll.canopy_build_number.restype = ctypes.c_int32
    with open(os.path.join(ROOT, "src", "canopy.h"), encoding="utf-8") as handle:
        in_header = int(re.search(r"#define CANOPYSYNTH_BUILD (\d+)", handle.read()).group(1))
    assert dll.canopy_build_number() == in_header == canopysynth.CANOPYSYNTH_BUILD
