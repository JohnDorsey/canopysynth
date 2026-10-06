"""The mutations for plan step 13's sweep of the C API (tests/python/test_c_api.py), as a FOCUSED campaign (see mutate.py: ARGS and ENV): only that test (and the C test of
registry_at, which the sweep led to: an index one past the end reads past the entries, which only the AddressSanitizer run of the C tests sees) judges each fault. Run with
    python dev/mutation/mutate.py dev/mutation/step13f.py
Every one of them should be reported as caught. They remove a guard that the header promises (a NULL pointer, a negative capacity, an index past the end, a
value that is not finite, a node of the wrong kind) or the zero-filling of a failed span, and the sweep sees it as a crash (which ctypes reports as an access
violation), as a status that is not the documented one or as a canary that was written."""
ENV = {"CANOPY_C_TESTS": "registry_at_gives_null"}
ARGS = ["-k", "survives_null_and_extreme"]

MUTATIONS = [
    ("S01 set_boundary does not look for a NULL name", "src/canopy_engine.c",
     "    if (!engine || !name) return CANOPY_ERR_ARGUMENT;\n    canopy_lock_shared(&engine->lock);\n    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n    entry = ",
     "    if (!engine) return CANOPY_ERR_ARGUMENT;\n    canopy_lock_shared(&engine->lock);\n    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n    entry = "),
    ("S02 boundary_at accepts a negative capacity", "src/canopy_engine.c",
     "    if (!engine || name_capacity < 0 || (name_capacity > 0 && !name)) return CANOPY_ERR_ARGUMENT;", "    if (!engine || (name_capacity > 0 && !name)) return CANOPY_ERR_ARGUMENT;"),
    ("S03 a span query does not look for a NULL out", "src/canopy_instance.c",
     "    if (!out) return CANOPY_ERR_ARGUMENT;\n    if (canopy_span_overflows(t0, t1)) {", "    if (canopy_span_overflows(t0, t1)) {"),
    ("S04 a span that overflows is not zero-filled", "src/canopy_instance.c",
     "        zero_fill(out, n);\n        return CANOPY_ERR_OVERFLOW;", "        return CANOPY_ERR_OVERFLOW;"),
    ("S05 node_message accepts a negative capacity", "src/canopy_retire.c",
     "    if (!engine || capacity < 0 || (capacity > 0 && !buffer)) return CANOPY_ERR_ARGUMENT;", "    if (!engine || (capacity > 0 && !buffer)) return CANOPY_ERR_ARGUMENT;"),
    ("S06 registry_at allows an index equal to the count", "src/canopy_registry.c",
     "    if (!registry || index < 0 || index >= registry->count) return NULL;", "    if (!registry || index < 0 || index > registry->count) return NULL;"),
    ("S07 set_knob accepts NaN", "src/canopy_engine.c",
     "    if (!(value >= -1.0f && value <= 1.0f)) return CANOPY_ERR_ARGUMENT;        /* false for NaN too */",
     "    if (value < -1.0f || value > 1.0f) return CANOPY_ERR_ARGUMENT;"),
    ("S08 preview_state does not look at the node's type", "src/canopy_preview.c",
     "    if (node->type->handlers.create_shared != preview_create_shared) return CANOPY_ERR_ARGUMENT;", "    if (!node->type) return CANOPY_ERR_ARGUMENT;"),
    ("S09 ns_to_frame lets a rate of zero through", "src/canopy_time.c",
     "int canopy_ns_to_frame(int64_t ns, int64_t rate, int64_t *out)\n{\n    int64_t sec, rem, low, frame;\n    int status;\n    if (rate < 1 || rate > CANOPY_MAX_HELPER_RATE) return CANOPY_ERR_RATE;",
     "int canopy_ns_to_frame(int64_t ns, int64_t rate, int64_t *out)\n{\n    int64_t sec, rem, low, frame;\n    int status;\n    if (rate < 0 || rate > CANOPY_MAX_HELPER_RATE) return CANOPY_ERR_RATE;"),
    ("S10 read_at does not look for a NULL name", "src/canopy_instance.c",
     "    if (!instance || !name || !out) return CANOPY_ERR_ARGUMENT;\n    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);\n    index = outlet_by_name",
     "    if (!instance || !out) return CANOPY_ERR_ARGUMENT;\n    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);\n    index = outlet_by_name"),
    ("S11 set_audio_backend accepts any number", "src/canopy_engine.c",
     "    if (!engine || (backend != CANOPY_AUDIO_SYSTEM && backend != CANOPY_AUDIO_NULL)) return CANOPY_ERR_ARGUMENT;", "    if (!engine) return CANOPY_ERR_ARGUMENT;"),
]
