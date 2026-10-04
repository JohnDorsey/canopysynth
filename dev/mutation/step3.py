"""The mutations of plan step 3 (graph, engine, instance, queries, scratch arena, allocation): run with
    python dev/mutation/mutate.py dev/mutation/step3.py
Every one of them should be reported as caught; see mutate.py. (A name starting I is canopy_instance.c, E canopy_engine.c, T canopy_time.c,
A canopy_alloc.c, G canopy_graph.c, R canopy_registry.c; N canopy_install.c and P canopy_package.c, where the code of the engine's records
and of the instance lifecycle moved at step 4. The entries that moved were rewritten for the new places; I23, E26 and E43 described fields
that no longer exist and were dropped: step4.py has their successors, P27 and N03.)"""
I = "src/canopy_instance.c"
N = "src/canopy_install.c"
P = "src/canopy_package.c"
E = "src/canopy_engine.c"
T = "src/canopy_time.c"
A = "src/canopy_alloc.c"
G = "src/canopy_graph.c"
R = "src/canopy_registry.c"

MUTATIONS = [
    # ---- span request checks and zero-fill ----
    ("I01 n upper limit +1", I, "    if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;\n    if (!out)", "    if (n < 1 || n > CANOPY_MAX_N + 1) return CANOPY_ERR_N;\n    if (!out)"),
    ("I02 n = 0 allowed", I, "    if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;\n    if (!out)", "    if (n < 0 || n > CANOPY_MAX_N) return CANOPY_ERR_N;\n    if (!out)"),
    ("I03 NULL out not checked", I, "    if (!out) return CANOPY_ERR_ARGUMENT;\n    if (canopy_span_overflows", "    if (canopy_span_overflows"),
    ("I04 overflow not checked", I, "    if (canopy_span_overflows(t0, t1)) {\n        zero_fill(out, n);", "    if (canopy_span_overflows(t0, t1 - t1 + t0)) {\n        zero_fill(out, n);"),
    ("I05 overflow does not zero-fill", I, "    if (canopy_span_overflows(t0, t1)) {\n        zero_fill(out, n);\n        return CANOPY_ERR_OVERFLOW;", "    if (canopy_span_overflows(t0, t1)) {\n        return CANOPY_ERR_OVERFLOW;"),
    ("I06 node failure not zero-filled", I, "    if (status != CANOPY_OK) zero_fill(out, n);", "    if (status != CANOPY_OK) (void)0;"),
    ("I07 derived sample time off by one", I, "canopy_span_plan_time(&plan, i));", "canopy_span_plan_time(&plan, i + 1));"),
    ("I08 span-only point query asks t..t+1", I, "query_span(&ctx, outlet, t, t, 1, &value) != CANOPY_OK) value = 0.0f;", "query_span(&ctx, outlet, t, t + 1, 1, &value) != CANOPY_OK) value = 0.0f;"),
    ("I09 span-only point failure keeps node's value", I, "query_span(&ctx, outlet, t, t, 1, &value) != CANOPY_OK) value = 0.0f;", "query_span(&ctx, outlet, t, t, 1, &value) != CANOPY_OK) (void)0;"),
    # ---- the knob fallback ----
    ("I10 knob fallback returns 0 (point)", I, "    if (link.node < 0) return canopy_slot_load(node->knobs[inlet]);", "    if (link.node < 0) return 0.0f;"),
    ("I11 knob fallback leaves the last sample", I, "        for (i = 0; i < n; i++) out[i] = knob;", "        for (i = 0; i < n - 1; i++) out[i] = knob;"),
    ("I12 bad inlet not zero-filled", I, "        zero_fill(out, n);\n        return CANOPY_ERR_PORT;", "        return CANOPY_ERR_PORT;"),
    ("I27 bad inlet index not checked (point)", I, "    if (inlet < 0 || inlet >= node->type->n_inlets) return 0.0f;\n", ""),
    ("I21 unknown node not zero-filled", I, "        zero_fill(out, n);\n        status = CANOPY_ERR_NODE;\n    } else {\n        status = inlet_span(instance, index, inlet,", "        status = CANOPY_ERR_NODE;\n    } else {\n        status = inlet_span(instance, index, inlet,"),
    # ---- scratch ----
    ("I13 declared count not enforced", I, "    if (ctx->scratch_taken >= ctx->node->type->scratch_buffers) return NULL;\n", ""),
    ("I14 no rounding to cache lines", I, "    rounded = (n + 15) & ~(int64_t)15;", "    rounded = n;"),
    ("I15 taken count not incremented", I, "    ctx->scratch_taken++;\n    return block;", "    return block;"),
    ("I16 arena limit off by one", I, "    if (instance->arena_top + rounded > instance->arena_floats) return NULL;", "    if (instance->arena_top + rounded >= instance->arena_floats) return NULL;"),
    ("I17 arena not emptied on return", I, "    ctx->instance->arena_top = ctx->mark;", "    (void)ctx;"),
    ("I24 arena not aligned", P, "    if (block) *start = (float *)(((uintptr_t)block + 63u) & ~(uintptr_t)63u);", "    if (block) *start = (float *)block;"),
    ("I30 scratch allowed outside a query", I, "    if (!ctx || !ctx->querying) return NULL;\n    if (n < 1", "    if (!ctx) return NULL;\n    if (n < 1"),
    # ---- the busy guard and lifecycle ----
    ("I18 busy guard always lets in", I, "    if (atomic_exchange_explicit(&instance->busy, 1, memory_order_acquire) != 0) return 0;\n", "    (void)atomic_exchange_explicit(&instance->busy, 1, memory_order_acquire);\n"),
    ("I19 busy flag never released", I, "    atomic_store_explicit(&instance->busy, 0, memory_order_release);", "    (void)instance;"),
    ("I22 instance free skips destroy_instance", P, "            if (instance->states[i] && handlers->destroy_instance) {", "            if (instance->states[i] && handlers->destroy_instance && i < 0) {"),
    ("I25 ctx_state always NULL", I, "    return ctx ? ctx->state : NULL;", "    (void)ctx;\n    return NULL;"),
    ("I26 ctx_shared always NULL", I, "    return ctx && ctx->node ? ctx->node->shared : NULL;", "    (void)ctx;\n    return NULL;"),
    ("I20 typed getters ignore the kind", I, "    return kind == kind_a || kind == kind_b ? &ctx->node->settings[index] : NULL;", "    return kind >= 0 || kind_a == kind_b ? &ctx->node->settings[index] : NULL;"),
    ("I28 inlet_at allowed outside a query", I, "    if (!ctx || !ctx->querying) return 0.0f;", "    if (!ctx) return 0.0f;"),
    ("I29 inlet_span allowed outside a query", I, "    if (!ctx || !ctx->querying) {\n        zero_fill(out, n);", "    if (!ctx) {\n        zero_fill(out, n);"),
    # ---- compiling ----
    ("E01 duplicate node ID not found", E, "        if (keys[i].id == keys[i - 1].id) {", "        if (keys[i].id == keys[i - 1].id && i < 0) {"),
    ("E03 internal rate minimum unchecked", E, "given->i < CANOPY_INTERNAL_RATE_MIN ||", "given->i < 0 ||"),
    ("E03b internal rate maximum off by one", E, "given->i > CANOPY_INTERNAL_RATE_MAX))", "given->i > CANOPY_INTERNAL_RATE_MAX + 1))"),
    ("E04 choice index one too high accepted", E, "if (given->i < 0 || given->i >= desc->n_choices)", "if (given->i < 0 || given->i > desc->n_choices)"),
    ("E05 fan-in not refused", E, "        if (to->links[inlet].node >= 0)", "        if (to->links[inlet].node >= 1000000)"),
    ("E06 knob of exactly 1 refused", E, "        if (!(given->value >= -1.0f && given->value <= 1.0f))", "        if (!(given->value >= -1.0f && given->value < 1.0f))"),
    ("E08 knob NaN accepted", E, "        if (!(given->value >= -1.0f && given->value <= 1.0f))", "        if (given->value < -1.0f || given->value > 1.0f)"),
    ("E07 float call accepted for any setting", E, "(given->kind == CANOPY_VALUE_FLOAT && desc->kind == CANOPY_SETTING_FLOAT)", "(given->kind == CANOPY_VALUE_FLOAT)"),
    ("E28 default knob ignored", E, "            node->knob_start[j] = type->inlets[j].default_knob;", "            node->knob_start[j] = 0.0f;"),
    ("E29 default int setting ignored", E, "                value->i = desc->default_int;", "                value->i = 0;"),
    ("E27 nodes not sorted by id", E, "    qsort(keys, (size_t)n, sizeof *keys, compare_keys);\n", ""),
    ("E33 connection always uses outlet 0", E, "        to->links[inlet].outlet = outlet;", "        to->links[inlet].outlet = 0;"),
    ("E35 builder knob ignored", E, "        node->knob_start[inlet] = given->value;", "        (void)node;"),
    ("E20 node lookup compares the wrong way", E, "        if (found < id) lo = mid + 1; else hi = mid - 1;", "        if (found > id) lo = mid + 1; else hi = mid - 1;"),
    # ---- the scratch arena size ----
    ("E09 upstream weight not added", E, "        weight[x] = c->nodes[x].type->scratch_buffers + heaviest;", "        weight[x] = c->nodes[x].type->scratch_buffers;"),
    ("E10 branches summed instead of the heaviest", E, "            if (source >= 0 && weight[source] > heaviest) heaviest = weight[source];", "            if (source >= 0) heaviest += weight[source];"),
    ("E11 loop fallback uses the chain maximum", E, "    buffers = c->has_cycle ? total : best;", "    buffers = best;"),
    ("E11b always the sum of all nodes", E, "    buffers = c->has_cycle ? total : best;", "    buffers = total;"),
    ("E36 arena size limit removed", E, "buffers > INT64_MAX / ((int64_t)CANOPY_MAX_N * (int64_t)sizeof(float)) - 1", "buffers > INT64_MAX / ((int64_t)CANOPY_MAX_N * (int64_t)sizeof(float))"),
    # ---- installing, knobs, lifecycle ----
    ("E13 description never replaces a slot's value", N, "            if (canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))", "            if (j < 0 && canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))"),
    ("E14 description always counts as a write", N, "            if (canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))", "            if (j >= 0 || canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))"),
    ("E15 shared resource made at every install", N, "        if (!record->shared_made) {", "        if (record->shared_made >= 0) {"),
    ("E16 engine free skips destroy_shared", N, "    if (record->shared && record->type->handlers.destroy_shared) {", "    if (record->shared && record->type->handlers.destroy_shared && node == NULL) {"),
    ("E17b engine free does not check for instances at all", E, "    if (engine->n_instances - engine->n_service != 0) {            /* (the instances the engine made for its own nodes do not hold it) */\n        canopy_unlock_exclusive(&engine->lock);\n        return CANOPY_ERR_BUSY;\n    }\n", ""),
    ("E17 engine free refuses always", E, "    if (engine->n_instances - engine->n_service != 0) {", "    if (engine->n_instances - engine->n_service != 12345) {"),
    ("E18 set_knob accepts any value", E, "    if (!(value >= -1.0f && value <= 1.0f)) return CANOPY_ERR_ARGUMENT;        /* false for NaN too */\n", ""),
    ("E19 set_knob does not bump the generation", E, "    if (status == CANOPY_OK) canopy_slot_write(slot, value);", "    if (status == CANOPY_OK) canopy_slot_set(slot, value);"),
    ("E21 records ignore the node type", N, "    if (type != record->type) return (uintptr_t)type < (uintptr_t)record->type ? -1 : 1;\n", "    (void)type;\n"),
    ("E22 error message not cleared", E, r"    engine->error[0] = '\0';" + "\n", ""),
    ("E32 knob slots not linked into the nodes", N, "        for (j = 0; j < node->type->n_inlets; j++) node->knobs[j] = record->knobs[j];\n", ""),
    ("E38 action on unknown node is fine", E, "    if (!node) {\n        status = CANOPY_ERR_NODE;\n    } else if (node->type->handlers.on_action) {", "    if (!node) {\n        status = CANOPY_OK;\n    } else if (node->type->handlers.on_action) {"),
    ("E39 set_knob does not check the inlet", E, "    if (inlet < 0 || inlet >= node->type->n_inlets) return CANOPY_ERR_PORT;\n    *slot", "    *slot"),
    # ---- sample placement ----
    ("T01 floor correction removed", T, "        r += n;\n        q -= 1;\n    }\n    plan->t0", "        r += n;\n    }\n    plan->t0"),
    ("T02 sample offset wrong divisor", T, "(i * plan->r) / plan->n);", "(i * plan->r) / (plan->n + 1));"),
    # ---- allocation, pool, graph description ----
    ("A01 failures not sticky", A, "        if (left == 0) return 1;", "        if (left == 0) return 0;"),
    ("A02 realloc tail not zeroed", A, "    if (new_size > old_size) memset((char *)grown + old_size, 0, new_size - old_size);\n", "    (void)old_size;\n"),
    ("A03 pool leaks its block table", A, "    canopy_free(pool->blocks);\n    pool->blocks = NULL;", "    pool->blocks = NULL;"),
    ("A04 free does not count", A, "    free(block);\n    atomic_fetch_sub(&live_blocks, 1);", "    free(block);"),
    ("G01 setting kind recorded wrong", G, "    record->kind = kind;", "    record->kind = CANOPY_VALUE_INT;"),
    ("G02 knob value lost", G, "    knobs[graph->n_knobs].value = value;", "    knobs[graph->n_knobs].value = value * 0.0f;"),
    ("G03 connection goes to the wrong node", G, "    connections[graph->n_connections].to_node = to_node;", "    connections[graph->n_connections].to_node = to_node + 1;"),
    ("R01 registry entry leaks its pool", R, "    canopy_pool_free(&entry->pool);\n    canopy_free(entry);", "    canopy_free(entry);"),
    # ---- more: leaks (these prove the leak counting works) and two more compile-time faults ----
    ("E40 new knob slot starts at 0", N, "        canopy_slot_set(record->knobs[j], node->knob_start[j]);", "        canopy_slot_set(record->knobs[j], 0.0f);"),
    ("E41 in-degrees not counted", E, "                indegree[i]++;\n", ""),
    ("E42 engine free leaks the compiled graphs", E, "        canopy_free_graph(engine, oldest);\n    }\n    canopy_free(engine->compiled);", "        (void)oldest;\n    }\n    canopy_free(engine->compiled);"),
    ("E44 engine free leaks the records", E, "    canopy_free(engine->records);\n", ""),
    ("I31 instance leaks its arena", P, "    canopy_free(instance->states);\n    canopy_free(instance->arena_block);", "    canopy_free(instance->states);"),
    ("I32 instance leaks its state table", P, "    canopy_free(instance->states);\n    canopy_free(instance->arena_block);", "    canopy_free(instance->arena_block);"),
    ("G04 graph leaks its connections", G, "    canopy_free(graph->connections);\n", ""),
    # ---- writing one float past the end of `out`: the guard zones and the debug heap must notice ----
    ("I33 knob fill writes one float past out", I, "        for (i = 0; i < n; i++) out[i] = knob;", "        for (i = 0; i <= n; i++) out[i] = knob;"),
    ("I34 zero-fill writes one float past out", I, "    memset(out, 0, (size_t)n * sizeof(float));", "    memset(out, 0, ((size_t)n + 1) * sizeof(float));"),
    ("I35 derived span writes one float past out", I, "            for (i = 0; i < n; i++) {\n                ctx_begin(&ctx, instance, node_index);", "            for (i = 0; i <= n; i++) {\n                ctx_begin(&ctx, instance, node_index);"),
    # ---- faults that only AddressSanitizer can see: a read past a heap block, and a read of freed memory (silent in the other two runs) ----
    ("A36 reads one int past the end of a heap block", E, "    for (i = 0; i < n; i++) total += c->nodes[i].type->scratch_buffers;", "    for (i = 0; i < n; i++) total += c->nodes[i].type->scratch_buffers + (int64_t)(((volatile int32_t *)first)[n + 1] & 0);"),
    ("A37 reads a block after freeing it", P, "    canopy_free(instance->states);\n    canopy_free(instance->arena_block);", "    canopy_free(instance->states);\n    (void)*(volatile char *)instance->states;\n    canopy_free(instance->arena_block);"),
]
