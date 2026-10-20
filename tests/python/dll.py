# SPDX-License-Identifier: GPL-3.0-or-later
"""A minimal ctypes view of the DLL for the tests of the C functions (the real Python bridge is built at plan step 9)."""
import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
lib = ctypes.CDLL(os.path.join(ROOT, "canopysynth", "canopysynth.dll"))

i64 = ctypes.c_int64
p_i64 = ctypes.POINTER(ctypes.c_int64)
p_double = ctypes.POINTER(ctypes.c_double)

# status codes (src/canopy.h)
OK, ERR_RATE, ERR_OVERFLOW, ERR_N, ERR_INDEX = 0, 1, 2, 3, 4
MAX_N = 65536
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1

lib.canopy_ns_to_frame.argtypes = [i64, i64, p_i64]
lib.canopy_ns_to_frame.restype = ctypes.c_int
lib.canopy_ns_to_frame_fraction.argtypes = [i64, i64, p_i64, p_double]
lib.canopy_ns_to_frame_fraction.restype = ctypes.c_int
lib.canopy_sample_time.argtypes = [i64, i64, i64, i64, p_i64]
lib.canopy_sample_time.restype = ctypes.c_int


def c_ns_to_frame(ns, rate):
    out = i64(0)
    status = lib.canopy_ns_to_frame(ns, rate, ctypes.byref(out))
    return status, out.value


def c_ns_to_frame_fraction(ns, rate):
    frame, fraction = i64(0), ctypes.c_double(0)
    status = lib.canopy_ns_to_frame_fraction(ns, rate, ctypes.byref(frame), ctypes.byref(fraction))
    return status, frame.value, fraction.value


def c_sample_time(t0, t1, n, i):
    out = i64(0)
    status = lib.canopy_sample_time(t0, t1, n, i, ctypes.byref(out))
    return status, out.value
