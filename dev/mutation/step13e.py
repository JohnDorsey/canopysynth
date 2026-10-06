"""The mutations for what plan step 13's API fuzz found (tests/python/test_api_fuzz.py and the regression test in tests/python/test_engine_controls.py): the five
Engine calls that the editor uses and that passed their node ID, and the action's name, straight to ctypes. Run with
    python dev/mutation/mutate.py dev/mutation/step13e.py
Every one of them should be reported as caught (by the explicit regression test, and by the fuzz). They are all Python files, so the runner skips the build and
the C tests, and AREAS limits the tests to the two files."""
E = "canopysynth/engine.py"

AREAS = ["engine_controls", "api_fuzz"]

MUTATIONS = [
    ("Q01 action does not check its node ID", E,
     "        handle = self._handle()\n        node_id = _values.node_id(node_id)\n        raw = _values.text(action,", "        handle = self._handle()\n        raw = _values.text(action,"),
    ("Q02 action does not check that its name is text", E,
     "        raw = _values.text(action, f\"node {node_id}\", \"the name of an action\").encode(\"utf-8\")", "        raw = action.encode(\"utf-8\")"),
    ("Q03 node_message does not check its node ID", E,
     "        node_id = _values.node_id(node_id)\n        status, text = self._text(self._lib.canopy_engine_node_message, handle, node_id)",
     "        status, text = self._text(self._lib.canopy_engine_node_message, handle, node_id)"),
    ("Q04 preview_state does not check its node ID", E,
     "        node_id = _values.node_id(node_id)\n        playing, time_ns = ctypes.c_int32(), ctypes.c_int64()", "        playing, time_ns = ctypes.c_int32(), ctypes.c_int64()"),
    ("Q05 preview_set_time does not check its node ID", E,
     "        node_id = _values.node_id(node_id)\n        self._node_status(self._lib.canopy_preview_set_time(", "        self._node_status(self._lib.canopy_preview_set_time("),
    ("Q06 preview_warning does not check its node ID", E,
     "        node_id = _values.node_id(node_id)\n        status, text = self._text(self._lib.canopy_preview_warning, handle, node_id)",
     "        status, text = self._text(self._lib.canopy_preview_warning, handle, node_id)"),
    ("Q07 a closed engine is reported after the arguments are checked, not before", E,
     "        handle = self._handle()\n        node_id = _values.node_id(node_id)\n        raw = _values.text(action, f\"node {node_id}\", \"the name of an action\").encode(\"utf-8\")\n        self._node_status(",
     "        node_id = _values.node_id(node_id)\n        raw = _values.text(action, f\"node {node_id}\", \"the name of an action\").encode(\"utf-8\")\n        handle = self._handle()\n        self._node_status("),
]
