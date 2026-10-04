"""The mutations of plan step 5 (the boundary nodes and the host calls by name): run with
    python dev/mutation/mutate.py dev/mutation/step5.py
Every one of them should be reported as caught; see mutate.py. (A name starting B is canopy_boundary.c, C the boundary parts of canopy_engine.c,
I canopy_instance.c, R canopy_registry.c, K canopy_core.h.) A mutation that deadlocks is stopped by run_tests.py after CANOPY_TEST_TIMEOUT seconds."""
B = "src/canopy_boundary.c"
C = "src/canopy_engine.c"
I = "src/canopy_instance.c"
R = "src/canopy_registry.c"

def without(block, *pieces):
    """(block, block with each piece taken out): a lock and its unlock go together."""
    new = block
    for piece in pieces:
        assert piece in new, piece
        new = new.replace(piece, "")
    return block, new


SHARED_LOCK = "    canopy_lock_shared(&engine->lock);\n"
SHARED_UNLOCK = "    canopy_unlock_shared(&engine->lock);\n"
SET_BOUNDARY_BY_NAME = (SHARED_LOCK + "    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n"
                        "    entry = graph ? canopy_compiled_find_boundary(graph, name) : NULL;\n"
                        "    if (!entry || entry->kind != CANOPY_BOUNDARY_INLET) status = CANOPY_ERR_NODE;\n"
                        "    else canopy_slot_write(&graph->nodes[entry->node].record->boundary, value);          /* any float: nothing is clamped on the way in */\n"
                        + SHARED_UNLOCK)
BOUNDARY_AT = (SHARED_LOCK + "    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n"
               "    if (!graph || index < 0 || index >= graph->n_boundary) {\n        status = CANOPY_ERR_INDEX;\n    } else {\n"
               "        const CanopyBoundary *entry = &graph->boundary[index];\n        size_t length = strlen(entry->name);\n"
               "        if (name_capacity > 0) {\n            size_t copied = length < (size_t)name_capacity - 1 ? length : (size_t)name_capacity - 1;\n"
               "            memcpy(name, entry->name, copied);\n            name[copied] = '\\0';\n        }\n"
               "        if (name_length) *name_length = (int32_t)length;\n        if (kind) *kind = entry->kind;\n"
               "        if (node_id) *node_id = graph->nodes[entry->node].id;\n    }\n" + SHARED_UNLOCK)

MUTATIONS = [
    # ---- the two node types ----
    ("B01 inlet gives 0 whatever the host wrote (point)", B, '    (void)outlet; (void)t;\n    *out = canopy_ctx_boundary_value(ctx);\n    return CANOPY_OK;', '    (void)outlet; (void)t; (void)ctx;\n    *out = 0.0f;\n    return CANOPY_OK;'),
    ("B02 inlet span leaves the last sample", B, "    for (i = 0; i < n; i++) out[i] = value;", "    for (i = 0; i < n - 1; i++) out[i] = value;"),
    ("B03 inlet span writes one past out", B, "    for (i = 0; i < n; i++) out[i] = value;", "    for (i = 0; i <= n; i++) out[i] = value;"),
    ("B04 inlet value clamped", B, '    *out = canopy_ctx_boundary_value(ctx);\n    return CANOPY_OK;', '    *out = canopy_ctx_boundary_value(ctx) > 1.0f ? 1.0f : canopy_ctx_boundary_value(ctx);\n    return CANOPY_OK;'),
    ("B05 inlet has no boundary slot flag", B, "CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_BOUNDARY_SLOT;", "CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE;"),
    ("B06 inlet is not marked as a boundary node", B, "CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_BOUNDARY_SLOT;", "CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_SLOT;"),
    ("B07 outlet is not marked as a boundary node", B, "    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE;\n", "    type.flags = CANOPY_FLAG_REALTIME_SAFE;\n"),
    ("B08 outlet has a boundary slot", B, "    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE;\n", "    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_BOUNDARY_SLOT;\n"),
    ("B09 inlet not realtime safe", B, "CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_BOUNDARY_SLOT;", "CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_BOUNDARY_SLOT;"),
    ("B10 outlet not realtime safe", B, "    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE;\n", "    type.flags = CANOPY_FLAG_BOUNDARY_NODE;\n"),
    ("B11 outlet's inlet starts away from 0", B, 'static const CanopyInletDesc OUTLET_INLETS[] = {{"in", "In", 0.0f}};', 'static const CanopyInletDesc OUTLET_INLETS[] = {{"in", "In", 0.5f}};'),
    ("B12 name starts as something", B, '{CANOPY_BOUNDARY_NAME_KEY, CANOPY_SETTING_STRING, 0, 0.0, "", 0, NULL}', '{CANOPY_BOUNDARY_NAME_KEY, CANOPY_SETTING_STRING, 0, 0.0, "x", 0, NULL}'),
    ("B13 inlet has no name widget", B, "    type.n_settings = 1; type.settings = NAME_SETTING;\n    type.n_widgets = 1; type.widgets = NAME_WIDGET;\n    type.handlers.query_at = inlet_at;",
     "    type.n_settings = 1; type.settings = NAME_SETTING;\n    type.handlers.query_at = inlet_at;"),
    ("B14 inlet is not registered by key boundary_inlet", B, '    type.key = "boundary_inlet";', '    type.key = "boundary_in";'),
    ("B15 inlet's outlet is called differently", B, 'static const CanopyOutletDesc INLET_OUTLETS[] = {{"out", "Out"}};', 'static const CanopyOutletDesc INLET_OUTLETS[] = {{"output", "Out"}};'),
    # ---- the registry ----
    ("R20 a new registry has no built-in types", R, "    if (registry && (canopy_boundary_register_types(registry) != CANOPY_OK || canopy_fileread_register_type(registry) != CANOPY_OK ||\n                     canopy_preview_register_type(registry) != CANOPY_OK)) {",
     "    if (registry && (canopy_boundary_register_types(registry) == 12345 || canopy_fileread_register_type(registry) == 12345 ||\n                     canopy_preview_register_type(registry) == 12345)) {"),
    ("R21 a registry that fails to get its types is returned", R, "        canopy_registry_free(registry);\n        return NULL;\n    }\n    return registry;", "        return NULL;\n    }\n    return registry;"),
    ("R22 any type may be a boundary node", R, "CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_SLOT | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_SERVICE) : CANOPY_FLAGS_KNOWN))",
     "CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_SLOT | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_SERVICE) : CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_NODE))"),
    ("R23 a boundary node without a name setting is accepted", R, "        if (!has_name) return fail(registry,", "        if (has_name < 0) return fail(registry,"),
    ("R24 a name setting of any kind is accepted", R, "&& type->settings[i].kind == CANOPY_SETTING_STRING)\n                has_name = 1;", ")\n                has_name = 1;"),
    # ---- compiling: names ----
    ("C01 empty name accepted", C, "            if (name[0] == '\\0')\n", "            if (name[0] == '\\0' && name[1] == 'x')\n"),
    ("C02 duplicate names accepted", C, "        if (strcmp(c->boundary[i].name, c->boundary[i - 1].name) == 0) {", "        if (strcmp(c->boundary[i].name, c->boundary[i - 1].name) == 0 && i < 0) {"),
    ("C03 names not sorted", C, "    qsort(c->boundary, (size_t)count, sizeof *c->boundary, compare_boundary);\n", ""),
    ("C04 names sorted backwards", C, "    return strcmp(((const CanopyBoundary *)a)->name, ((const CanopyBoundary *)b)->name);", "    return strcmp(((const CanopyBoundary *)b)->name, ((const CanopyBoundary *)a)->name);"),
    ("C05 kind swapped", C, "(node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT) ? CANOPY_BOUNDARY_INLET : CANOPY_BOUNDARY_OUTLET;", "(node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT) ? CANOPY_BOUNDARY_OUTLET : CANOPY_BOUNDARY_INLET;"),
    ("C06 count of boundary nodes not stored", C, "    c->n_boundary = count;\n", ""),
    ("C07 only inlets are named", C, "        if (node->type->flags & CANOPY_FLAG_BOUNDARY_NODE) {\n            int32_t setting", "        if ((node->type->flags & CANOPY_FLAG_BOUNDARY_NODE) && (node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT)) {\n            int32_t setting"),
    ("C08 message names the wrong node", C, "c->boundary[i].name, LL(c->nodes[first].id), LL(c->nodes[second].id));", "c->boundary[i].name, LL(c->nodes[first].id), LL(c->nodes[second].id - c->nodes[second].id + c->nodes[first].id));"),
    ("C09 lookup compares the wrong way", C, "        if (order < 0) lo = mid + 1; else hi = mid - 1;", "        if (order > 0) lo = mid + 1; else hi = mid - 1;"),
    ("C10 lookup finds only the first half", C, "    int32_t lo = 0, hi = graph->n_boundary - 1;", "    int32_t lo = 0, hi = graph->n_boundary / 2;"),
    ("C11 lookup matches a prefix", C, "        int order = strcmp(graph->boundary[mid].name, name);", "        int order = strncmp(graph->boundary[mid].name, name, strlen(name));"),
    # ---- the host's writes and listing ----
    ("C20 write accepts an outlet", C, "    if (!entry || entry->kind != CANOPY_BOUNDARY_INLET) status = CANOPY_ERR_NODE;", "    if (!entry) status = CANOPY_ERR_NODE;"),
    ("C21 write does not bump the generation", C, "    else canopy_slot_write(&graph->nodes[entry->node].record->boundary, value);", "    else canopy_slot_set(&graph->nodes[entry->node].record->boundary, value);"),
    ("C22 write clamps the value", C, "    else canopy_slot_write(&graph->nodes[entry->node].record->boundary, value);", "    else canopy_slot_write(&graph->nodes[entry->node].record->boundary, value > 1.0f ? 1.0f : value);"),
    ("C23 write takes no lock", C, *without(SET_BOUNDARY_BY_NAME, SHARED_LOCK, SHARED_UNLOCK)),
    ("C24 write does not refuse a NULL name", C, "    if (!engine || !name) return CANOPY_ERR_ARGUMENT;\n    canopy_lock_shared(&engine->lock);\n    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n    entry =",
     "    if (!engine) return CANOPY_ERR_ARGUMENT;\n    canopy_lock_shared(&engine->lock);\n    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n    entry ="),
    ("C25 count is always the number of nodes", C, "    count = graph ? graph->n_boundary : 0;", "    count = graph ? graph->n_nodes : 0;"),
    ("C26 listing allows one index too many", C, "    if (!graph || index < 0 || index >= graph->n_boundary) {", "    if (!graph || index < 0 || index > graph->n_boundary) {"),
    ("C27 listing allows a negative index", C, "    if (!graph || index < 0 || index >= graph->n_boundary) {", "    if (!graph || index >= graph->n_boundary) {"),
    ("C28 a cut name is not terminated", C, "            name[copied] = '\\0';\n", ""),
    ("C29 a name is cut one byte too early", C, "size_t copied = length < (size_t)name_capacity - 1 ? length : (size_t)name_capacity - 1;", "size_t copied = length < (size_t)name_capacity - 1 ? length : (size_t)name_capacity - 2;"),
    ("C30 listing copies one byte past the buffer", C, "size_t copied = length < (size_t)name_capacity - 1 ? length : (size_t)name_capacity - 1;", "size_t copied = length < (size_t)name_capacity ? length : (size_t)name_capacity;"),
    ("C31 name length is the cut length", C, "        if (name_length) *name_length = (int32_t)length;", "        if (name_length) *name_length = (int32_t)(length < (size_t)name_capacity ? length : (size_t)name_capacity);"),
    ("C32 kind not reported", C, "        if (kind) *kind = entry->kind;\n", "        (void)kind;\n"),
    ("C33 node id is the index", C, "        if (node_id) *node_id = graph->nodes[entry->node].id;", "        if (node_id) *node_id = entry->node;"),
    ("C34 listing takes no lock", C, *without(BOUNDARY_AT, SHARED_LOCK, SHARED_UNLOCK)),
    # ---- the instance's reads ----
    ("I20 a boundary inlet can be read", I, "    return entry && entry->kind == CANOPY_BOUNDARY_OUTLET ? entry->node : -1;", "    return entry ? entry->node : -1;"),
    ("I21 point read does not adopt", I, '    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);\n    index = outlet_by_name(instance, name);\n    if (index >= 0) status = inlet_at', '    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    index = outlet_by_name(instance, name);\n    if (index >= 0) status = inlet_at'),
    ("I22 span read does not adopt", I, "    canopy_instance_adopt(instance);\n    index = outlet_by_name(instance, name);\n    if (index < 0) {", "    index = outlet_by_name(instance, name);\n    if (index < 0) {"),
    ("I23 unknown name does not zero-fill a span", I, "    if (index < 0) {\n        zero_fill(out, n);\n        status = CANOPY_ERR_NODE;", "    if (index < 0) {\n        status = CANOPY_ERR_NODE;"),
    ("I24 span read busy flag never released", I, "        status = inlet_span(instance, index, 0, t0, t1, n, out);\n    }\n    release(instance);\n    return status;\n}\n\nint32_t canopy_instance_inlet_span",
     "        status = inlet_span(instance, index, 0, t0, t1, n, out);\n    }\n    return status;\n}\n\nint32_t canopy_instance_inlet_span"),
    ("I25 reads the outlet's second inlet slot", I, '    if (index >= 0) status = inlet_at(instance, index, 0, t, out);', '    if (index >= 0) status = inlet_at(instance, index, 1, t, out);'),
    ("I26 span read of a NULL name is not refused", I, "    if (!instance || !name) {\n        zero_fill(out, n);\n        return CANOPY_ERR_ARGUMENT;\n    }\n    if (!acquire(instance)) {\n        zero_fill(out, n);\n        return CANOPY_ERR_BUSY;\n    }\n    canopy_instance_adopt(instance);\n    index = outlet_by_name",
     "    if (!instance) {\n        zero_fill(out, n);\n        return CANOPY_ERR_ARGUMENT;\n    }\n    if (!acquire(instance)) {\n        zero_fill(out, n);\n        return CANOPY_ERR_BUSY;\n    }\n    canopy_instance_adopt(instance);\n    index = outlet_by_name"),
]
