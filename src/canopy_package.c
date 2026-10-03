/* The lifecycle of instances, and the packages that move a running instance to a newly installed graph (see CanopyPackage in canopy_core.h).
   Everything here except canopy_instance_adopt runs with the engine's lock held, in the thread that installs, collects or frees. */
#include <stdint.h>
#include <string.h>
#include "canopy_core.h"

/* A 64-byte aligned arena of `floats` floats: the block to free, and the start inside it. NULL if it cannot be had. */
static void *arena_block_for(int64_t floats, float **start)
{
    void *block;
    if (floats <= 0) {
        *start = NULL;
        return NULL;
    }
    if ((uint64_t)floats > (SIZE_MAX - 64) / sizeof(float)) return NULL;                    /* cannot be addressed */
    block = canopy_alloc((size_t)floats * sizeof(float) + 64);                              /* 64 spare bytes let it start on a cache line */
    if (block) *start = (float *)(((uintptr_t)block + 63u) & ~(uintptr_t)63u);
    return block;
}

/* ---- packages ---- */

void canopy_package_discard(CanopyPackage *package)
{
    int32_t i;
    if (!package) return;
    if (package->fresh && package->to) {
        for (i = 0; i < package->to->n_nodes; i++) {
            const CanopyHandlers *handlers = &package->to->nodes[i].type->handlers;
            if (package->fresh[i] && handlers->destroy_instance) {
                struct CanopyCtx ctx;
                canopy_ctx_setup(&ctx, &package->to->nodes[i], i, package->fresh[i]);
                handlers->destroy_instance(&ctx, package->fresh[i]);
            }
        }
    }
    canopy_free(package->map);
    canopy_free(package->carried);
    canopy_free(package->fresh);
    canopy_free(package->new_states);
    canopy_free(package->new_arena_block);
    canopy_free(package);
}

CanopyPackage *canopy_package_build(CanopyEngine *engine, CanopyInstance *instance, const CanopyCompiled *to)
{
    const CanopyCompiled *from = instance->planned_graph;
    CanopyPackage *package = (CanopyPackage *)canopy_alloc(sizeof *package);
    int32_t i, j;
    (void)engine;
    if (!package) return NULL;
    package->from = from;
    package->to = to;
    package->map = (int32_t *)canopy_alloc((size_t)to->n_nodes * sizeof(int32_t));
    package->carried = (unsigned char *)canopy_alloc((size_t)from->n_nodes);
    package->fresh = (void **)canopy_alloc((size_t)to->n_nodes * sizeof(void *));
    package->new_states = (void **)canopy_alloc((size_t)to->n_nodes * sizeof(void *));
    if (!package->map || !package->carried || !package->fresh || !package->new_states) goto fail;
    if (to->arena_floats > instance->planned_arena_floats) {                                 /* a bigger arena: made here, not in a query */
        package->new_arena_block = arena_block_for(to->arena_floats, &package->new_arena);
        if (!package->new_arena_block) goto fail;
        package->new_arena_floats = to->arena_floats;
    }
    /* the state of a node is kept when the same node (same ID and type) is in both graphs; both lists are sorted by ID */
    for (i = 0, j = 0; i < to->n_nodes; i++) {
        while (j < from->n_nodes && from->nodes[j].id < to->nodes[i].id) j++;
        if (j < from->n_nodes && from->nodes[j].id == to->nodes[i].id && from->nodes[j].type == to->nodes[i].type) {
            package->map[i] = j;
            package->carried[j] = 1;
        } else {
            package->map[i] = -1;
        }
    }
    for (i = 0; i < to->n_nodes; i++) {                                                      /* state for the nodes that are new */
        const CanopyHandlers *handlers = &to->nodes[i].type->handlers;
        if (package->map[i] < 0 && handlers->create_instance) {
            struct CanopyCtx ctx;
            canopy_ctx_setup(&ctx, &to->nodes[i], i, NULL);
            package->fresh[i] = handlers->create_instance(&ctx);
        }
    }
    return package;
fail:
    canopy_package_discard(package);
    return NULL;
}

void canopy_package_enqueue(CanopyInstance *instance, CanopyPackage *package)
{
    atomic_store_explicit(&instance->tail->next, package, memory_order_release);
    instance->tail = package;
    instance->planned_graph = package->to;
    if (package->new_arena_block) instance->planned_arena_floats = package->new_arena_floats;
}

/* The thread that queries: applies every package that has been queued since it last looked. Pointer swaps only. */
static void apply_package(CanopyInstance *instance, CanopyPackage *package)
{
    int32_t i;
    for (i = 0; i < package->to->n_nodes; i++)
        package->new_states[i] = package->map[i] >= 0 ? instance->states[package->map[i]] : package->fresh[i];
    package->old_states = instance->states;
    instance->states = package->new_states;
    instance->graph = package->to;
    if (package->new_arena_block) {
        package->old_arena_block = instance->arena_block;
        instance->arena_block = package->new_arena_block;
        instance->arena = package->new_arena;
        instance->arena_floats = package->new_arena_floats;
        instance->arena_top = 0;                                                             /* adoption is at the start of a query: nothing is held */
    }
    atomic_store_explicit(&package->done, 1, memory_order_release);                          /* last: from here the installing thread owns the rest */
}

void canopy_instance_adopt(CanopyInstance *instance)
{
    CanopyPackage *next;
    while ((next = atomic_load_explicit(&instance->applied->next, memory_order_acquire)) != NULL) {
        apply_package(instance, next);
        instance->applied = next;
    }
}

/* What an applied package took out of use: the states of nodes that did not make it into the new graph, the old table, the old arena. */
static void dispose_payload(CanopyPackage *package)
{
    int32_t j;
    if (package->payload_disposed) return;
    package->payload_disposed = 1;
    for (j = package->from->n_nodes - 1; j >= 0; j--) {
        const CanopyHandlers *handlers = &package->from->nodes[j].type->handlers;
        if (!package->carried[j] && package->old_states[j] && handlers->destroy_instance) {
            struct CanopyCtx ctx;
            canopy_ctx_setup(&ctx, &package->from->nodes[j], j, package->old_states[j]);
            handlers->destroy_instance(&ctx, package->old_states[j]);
        }
    }
    canopy_free(package->old_states);
    canopy_free(package->old_arena_block);
    canopy_free(package->map);
    canopy_free(package->carried);
    canopy_free(package->fresh);                         /* (the states in it are in new_states now: the instance's table) */
    package->old_states = NULL;
    package->old_arena_block = NULL;
    package->map = NULL;
    package->carried = NULL;
    package->fresh = NULL;
}

void canopy_instance_reap(CanopyInstance *instance)
{
    for (;;) {
        CanopyPackage *next = atomic_load_explicit(&instance->first->next, memory_order_acquire);
        if (!next || !atomic_load_explicit(&next->done, memory_order_acquire)) break;
        dispose_payload(next);
        canopy_free(instance->first);                    /* the instance has moved past it: it only ever reads `applied->next` */
        instance->first = next;
    }
}

uint64_t canopy_instance_oldest_serial(CanopyInstance *instance)
{
    CanopyPackage *next = atomic_load_explicit(&instance->first->next, memory_order_acquire);   /* (after a reap: not applied yet) */
    return next ? next->from->serial : instance->first->to->serial;
}

/* ---- instances ---- */

/* Frees an instance that is no longer in the engine's list: what it runs, what was prepared for it and not applied, the rest. */
static void instance_teardown(CanopyInstance *instance)
{
    int32_t i;
    CanopyPackage *package;
    if (instance->first) {
        canopy_instance_reap(instance);
        package = atomic_load_explicit(&instance->first->next, memory_order_acquire);
        while (package) {                                /* never applied */
            CanopyPackage *following = atomic_load_explicit(&package->next, memory_order_acquire);
            canopy_package_discard(package);
            package = following;
        }
    }
    if (instance->states && instance->graph) {
        for (i = instance->graph->n_nodes - 1; i >= 0; i--) {
            const CanopyHandlers *handlers = &instance->graph->nodes[i].type->handlers;
            if (instance->states[i] && handlers->destroy_instance) {
                struct CanopyCtx ctx;
                canopy_ctx_setup(&ctx, &instance->graph->nodes[i], i, instance->states[i]);
                handlers->destroy_instance(&ctx, instance->states[i]);
            }
        }
    }
    canopy_free(instance->states);
    canopy_free(instance->arena_block);
    canopy_free(instance->first);
    canopy_free(instance);
}

CanopyInstance *canopy_engine_new_instance(CanopyEngine *engine)
{
    const CanopyCompiled *graph;
    CanopyInstance *instance;
    CanopyPackage *sentinel;
    int32_t i;
    if (!engine) return NULL;
    canopy_lock_exclusive(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    if (!graph) goto none;
    instance = (CanopyInstance *)canopy_alloc(sizeof *instance);
    if (!instance) goto none;
    sentinel = (CanopyPackage *)canopy_alloc(sizeof *sentinel);
    if (sentinel) {
        sentinel->from = sentinel->to = graph;
        sentinel->payload_disposed = 1;
        atomic_store(&sentinel->done, 1);
    }
    instance->engine = engine;
    instance->graph = instance->planned_graph = graph;
    instance->first = instance->tail = instance->applied = sentinel;
    instance->states = (void **)canopy_alloc((size_t)graph->n_nodes * sizeof(void *));
    if (graph->arena_floats > 0) {
        instance->arena_block = arena_block_for(graph->arena_floats, &instance->arena);
        instance->arena_floats = graph->arena_floats;
        instance->planned_arena_floats = graph->arena_floats;
        if (!instance->arena_block) instance->arena_floats = instance->planned_arena_floats = 0;
    }
    if (!sentinel || !instance->states || (graph->arena_floats > 0 && !instance->arena_block)) {
        instance_teardown(instance);
        goto none;
    }
    for (i = 0; i < graph->n_nodes; i++) {
        const CanopyHandlers *handlers = &graph->nodes[i].type->handlers;
        if (handlers->create_instance) {
            struct CanopyCtx ctx;
            canopy_ctx_setup(&ctx, &graph->nodes[i], i, NULL);
            instance->states[i] = handlers->create_instance(&ctx);
        }
    }
    if (engine->n_instances == engine->cap_instances) {
        int32_t capacity = engine->cap_instances ? engine->cap_instances * 2 : 8;
        CanopyInstance **grown = (CanopyInstance **)canopy_realloc(engine->instances, (size_t)engine->cap_instances * sizeof *grown,
                                                                    (size_t)capacity * sizeof *grown);
        if (!grown) {
            instance_teardown(instance);
            goto none;
        }
        engine->instances = grown;
        engine->cap_instances = capacity;
    }
    engine->instances[engine->n_instances++] = instance;
    canopy_unlock_exclusive(&engine->lock);
    return instance;
none:
    canopy_unlock_exclusive(&engine->lock);
    return NULL;
}

void canopy_instance_free(CanopyInstance *instance)
{
    CanopyEngine *engine;
    int32_t k;
    if (!instance) return;
    engine = instance->engine;
    canopy_lock_exclusive(&engine->lock);
    for (k = 0; k < engine->n_instances; k++)
        if (engine->instances[k] == instance) {
            engine->instances[k] = engine->instances[--engine->n_instances];
            break;
        }
    canopy_retire_forget(engine, instance);
    instance_teardown(instance);
    canopy_reclaim(engine);                              /* the graphs and shared resources this instance was the last to need */
    canopy_unlock_exclusive(&engine->lock);
}
