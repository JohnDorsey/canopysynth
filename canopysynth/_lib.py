# SPDX-License-Identifier: GPL-3.0-or-later
"""Loading the DLL, and refusing to run against one that does not match this Python package."""
import ctypes
import os

from .version import ABI_VERSION, CANOPYSYNTH_BUILD

DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "canopysynth.dll")


def check_versions(dll):
    """Raises RuntimeError unless the DLL's delivery counter and descriptor layout version are the ones this package was made for."""
    dll.canopy_build_number.restype = ctypes.c_int32
    dll.canopy_abi_version.restype = ctypes.c_int32
    build, abi = dll.canopy_build_number(), dll.canopy_abi_version()
    if build != CANOPYSYNTH_BUILD:
        raise RuntimeError(f"canopysynth.dll is build {build} but the Python package is build {CANOPYSYNTH_BUILD}: rebuild the DLL "
                           f"(python run_tests.py builds it)")
    if abi != ABI_VERSION:
        raise RuntimeError(f"canopysynth.dll has node-descriptor layout version {abi} but the Python package expects {ABI_VERSION}")


def load_dll(path=None):
    """The DLL, loaded with ctypes and version-checked (RuntimeError on a mismatch, OSError if it cannot be loaded)."""
    dll = ctypes.CDLL(path or DLL_PATH)
    check_versions(dll)
    return dll
