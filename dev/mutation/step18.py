# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations for the exception-safe `Engine.new_instance` (build 23, found through the flaky real out-of-memory test): the order of its steps and what it stores. It is a
Python file, so the runner skips the build and the C tests, and AREAS limits the tests to test_bridge.py. Run with
    python dev/mutation/mutate.py dev/mutation/step18.py
Every one should be reported as caught. Not here: dropping the check for a NULL pointer from C (nothing in test_bridge.py makes C run out of memory; the real
out-of-memory test of test_shutdown.py, and the C tests that fail the Nth allocation, are what see it)."""
E = "canopysynth/engine.py"

AREAS = ["bridge"]

MUTATIONS = [
    ("N01 the Python object is built after the C call again (a failure there loses the instance)", E,
     "            instance = Instance(self, None)\n            count = self._instances + 1\n            pointer = self._lib.canopy_engine_new_instance(handle)\n",
     "            count = self._instances + 1\n            pointer = self._lib.canopy_engine_new_instance(handle)\n            instance = Instance(self, None)\n"),
    ("N02 the instance is not counted", E, "            self._instances = count\n", ""),
    ("N03 the instance is counted twice", E, "count = self._instances + 1", "count = self._instances + 2"),
    ("N04 the instance never gets its pointer", E, "            instance._pointer = pointer\n", ""),
]
