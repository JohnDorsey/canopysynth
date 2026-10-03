/* Installing a compiled graph (compile-and-swap, design section 8), and freeing what is no longer used. Everything here runs with the engine's
   lock held exclusively.

   Installing is a transaction. First everything that can fail because memory runs out is done, without changing anything an instance or a
   query can see: the records of new nodes (knob slots, shared resources), the generation numbers of changed settings, the lists of sources
   upstream of each node, and a package for every live instance (canopy_package_build). If any of that fails, all of it is undone and the engine is
   as it was. Then, with nothing left that can fail, the new knob positions are written, the packages are queued and the graph is published. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "canopy_core.h"

/* ---- records ---- */

static int record_order(int64_t id, const CanopyNodeType *type, const CanopyNodeRecord *record)
{
    if (id != record->id) return id < record->id ? -1 : 1;
    if (type != record->type) return (uintptr_t)type < (uintptr_t)record->type ? -1 : 1;
    return 0;
}

/* The position of the record of this node ID and type in the sorted array, or where it would go. */
static int32_t record_position(const CanopyEngine *engine, int64_t id, const CanopyNodeType *type, int *found)
{
    int32_t lo = 0, hi = engine->n_records;
    while (lo < hi) {
        int32_t mid = lo + (hi - lo) / 2;
        if (record_order(id, type, engine->records[mid]) > 0) lo = mid + 1; else hi = mid;
    }
    *found = lo < engine->n_records && record_order(id, type, engine->records[lo]) == 0;
    return lo;
}

static void record_free(CanopyNodeRecord *record)
{
    canopy_pool_free(&record->pool);
    canopy_free(record);
}

/* The record of this node, made if there is none yet (NULL if memory ran out): knob slots that start at the position the description asks for. */
static CanopyNodeRecord *record_for(CanopyEngine *engine, const CanopyCNode *node)
{
    int found;
    int32_t position = record_position(engine, node->id, node->type, &found), j;
    CanopyNodeRecord *record;
    if (found) return engine->records[position];
    record = (CanopyNodeRecord *)canopy_alloc(sizeof *record);
    if (!record) return NULL;
    record->uid = ++engine->uid;
    record->engine = engine;
    record->id = node->id;
    record->type = node->type;
    record->fresh = 1;
    record->knobs = (CanopySlot **)canopy_pool_alloc(&record->pool, (size_t)node->type->n_inlets * sizeof(CanopySlot *));
    record->setting_gen = (uint64_t *)canopy_pool_alloc(&record->pool, (size_t)node->type->n_settings * sizeof(uint64_t));
    if (!record->knobs || !record->setting_gen) goto fail;
    for (j = 0; j < node->type->n_inlets; j++) {
        record->knobs[j] = (CanopySlot *)canopy_pool_alloc(&record->pool, sizeof(CanopySlot));
        if (!record->knobs[j]) goto fail;
        canopy_slot_set(record->knobs[j], node->knob_start[j]);
    }
    if (engine->n_records == engine->cap_records) {
        int32_t capacity = engine->cap_records ? engine->cap_records * 2 : 16;
        CanopyNodeRecord **grown = (CanopyNodeRecord **)canopy_realloc(engine->records, (size_t)engine->cap_records * sizeof *grown,
                                                                        (size_t)capacity * sizeof *grown);
        if (!grown) goto fail;
        engine->records = grown;
        engine->cap_records = capacity;
    }
    memmove(&engine->records[position + 1], &engine->records[position], (size_t)(engine->n_records - position) * sizeof *engine->records);
    engine->records[position] = record;
    engine->n_records++;
    return record;
fail:
    record_free(record);
    return NULL;
}

/* Destroys a record: its shared resource (with `node`, a node of a graph that is still there, as the context) and its slots. */
static void record_destroy(CanopyEngine *engine, CanopyNodeRecord *record, const CanopyCNode *node)
{
    int found;
    int32_t position = record_position(engine, record->id, record->type, &found);
    if (record->shared && record->type->handlers.destroy_shared) {
        struct CanopyCtx ctx;
        canopy_ctx_setup(&ctx, node, 0, NULL);
        record->type->handlers.destroy_shared(&ctx, record->shared);
    }
    if (found) {
        memmove(&engine->records[position], &engine->records[position + 1], (size_t)(engine->n_records - position - 1) * sizeof *engine->records);
        engine->n_records--;
    }
    record_free(record);
}

/* ---- the sources upstream of each node (design section 7) ---- */

static uint64_t hash_text(const char *text)
{
    uint64_t h = 0xCBF29CE484222325ULL;
    for (; *text; text++) h = (h ^ (unsigned char)*text) * 0x100000001B3ULL;
    return h;
}

/* Walks everything upstream of node x (itself included) once, loops included, using `mark` and `stack` (n entries each; a node counts as
   visited when its mark equals `token`, so the marks only need clearing once, if every walk has a token of its own).
   Appends the generation counter of every source it passes to `list` (if not NULL) and returns how many there are; folds what it passes
   (identities, wiring, setting generations) into *digest (if not NULL). The sources of a node are the knobs of its unconnected inlets, its
   shared resource and, for a boundary node, its boundary slot. */
static int32_t cone_walk(const CanopyCompiled *c, int32_t x, int32_t token, int32_t *mark, int32_t *stack, atomic_uint_fast64_t **list,
                         uint64_t *digest)
{
    int32_t sp = 0, count = 0, j, s;
    stack[sp++] = x;
    mark[x] = token;
    while (sp > 0) {
        const CanopyCNode *node = &c->nodes[stack[--sp]];
        if (digest) {
            *digest = canopy_mix(*digest, node->record->uid);
            *digest = canopy_mix(*digest, (uint64_t)node->id);
            *digest = canopy_mix(*digest, hash_text(node->type->key));
            for (s = 0; s < node->type->n_settings; s++) *digest = canopy_mix(*digest, node->setting_gen[s]);
        }
        for (j = 0; j < node->type->n_inlets; j++) {
            const CanopyLink link = node->links[j];
            if (digest) *digest = canopy_mix(*digest, link.node < 0 ? 0xFFFFFFFFULL : (uint64_t)c->nodes[link.node].id * 64u + (uint64_t)link.outlet);
            if (link.node < 0) {
                if (list) list[count] = &node->knobs[j]->generation;
                count++;
            } else if (mark[link.node] != token) {
                mark[link.node] = token;
                stack[sp++] = link.node;
            }
        }
        if (list) list[count] = &node->record->shared_generation;
        count++;
        if (node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT) {
            if (list) list[count] = &node->record->boundary.generation;
            count++;
        }
    }
    return count;
}

static int setting_differs(int32_t kind, const CanopySettingValue *a, const CanopySettingValue *b)
{
    switch (kind) {
    case CANOPY_SETTING_FLOAT: return memcmp(&a->f, &b->f, sizeof a->f) != 0;
    case CANOPY_SETTING_STRING:
    case CANOPY_SETTING_PATH: return strcmp(a->s, b->s) != 0;
    default: return a->i != b->i;                                         /* INT, and the index of a CHOICE */
    }
}

/* ---- freeing graphs ---- */

void canopy_free_graph(CanopyEngine *engine, CanopyCompiled *compiled)
{
    int32_t i;
    for (i = 0; i < compiled->n_nodes; i++) {
        CanopyNodeRecord *record = compiled->nodes[i].record;
        if (record && --record->refs == 0) record_destroy(engine, record, &compiled->nodes[i]);
    }
    canopy_compiled_release(compiled);
}

void canopy_reclaim(CanopyEngine *engine)
{
    const CanopyCompiled *current = atomic_load_explicit(&engine->current, memory_order_acquire);
    uint64_t floor = current ? current->serial : UINT64_MAX;
    int32_t k;
    for (k = 0; k < engine->n_instances; k++) {
        uint64_t oldest;
        canopy_instance_reap(engine->instances[k]);
        oldest = canopy_instance_oldest_serial(engine->instances[k]);
        if (oldest < floor) floor = oldest;
    }
    while (engine->n_compiled > 0 && engine->compiled[0]->serial < floor && engine->compiled[0] != current) {
        CanopyCompiled *oldest = engine->compiled[0];
        memmove(&engine->compiled[0], &engine->compiled[1], (size_t)(engine->n_compiled - 1) * sizeof *engine->compiled);
        engine->n_compiled--;
        canopy_free_graph(engine, oldest);
    }
    canopy_retire_collect(engine);
}

/* ---- installing ---- */

int32_t canopy_install(CanopyEngine *engine, CanopyCompiled *compiled)
{
    CanopyPackage **built = NULL;
    int32_t *mark = NULL, *stack = NULL;
    int32_t n = compiled->n_nodes, n_built = 0, i, j, s;

    compiled->serial = ++engine->serial;
    if (engine->n_compiled == engine->cap_compiled) {
        int32_t capacity = engine->cap_compiled ? engine->cap_compiled * 2 : 8;
        CanopyCompiled **grown = (CanopyCompiled **)canopy_realloc(engine->compiled, (size_t)engine->cap_compiled * sizeof *grown,
                                                                   (size_t)capacity * sizeof *grown);
        if (!grown) {
            canopy_compiled_release(compiled);
            return CANOPY_ERR_MEMORY;
        }
        engine->compiled = grown;
        engine->cap_compiled = capacity;
    }
    engine->compiled[engine->n_compiled++] = compiled;

    /* 1. the record of every node, bound to the node; the shared resource of a node that has none yet */
    for (i = 0; i < n; i++) {
        CanopyCNode *node = &compiled->nodes[i];
        CanopyNodeRecord *record = record_for(engine, node);
        if (!record) goto fail;
        node->record = record;
        for (j = 0; j < node->type->n_inlets; j++) node->knobs[j] = record->knobs[j];
        if (!record->shared_made) {
            record->shared_made = 1;
            if (node->type->handlers.create_shared) {
                struct CanopyCtx ctx;
                canopy_ctx_setup(&ctx, node, i, NULL);
                record->shared = node->type->handlers.create_shared(&ctx);
            }
        }
        node->shared = record->shared;
    }

    /* 2. the generation number of every setting in this graph: the record's, plus one where the value differs from the installed graph's */
    for (i = 0; i < n; i++) {
        CanopyCNode *node = &compiled->nodes[i];
        const CanopyNodeRecord *record = node->record;
        for (s = 0; s < node->type->n_settings; s++) {
            int changed = record->published && setting_differs(node->type->settings[s].kind, &record->published->settings[s], &node->settings[s]);
            node->setting_gen[s] = record->setting_gen[s] + (changed ? 1u : 0u);
        }
    }

    /* 3. what is upstream of each node: the list of generation counters, and a digest of the rest */
    mark = (int32_t *)canopy_alloc((size_t)n * sizeof *mark);                  /* zeroed: no walk uses the token 0 */
    stack = (int32_t *)canopy_alloc((size_t)n * sizeof *stack);
    if (!mark || !stack) goto fail;
    for (i = 0; i < n; i++) {
        CanopyCNode *node = &compiled->nodes[i];
        int32_t count = cone_walk(compiled, i, 2 * i + 1, mark, stack, NULL, NULL);
        uint64_t digest = 0x6A09E667F3BCC908ULL;
        node->cone_gens = (atomic_uint_fast64_t **)canopy_pool_alloc(&compiled->pool, (size_t)count * sizeof *node->cone_gens);
        if (!node->cone_gens) goto fail;
        node->n_cone_gens = count;
        (void)cone_walk(compiled, i, 2 * i + 2, mark, stack, node->cone_gens, &digest);
        node->cone_static = digest;
    }

    /* 4. a package for every live instance */
    if (engine->n_instances > 0) {
        built = (CanopyPackage **)canopy_alloc((size_t)engine->n_instances * sizeof *built);
        if (!built) goto fail;
        for (n_built = 0; n_built < engine->n_instances; n_built++) {
            built[n_built] = canopy_package_build(engine, engine->instances[n_built], compiled);
            if (!built[n_built]) goto fail;
        }
    }

    /* nothing can fail from here */
    for (i = 0; i < n; i++) {
        CanopyCNode *node = &compiled->nodes[i];
        CanopyNodeRecord *record = node->record;
        for (s = 0; s < node->type->n_settings; s++) record->setting_gen[s] = node->setting_gen[s];
        for (j = 0; j < node->type->n_inlets; j++)                 /* the description's knob positions replace the slots' values, where they differ */
            if (canopy_float_bits(canopy_slot_load(node->knobs[j])) != canopy_float_bits(node->knob_start[j]))
                canopy_slot_write(node->knobs[j], node->knob_start[j]);
        record->published = node;
        record->refs++;
        record->fresh = 0;
    }
    for (i = 0; i < engine->n_instances; i++)
        if (built) canopy_package_enqueue(engine->instances[i], built[i]);
    atomic_store_explicit(&engine->current, compiled, memory_order_release);
    canopy_free(built);
    canopy_free(mark);
    canopy_free(stack);
    return CANOPY_OK;

fail:
    /* undo: the packages built so far, the records and resources made for this graph, the graph itself */
    for (i = 0; i < n_built; i++) canopy_package_discard(built[i]);
    engine->n_compiled--;                                          /* (the graph is the last one in the list) */
    for (i = engine->n_records - 1; i >= 0; i--) {
        CanopyNodeRecord *record = engine->records[i];
        if (record->fresh) {
            const CanopyCNode *node = canopy_compiled_find(compiled, record->id, NULL);
            record_destroy(engine, record, node);
        }
    }
    canopy_compiled_release(compiled);
    canopy_free(built);
    canopy_free(mark);
    canopy_free(stack);
    return CANOPY_ERR_MEMORY;
}
