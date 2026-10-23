# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations for `canopy_engine_new_instance_into` (build 24) and for the Python code that uses it. The first three break C code (the build runs again before each and the C tests judge:
FOCUSED on the two C tests of the function), the last four break Python files (judged by test_bridge.py and test_c_api.py). Run with
    python dev/mutation/mutate.py dev/mutation/step19.py
Every one should be reported as caught; read WHICH test caught each (the flaky out-of-memory test of test_shutdown.py is not among the judges here, on purpose)."""
C = "src/canopy_package.c"
E = "canopysynth/engine.py"

ENV = {"CANOPY_C_TESTS": "new_instance_into;the_engine_cannot_be_freed_while_an_instance_exists"}
ARGS = ["bridge", "c_api"]

MUTATIONS = [
    ("I01 a failure leaves the slot as it was (stale)", C, "    *out = NULL;                                         /* written whatever happens: a caller never reads a stale value */\n", ""),
    ("I02 running out of memory is reported as success", C, "status = *out ? CANOPY_OK : CANOPY_ERR_MEMORY;", "status = CANOPY_OK;"),
    ("I03 no installed graph is reported as out of memory", C, "status = CANOPY_ERR_ARGUMENT;                    /* a call that is not allowed yet: no graph is installed */",
     "status = CANOPY_ERR_MEMORY;"),
    ("I04 the old function returns no instance", C, "    canopy_engine_new_instance_into(engine, &instance);  /* one path: a failure of either kind is a NULL */\n    return instance;\n",
     "    canopy_engine_new_instance_into(engine, &instance);  /* one path: a failure of either kind is a NULL */\n    return NULL;\n"),
    ("I05 the engine falls back to a number: it does not use the slot's pointer", E, "            instance._pointer = slot\n", "            instance._pointer = slot.value\n"),
    ("I06 the engine does not count the instance", E, "            self._instances = count\n", ""),
    ("I07 a status that is not out of memory is let through as success", E,
     "                raise MemoryError(\"the engine could not make an instance\")\n            if status != native.OK:\n                raise RuntimeError(native.message(status))\n",
     "                raise MemoryError(\"the engine could not make an instance\")\n"),
    ("I08 the engine passes no slot at all", E,
     "            reference = ctypes.byref(slot)\n            status = self._lib.canopy_engine_new_instance_into(handle, reference)\n",
     "            status = self._lib.canopy_engine_new_instance_into(handle, None)\n"),
]
