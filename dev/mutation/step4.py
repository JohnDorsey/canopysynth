"""The mutations of plan step 4 (generation numbers, records, compile-and-swap with packages, the hidden filter, the engine's lock): run with
    python dev/mutation/mutate.py dev/mutation/step4.py
Every one of them should be reported as caught; see mutate.py. (A name starting N is canopy_install.c, P canopy_package.c, F canopy_test_nodes.c,
T canopy_time.c, I canopy_instance.c, E canopy_engine.c, R canopy_registry.c, K canopy_core.h.)
The lock faults K01 to K05 (and K06 slowly) deadlock or crash the test program: run_tests.py stops a C test program after CANOPY_TEST_TIMEOUT
seconds (default 180), so run those with CANOPY_TEST_TIMEOUT=30. Mutations that would loop or recurse without end are left out on purpose.
(E52, the lock of the internal by-ID boundary write, was dropped at step 5: only tests call it now; the host's by-name write has its own lock check, step5.py C23.)"""
N = "src/canopy_install.c"
P = "src/canopy_package.c"
F = "src/canopy_test_nodes.c"
T = "src/canopy_time.c"
I = "src/canopy_instance.c"
E = "src/canopy_engine.c"
R = "src/canopy_registry.c"
K = "src/canopy_core.h"


def without(block, *pieces):
    """(block, block with each of the pieces taken out): for removing a lock and its unlock from the same function."""
    new = block
    for piece in pieces:
        assert piece in new, piece
        new = new.replace(piece, "")
    return block, new


SHARED_LOCK = "    canopy_lock_shared(&engine->lock);\n"
SHARED_UNLOCK = "    canopy_unlock_shared(&engine->lock);"
EXCLUSIVE_LOCK = "    canopy_lock_exclusive(&engine->lock);\n"
EXCLUSIVE_UNLOCK = "    canopy_unlock_exclusive(&engine->lock);"

SET_KNOB = (SHARED_LOCK + "    status = find_knob(engine, node_id, inlet, &slot);\n    if (status == CANOPY_OK) canopy_slot_write(slot, value);\n"
            + SHARED_UNLOCK)
GET_KNOB = (SHARED_LOCK + "    status = find_knob(engine, node_id, inlet, &slot);\n    if (status == CANOPY_OK) {\n        if (generation) *generation"
            " = (uint64_t)atomic_load_explicit(&slot->generation, memory_order_acquire);   /* generation first, then value */\n"
            "        if (value) *value = canopy_slot_load(slot);\n    }\n" + SHARED_UNLOCK)
NODE_COUNT = (SHARED_LOCK + "    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n    count = graph ? graph->n_nodes : 0;\n"
              + SHARED_UNLOCK)
GRAPH_SERIAL = (SHARED_LOCK + "    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n"
                "    serial = graph ? (int64_t)graph->serial : 0;\n" + SHARED_UNLOCK)
SET_BOUNDARY = (SHARED_LOCK + "    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n"
                "    node = graph ? canopy_compiled_find(graph, node_id, NULL) : NULL;\n    if (!node) status = CANOPY_ERR_NODE;\n"
                "    else if (!(node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT)) status = CANOPY_ERR_ARGUMENT;\n"
                "    else canopy_slot_write(&node->record->boundary, value);                  /* any float: nothing is clamped on the way in */\n"
                + SHARED_UNLOCK)
ACTION_UNLOCK = "    if (exclusive) canopy_unlock_exclusive(&engine->lock); else canopy_unlock_shared(&engine->lock);"
ACTION = (SHARED_LOCK + "    graph = atomic_load_explicit(&engine->current, memory_order_acquire);\n"
          "    node = graph ? canopy_compiled_find(graph, node_id, &index) : NULL;\n"
          "    if (node && (node->type->flags & CANOPY_FLAG_SERVICE)) {      /* the buttons of a node with a thread of its own make and free its instance: exclusive */\n"
          "        canopy_unlock_shared(&engine->lock);\n        if (action_window_hook) action_window_hook();\n        canopy_lock_exclusive(&engine->lock);\n"
          "        exclusive = 1;\n"
          "        graph = atomic_load_explicit(&engine->current, memory_order_acquire);          /* (it may have changed while the lock was let go) */\n"
          "        node = graph ? canopy_compiled_find(graph, node_id, &index) : NULL;\n    }\n"
          "    if (!node) {\n        status = CANOPY_ERR_NODE;\n"
          "    } else if (node->type->handlers.on_action) {\n        struct CanopyCtx ctx;\n        canopy_ctx_setup(&ctx, node, index, NULL);\n"
          "        node->type->handlers.on_action(&ctx, action);\n    }\n" + ACTION_UNLOCK)
SET_GRAPH = (EXCLUSIVE_LOCK + "    status = canopy_install(engine, compiled);\n    if (status == CANOPY_OK) canopy_reclaim(engine);\n"
             "    else memory_error(engine);\n" + EXCLUSIVE_UNLOCK)
COLLECT = EXCLUSIVE_LOCK + "    canopy_reclaim(engine);\n    held = engine->n_compiled;\n" + EXCLUSIVE_UNLOCK
INSTANCE_FREE = (EXCLUSIVE_LOCK + "    instance_remove_locked(engine, instance);\n"
                 "    canopy_reclaim(engine);                              /* the graphs and shared resources this instance was the last to need */\n"
                 + EXCLUSIVE_UNLOCK)

MUTATIONS = [
    # ---- records: found by node ID and type, kept sorted, made and destroyed with their nodes ----
    ("N01 records ignore the node type", N, "    if (type != record->type) return (uintptr_t)type < (uintptr_t)record->type ? -1 : 1;\n", "    (void)type;\n"),
    ("N02 a record is never found again", N, "        if (record_order(id, type, engine->records[mid]) > 0) lo = mid + 1; else hi = mid;",
     "        if (record_order(id, type, engine->records[mid]) >= 0) lo = mid + 1; else hi = mid;"),
    ("N03 record leaks its pool", N, "    canopy_pool_free(&record->pool);\n    canopy_free(record);", "    canopy_free(record);"),
    ("N04 record uid is always 1", N, "    record->uid = ++engine->uid;", "    record->uid = 1;"),
    ("N05 fresh records not marked (a failed install keeps them)", N, "    record->fresh = 1;\n", ""),
    ("N06 new knob slot starts at 0", N, "        canopy_slot_set(record->knobs[j], node->knob_start[j]);", "        canopy_slot_set(record->knobs[j], 0.0f);"),
    ("N07 records array grows without keeping its content", N, "canopy_realloc(engine->records, (size_t)engine->cap_records * sizeof *grown,",
     "canopy_realloc(engine->records, 0,"),
    ("N08 inserting a record loses the last one", N,
     "    memmove(&engine->records[position + 1], &engine->records[position], (size_t)(engine->n_records - position) * sizeof *engine->records);",
     "    memmove(&engine->records[position + 1], &engine->records[position],\n"
     "            (size_t)(engine->n_records - position > 0 ? engine->n_records - position - 1 : 0) * sizeof *engine->records);"),
    ("N09 destroying a record skips destroy_shared", N, "    if (record->shared && record->type->handlers.destroy_shared) {\n        struct CanopyCtx ctx;\n        canopy_ctx_setup(&ctx, node, 0, NULL);",
     "    if (record->shared && record->type->handlers.destroy_shared && node == NULL) {\n        struct CanopyCtx ctx;\n        canopy_ctx_setup(&ctx, node, 0, NULL);"),
    ("N10 a destroyed record stays in the array", N,
     "    if (found) {\n        memmove(&engine->records[position], &engine->records[position + 1], (size_t)(engine->n_records - position - 1) * sizeof *engine->records);\n"
     "        engine->n_records--;\n    }", "    (void)found;\n    (void)position;"),
    # ---- the stamp of a node: what goes into its digest and its list of generation counters ----
    ("N11 digest ignores the record uid", N, "            *digest = canopy_mix(*digest, node->record->uid);\n", ""),
    ("N12 digest ignores the settings' generations", N,
     "            for (s = 0; s < node->type->n_settings; s++) *digest = canopy_mix(*digest, node->setting_gen[s]);\n",
     "            (void)s;\n"),
    ("N13 digest ignores the wiring", N,
     "            if (digest) *digest = canopy_mix(*digest, link.node < 0 ? 0xFFFFFFFFULL : (uint64_t)c->nodes[link.node].id * 64u + (uint64_t)link.outlet);\n", ""),
    ("N14 digest ignores which outlet", N, "(uint64_t)c->nodes[link.node].id * 64u + (uint64_t)link.outlet);", "(uint64_t)c->nodes[link.node].id * 64u);"),
    ("N15 knob generations not in the list", N, "                if (list) list[count] = &node->knobs[j]->generation;\n                count++;\n", ""),
    ("N16 shared generation not in the list", N, "        if (list) list[count] = &node->record->shared_generation;\n        count++;\n", ""),
    ("N17 boundary generation not in the list", N,
     "        if (node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT) {\n            if (list) list[count] = &node->record->boundary.generation;\n            count++;\n        }\n", ""),
    ("N18 second walk uses the first walk's token", N, "        (void)cone_walk(compiled, i, 2 * i + 2, mark, stack, node->cone_gens, &digest);",
     "        (void)cone_walk(compiled, i, 2 * i + 1, mark, stack, node->cone_gens, &digest);"),
    ("N19 count of generation counters not stored", N, "        node->n_cone_gens = count;\n", ""),
    ("N20 static digest not stored", N, "        node->cone_static = digest;\n", ""),
    # ---- when a setting counts as changed ----
    ("N21 floats compared by value (0.0 == -0.0)", N, "    case CANOPY_SETTING_FLOAT: return memcmp(&a->f, &b->f, sizeof a->f) != 0;",
     "    case CANOPY_SETTING_FLOAT: return a->f != b->f;"),
    ("N22 strings compared by address", N, "    case CANOPY_SETTING_PATH: return strcmp(a->s, b->s) != 0;", "    case CANOPY_SETTING_PATH: return a->s != b->s;"),
    ("N23 strings never differ", N, "    case CANOPY_SETTING_PATH: return strcmp(a->s, b->s) != 0;", "    case CANOPY_SETTING_PATH: return 0;"),
    ("N24 integers differ only when they go up", N, "    default: return a->i != b->i;", "    default: return a->i < b->i;"),
    ("N25 integers differ only when they go down", N, "    default: return a->i != b->i;", "    default: return a->i > b->i;"),
    # ---- freeing graphs and records ----
    ("N26 records are never destroyed", N, "        if (record && --record->refs == 0) record_destroy(engine, record, &compiled->nodes[i]);",
     "        if (record && --record->refs == -1) record_destroy(engine, record, &compiled->nodes[i]);"),
    ("N27 a record is destroyed with the first graph that goes", N,
     "        if (record && --record->refs == 0) record_destroy(engine, record, &compiled->nodes[i]);",
     "        if (record) { record->refs = 0; record_destroy(engine, record, &compiled->nodes[i]); }"),
    ("N28 reclaiming ignores what the instances still use", N, "        if (oldest < floor) floor = oldest;\n", ""),
    ("N29 reclaiming frees the graph an instance still runs", N, "engine->compiled[0]->serial < floor && engine->compiled[0] != current",
     "engine->compiled[0]->serial <= floor && engine->compiled[0] != current"),
    ("N30 reclaiming does not reap the instances", N, "        canopy_instance_reap(engine->instances[k]);\n", ""),
    ("N31 reclaiming never frees anything", N, "    uint64_t floor = current ? current->serial : UINT64_MAX;", "    uint64_t floor = 0;"),
    # ---- installing ----
    ("N32 serial not advanced", N, "    compiled->serial = ++engine->serial;", "    compiled->serial = engine->serial;"),
    ("N33 knob slots not linked to the nodes", N, "        for (j = 0; j < node->type->n_inlets; j++) node->knobs[j] = record->knobs[j];\n", ""),
    ("N34 shared resource made at every install", N, "        if (!record->shared_made) {\n            record->shared_made = 1;",
     "        if (record->shared_made >= 0) {\n            record->shared_made = 1;"),
    ("N35 node does not get the shared resource", N, "        node->shared = record->shared;\n", ""),
    ("N36 settings' generations never bumped", N, "            node->setting_gen[s] = record->setting_gen[s] + (changed ? 1u : 0u);",
     "            node->setting_gen[s] = record->setting_gen[s];\n            (void)changed;"),
    ("N37 settings' generations bumped at every install", N, "            node->setting_gen[s] = record->setting_gen[s] + (changed ? 1u : 0u);",
     "            node->setting_gen[s] = record->setting_gen[s] + 1u;\n            (void)changed;"),
    ("N38 the record does not keep the new generations", N,
     "        for (s = 0; s < node->type->n_settings; s++) record->setting_gen[s] = node->setting_gen[s];\n", ""),
    ("N39 a description never moves the knob slots", N,
     "            if (canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))\n                canopy_slot_write(node->knobs[j], node->knob_start[j]);",
     "            if (j < 0 && canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))\n                canopy_slot_write(node->knobs[j], node->knob_start[j]);"),
    ("N40 a description always counts as a knob write", N,
     "            if (canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))\n                canopy_slot_write(node->knobs[j], node->knob_start[j]);",
     "            if (j >= 0 || canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))\n                canopy_slot_write(node->knobs[j], node->knob_start[j]);"),
    ("N41 published node not recorded", N, "        record->published = node;\n", ""),
    ("N42 references to a record not counted", N, "        record->refs++;\n", ""),
    ("N43 fresh flag not cleared", N, "        record->fresh = 0;\n", ""),
    ("N44 the new graph is not published", N, "    atomic_store_explicit(&engine->current, compiled, memory_order_release);\n    canopy_free(built);",
     "    canopy_free(built);"),
    ("N45 packages not queued for the instances", N, "        if (built) canopy_package_enqueue(engine->instances[i], built[i]);", "        if (built) (void)i;"),
    ("N46 failed install leaves the graph in the list", N, "    engine->n_compiled--;                                          /* (the graph is the last one in the list) */\n", ""),
    ("N47 failed install keeps the packages built so far", N, "    for (i = 0; i < n_built; i++) canopy_package_discard(built[i]);\n", ""),
    ("N48 failed install keeps the records it made", N,
     "        if (record->fresh) {\n            const CanopyCNode *node = canopy_compiled_find(compiled, record->id, NULL);\n            record_destroy(engine, record, node);\n        }",
     "        (void)record;"),
    ("N49 install leaks its mark array", N, "    canopy_free(built);\n    canopy_free(mark);\n    canopy_free(stack);\n    return CANOPY_OK;",
     "    canopy_free(built);\n    canopy_free(stack);\n    return CANOPY_OK;"),
    # ---- packages ----
    ("P01 arena block has no room to align", P, "    block = canopy_alloc((size_t)floats * sizeof(float) + 64);", "    block = canopy_alloc((size_t)floats * sizeof(float));"),
    ("P02 discarded package keeps the states made for it", P, "            if (package->fresh[i] && handlers->destroy_instance) {",
     "            if (package->fresh[i] && handlers->destroy_instance && i < 0) {"),
    ("P03 discarded package leaks its arena", P, "    canopy_free(package->new_arena_block);\n    canopy_free(package);\n}", "    canopy_free(package);\n}"),
    ("P04 package starts from the running graph, not the planned one", P, "    const CanopyCompiled *from = instance->planned_graph;",
     "    const CanopyCompiled *from = instance->graph;"),
    ("P05 a bigger arena is never prepared", P, "    if (to->arena_floats > instance->planned_arena_floats) {", "    if (to->arena_floats < 0) {"),
    ("P06 state carried over a change of node type", P, "from->nodes[j].id == to->nodes[i].id && from->nodes[j].type == to->nodes[i].type) {",
     "from->nodes[j].id == to->nodes[i].id) {"),
    ("P07 carried flag not set", P, "            package->carried[j] = 1;\n", ""),
    ("P08 fresh state made for carried nodes too", P, "        if (package->map[i] < 0 && handlers->create_instance) {", "        if (handlers->create_instance) {"),
    ("P09 planned graph not advanced", P, "    instance->planned_graph = package->to;\n", ""),
    ("P10 state taken from the wrong place", P, "package->map[i] >= 0 ? instance->states[package->map[i]] : package->fresh[i];",
     "package->map[i] >= 0 ? instance->states[i] : package->fresh[i];"),
    ("P11 old state table not remembered", P, "    package->old_states = instance->states;\n", ""),
    ("P12 package never marked done", P,
     "    atomic_store_explicit(&package->done, 1, memory_order_release);                          /* last: from here the installing thread owns the rest */",
     "    (void)package;"),
    ("P13 only one package applied per query", P, "    while ((next = atomic_load_explicit(&instance->applied->next, memory_order_acquire)) != NULL) {",
     "    if ((next = atomic_load_explicit(&instance->applied->next, memory_order_acquire)) != NULL) {"),
    ("P14 disposing destroys the carried states too", P, "        if (!package->carried[j] && package->old_states[j] && handlers->destroy_instance) {",
     "        if (package->old_states[j] && handlers->destroy_instance) {"),
    ("P15 old arena leaked", P, "    canopy_free(package->old_arena_block);\n    canopy_free(package->map);", "    canopy_free(package->map);"),
    ("P16 old state table leaked", P, "    canopy_free(package->old_states);\n    canopy_free(package->old_arena_block);", "    canopy_free(package->old_arena_block);"),
    ("P17 package's fresh array leaked", P,
     "    canopy_free(package->fresh);                         /* (the states in it are in new_states now: the instance's table) */", "    (void)package;"),
    ("P18 reaping disposes packages that are not applied yet", P,
     "        if (!next || !atomic_load_explicit(&next->done, memory_order_acquire)) break;", "        if (!next) break;"),
    ("P19 spent packages leaked", P,
     "        canopy_free(instance->first);                    /* the instance has moved past it: it only ever reads `applied->next` */\n", ""),
    ("P20 oldest serial too new", P, "    return next ? next->from->serial : instance->first->to->serial;", "    return next ? next->to->serial : instance->first->to->serial;"),
    ("P21 teardown keeps the packages never applied", P, "            canopy_package_discard(package);\n            package = following;", "            package = following;"),
    ("P22 teardown keeps the states in use", P,
     "            if (instance->states[i] && handlers->destroy_instance) {\n                struct CanopyCtx ctx;\n                canopy_ctx_setup(&ctx, &instance->graph->nodes[i], i, instance->states[i]);",
     "            if (instance->states[i] && handlers->destroy_instance && i < 0) {\n                struct CanopyCtx ctx;\n                canopy_ctx_setup(&ctx, &instance->graph->nodes[i], i, instance->states[i]);"),
    ("P23 teardown leaks the last package", P, "    canopy_free(instance->arena_block);\n    canopy_free(instance->first);\n    canopy_free(instance);",
     "    canopy_free(instance->arena_block);\n    canopy_free(instance);"),
    ("P24 teardown leaks the arena", P, "    canopy_free(instance->states);\n    canopy_free(instance->arena_block);", "    canopy_free(instance->states);"),
    ("P25 teardown leaks the state table", P, "    canopy_free(instance->states);\n    canopy_free(instance->arena_block);", "    canopy_free(instance->arena_block);"),
    ("P26 new instance not entered in the engine's list", P, "    engine->instances[engine->n_instances++] = instance;\n", ""),
    ("P27 freed instance stays in the engine's list", P, "            engine->instances[k] = engine->instances[--engine->n_instances];\n            break;", "            break;"),
    ("P28 no reclaiming after an instance is freed", P,
     "    canopy_reclaim(engine);                              /* the graphs and shared resources this instance was the last to need */\n", ""),
    # ---- the hidden filter ----
    ("F01 filter never forgets", F, "    if (!filter->have_stamp || stamp != filter->stamp) {", "    if (!filter->have_stamp) {"),
    ("F02 filter always forgets", F, "    if (!filter->have_stamp || stamp != filter->stamp) {", "    if (!filter->have_stamp || stamp != filter->stamp || run->rate > 0) {"),
    ("F04 zero checkpoint interval allowed", F, "    if (seconds < 1) seconds = 1;\n", ""),
    ("F05 huge checkpoint interval not limited", F,
     "    if (seconds > 3600000) seconds = 3600000;                              /* (a thousand hours: keeps seconds * rate far from overflow) */\n", ""),
    ("F06 wrong checkpoint interval", F, "    run->interval = seconds * run->rate;", "    run->interval = seconds + run->rate;"),
    ("F07 checkpoint 0 (the initial state) not kept", F,
     "        (void)append_checkpoint(filter, run->initial);                     /* checkpoint 0: the state before the first sample */\n", ""),
    ("F08 coefficient not limited", F, "    a = fminf(fmaxf((c + 1.0f) * 0.5f, 0.0f), 1.0f);", "    a = (c + 1.0f) * 0.5f;"),
    ("F09 coefficient limited from above only", F, "    a = fminf(fmaxf((c + 1.0f) * 0.5f, 0.0f), 1.0f);", "    a = fminf((c + 1.0f) * 0.5f, 1.0f);"),
    ("F10 coefficient limited from below only", F, "    a = fminf(fmaxf((c + 1.0f) * 0.5f, 0.0f), 1.0f);", "    a = fmaxf((c + 1.0f) * 0.5f, 0.0f);"),
    ("F11 render does not stop at the last checkpoint", F,
     "        if (j >= filter->n_checkpoints) j = filter->n_checkpoints - 1;     /* ahead of the checkpoints made so far: from the last one */\n", ""),
    ("F12 cursor used one sample too far", F, "        if (filter->cursor_k + 1 <= k && filter->cursor_k + 1 > s) {", "        if (filter->cursor_k + 1 <= k + 1 && filter->cursor_k + 1 > s) {"),
    ("F13 cursor pair used for any sample", F, "    if (filter->cursor_valid && filter->cursor_k == k) {\n        *y0 = filter->cursor_y[0];",
     "    if (filter->cursor_valid) {\n        *y0 = filter->cursor_y[0];"),
    ("F14 just before the first sample the next value is wrong", F, "        *y1 = k + 1 < 0 ? run->initial : y_at(run, 0);",
     "        *y1 = k + 1 < 0 ? run->initial : y_at(run, 1);"),
    ("F15 no interpolation between samples", F, "    return (float)((double)y0 + fraction * ((double)y1 - (double)y0));",
     "    return (float)((double)y0 + 0.0 * fraction * ((double)y1 - (double)y0));"),
    ("F16 coefficient read from the signal inlet", F, "    c = canopy_inlet_at(run->ctx, 1, t);", "    c = canopy_inlet_at(run->ctx, 0, t);"),
    ("F17 initial value ignored", F, "    run->initial = (float)canopy_ctx_float(ctx, SETTING_INITIAL);", "    run->initial = 0.0f;"),
    ("F18 checkpoints lost when their array grows", F,
     "canopy_realloc(filter->checkpoints, (size_t)filter->cap_checkpoints * sizeof(float), (size_t)capacity * sizeof(float));",
     "canopy_realloc(filter->checkpoints, 0, (size_t)capacity * sizeof(float));"),
    ("F19 filter leaks its checkpoints", F, "    canopy_free(filter->checkpoints);\n    canopy_free(filter);", "    canopy_free(filter);"),
    # ---- the grid times of the filter: canopy_frame_to_ns ----
    ("T10 grid times rounded down", T, "    low = (2 * rem * NS_PER_SEC + rate) / (2 * rate);          /* round half up; rem < rate <= 384000, so the numerator is below 7.7e14 */",
     "    low = (rem * NS_PER_SEC) / rate;"),
    ("T11 negative frames not floored", T,
     "    if (rem < 0) {                                            /* floor division: 0 <= rem < rate */\n        rem += rate;\n        sec -= 1;\n    }\n    low = (2",
     "    low = (2"),
    ("T12 whole seconds beyond the range accepted", T, "    if (sec > INT64_MAX / NS_PER_SEC || sec < INT64_MIN / NS_PER_SEC) return CANOPY_ERR_OVERFLOW;\n", ""),
    ("T13 sum beyond the range accepted", T, "    if (base > INT64_MAX - low) return CANOPY_ERR_OVERFLOW;\n", ""),
    ("T14 rates above the limit accepted", T, "    if (rate < 1 || rate > CANOPY_INTERNAL_RATE_MAX) return CANOPY_ERR_RATE;\n    sec = frame / rate;",
     "    if (rate < 1) return CANOPY_ERR_RATE;\n    sec = frame / rate;"),
    # ---- the context a node sees, and the host's entries ----
    ("I41 shared change does not bump the generation", I,
     "    if (ctx && ctx->node && ctx->node->record) atomic_fetch_add_explicit(&ctx->node->record->shared_generation, 1, memory_order_acq_rel);",
     "    (void)ctx;"),
    ("I44 span query does not adopt", I, "    canopy_instance_adopt(instance);\n    if (!canopy_compiled_find(instance->graph, node_id, &index)) {",
     "    if (!canopy_compiled_find(instance->graph, node_id, &index)) {"),
    ("I45 point query does not adopt", I,
     "    canopy_instance_adopt(instance);                                          /* a newly installed graph is taken up here, by swapping pointers */\n", ""),
    ("I46 handlers get no instance state", I, "    ctx->state = instance->states[node_index];\n", "    ctx->state = NULL;\n"),
    ("I47 a handler outside a query sees the stamp of nothing", I, "    if (!ctx || !ctx->node) return 0;\n    node = ctx->node;", "    if (!ctx || !ctx->node) return 1;\n    node = ctx->node;"),
    # ---- the engine ----
    ("E60 any node accepts a boundary value", E, "    else if (!(node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT)) status = CANOPY_ERR_ARGUMENT;\n", ""),
    ("E61 boundary write does not bump the generation", E, "    else canopy_slot_write(&node->record->boundary, value);", "    else canopy_slot_set(&node->record->boundary, value);"),
    ("E62 boundary value refused when not finite", E, "    else canopy_slot_write(&node->record->boundary, value);",
     "    else if (!isfinite(value)) status = CANOPY_ERR_ARGUMENT;\n    else canopy_slot_write(&node->record->boundary, value);"),
    ("E63 boundary value clamped to 1", E, "    else canopy_slot_write(&node->record->boundary, value);",
     "    else canopy_slot_write(&node->record->boundary, value > 1.0f ? 1.0f : value);"),
    ("E65 engine free leaks the list of graphs", E, "    canopy_free(engine->compiled);\n    canopy_free(engine->records);", "    canopy_free(engine->records);"),
    ("E66 engine free leaks the list of instances", E, "    canopy_free(engine->instances);\n", ""),
    ("E67 engine free leaks the list of records", E, "    canopy_free(engine->compiled);\n    canopy_free(engine->records);", "    canopy_free(engine->compiled);"),
    ("E68 collect reports one graph whatever is held", E, "    held = engine->n_compiled;", "    held = 1;"),
    ("E69 collect does not reclaim", E, "    canopy_reclaim(engine);\n    held = engine->n_compiled;", "    held = engine->n_compiled;"),
    ("E70 no reclaiming after a successful install", E, "    if (status == CANOPY_OK) canopy_reclaim(engine);\n    else memory_error(engine);",
     "    if (status != CANOPY_OK) memory_error(engine);"),
    ("E71 failed install gives no message", E, "    if (status == CANOPY_OK) canopy_reclaim(engine);\n    else memory_error(engine);",
     "    if (status == CANOPY_OK) canopy_reclaim(engine);"),
    # ---- registry: the boundary flag is for built-in types only ----
    ("R10 any type may have a boundary slot", R, "builtin ? (CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_SLOT | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_SERVICE) : CANOPY_FLAGS_KNOWN",
     "(CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_SLOT | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_SERVICE)"),
    ("R11 no type may have a boundary slot", R, "builtin ? (CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_SLOT | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_SERVICE) : CANOPY_FLAGS_KNOWN",
     "CANOPY_FLAGS_KNOWN"),
    # ---- the lock: a missing lock is only seen by a test that holds it itself ----
    ("K01 exclusive lock does nothing", K, "static inline void canopy_lock_exclusive(CanopyLock *lock) { AcquireSRWLockExclusive(lock); }",
     "static inline void canopy_lock_exclusive(CanopyLock *lock) { (void)lock; }"),
    ("K02 exclusive unlock does nothing", K, "static inline void canopy_unlock_exclusive(CanopyLock *lock) { ReleaseSRWLockExclusive(lock); }",
     "static inline void canopy_unlock_exclusive(CanopyLock *lock) { (void)lock; }"),
    ("K03 shared lock does nothing", K, "static inline void canopy_lock_shared(CanopyLock *lock) { AcquireSRWLockShared(lock); }",
     "static inline void canopy_lock_shared(CanopyLock *lock) { (void)lock; }"),
    ("K04 shared lock is exclusive", K, "static inline void canopy_lock_shared(CanopyLock *lock) { AcquireSRWLockShared(lock); }",
     "static inline void canopy_lock_shared(CanopyLock *lock) { AcquireSRWLockExclusive(lock); }"),
    ("K05 shared unlock matches the exclusive lock", K, "static inline void canopy_unlock_shared(CanopyLock *lock) { ReleaseSRWLockShared(lock); }",
     "static inline void canopy_unlock_shared(CanopyLock *lock) { ReleaseSRWLockExclusive(lock); }"),
    ("K07 no exclusive locking at all", K,
     "static inline void canopy_lock_exclusive(CanopyLock *lock) { AcquireSRWLockExclusive(lock); }\n"
     "static inline void canopy_unlock_exclusive(CanopyLock *lock) { ReleaseSRWLockExclusive(lock); }",
     "static inline void canopy_lock_exclusive(CanopyLock *lock) { (void)lock; }\n"
     "static inline void canopy_unlock_exclusive(CanopyLock *lock) { (void)lock; }"),
    ("K08 no shared locking at all", K,
     "static inline void canopy_lock_shared(CanopyLock *lock) { AcquireSRWLockShared(lock); }\n"
     "static inline void canopy_unlock_shared(CanopyLock *lock) { ReleaseSRWLockShared(lock); }",
     "static inline void canopy_lock_shared(CanopyLock *lock) { (void)lock; }\n"
     "static inline void canopy_unlock_shared(CanopyLock *lock) { (void)lock; }"),
    ("E50 set_knob takes no lock", E, *without(SET_KNOB, SHARED_LOCK, SHARED_UNLOCK)),
    ("E51 get_knob takes no lock", E, *without(GET_KNOB, SHARED_LOCK, SHARED_UNLOCK)),
    ("E53 action takes no lock", E, *without(ACTION, SHARED_LOCK, ACTION_UNLOCK)),
    ("E54 node_count takes no lock", E, *without(NODE_COUNT, SHARED_LOCK, SHARED_UNLOCK)),
    ("E55 graph_serial takes no lock", E, *without(GRAPH_SERIAL, SHARED_LOCK, SHARED_UNLOCK)),
    ("E56 set_graph takes no lock", E, *without(SET_GRAPH, EXCLUSIVE_LOCK, EXCLUSIVE_UNLOCK)),
    ("E57 collect takes no lock", E, *without(COLLECT, EXCLUSIVE_LOCK, EXCLUSIVE_UNLOCK)),
    ("P30 instance_free takes no lock", P, *without(INSTANCE_FREE, EXCLUSIVE_LOCK, EXCLUSIVE_UNLOCK)),
    ("K06 a query takes the lock", I, "    if (!instance || !acquire(instance)) return 0.0f;\n    canopy_instance_adopt(instance);",
     "    if (!instance || !acquire(instance)) return 0.0f;\n    canopy_lock_shared(&instance->engine->lock);\n    canopy_instance_adopt(instance);\n"
     "    canopy_unlock_shared(&instance->engine->lock);"),
]
