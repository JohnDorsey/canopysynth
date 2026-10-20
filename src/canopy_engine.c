/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The engine: compiling a graph description into an immutable compiled graph, installing it, and the things that outlive one compiled graph
   (the knob slots and the shared resources, kept per node ID). Instances and queries are in canopy_instance.c. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "canopy_core.h"

#define LL(x) ((long long)(x))
#define GRAPH_ERROR(engine, ...) (snprintf((engine)->error, sizeof (engine)->error, __VA_ARGS__), CANOPY_ERR_GRAPH)

static int32_t memory_error(CanopyEngine *engine)
{
    snprintf(engine->error, sizeof engine->error, "out of memory");
    return CANOPY_ERR_MEMORY;
}

void canopy_compiled_release(CanopyCompiled *compiled)
{
    if (!compiled) return;
    canopy_pool_free(&compiled->pool);
    canopy_free(compiled);
}

const CanopyCNode *canopy_compiled_find(const CanopyCompiled *graph, int64_t id, int32_t *index)
{
    int32_t lo = 0, hi = graph->n_nodes - 1;
    while (lo <= hi) {
        int32_t mid = lo + (hi - lo) / 2;
        int64_t found = graph->nodes[mid].id;
        if (found == id) {
            if (index) *index = mid;
            return &graph->nodes[mid];
        }
        if (found < id) lo = mid + 1; else hi = mid - 1;
    }
    return NULL;
}

/* ---- looking things up by key in a node type ---- */

static int32_t find_inlet(const CanopyNodeType *type, const char *key)
{
    int32_t i;
    for (i = 0; i < type->n_inlets; i++)
        if (strcmp(type->inlets[i].key, key) == 0) return i;
    return -1;
}

static int32_t find_outlet(const CanopyNodeType *type, const char *key)
{
    int32_t i;
    for (i = 0; i < type->n_outlets; i++)
        if (strcmp(type->outlets[i].key, key) == 0) return i;
    return -1;
}

static int32_t find_setting(const CanopyNodeType *type, const char *key)
{
    int32_t i;
    for (i = 0; i < type->n_settings; i++)
        if (strcmp(type->settings[i].key, key) == 0) return i;
    return -1;
}

static const char *setting_kind_name(int32_t kind)
{
    switch (kind) {
    case CANOPY_SETTING_INT: return "an integer";
    case CANOPY_SETTING_FLOAT: return "a float";
    case CANOPY_SETTING_STRING: return "a string";
    case CANOPY_SETTING_PATH: return "a path";
    case CANOPY_SETTING_CHOICE: return "a choice";
    default: return "an unknown kind of";
    }
}

static const char *call_kind_name(CanopyValueKind kind)
{
    return kind == CANOPY_VALUE_INT ? "an integer" : kind == CANOPY_VALUE_FLOAT ? "a float" : "a string";
}

/* ---- compiling ---- */

typedef struct {
    int64_t id;
    int32_t source;                    /* the position in the description */
} SortKey;

static int compare_keys(const void *a, const void *b)
{
    const SortKey *x = (const SortKey *)a, *y = (const SortKey *)b;
    if (x->id != y->id) return x->id < y->id ? -1 : 1;
    return (x->source > y->source) - (x->source < y->source);
}

/* The nodes, sorted by ID, with their types resolved and every setting and knob at its default. */
static int32_t build_nodes(CanopyEngine *engine, const CanopyGraph *graph, CanopyCompiled *c)
{
    int32_t n = graph->n_nodes, i, j, status = CANOPY_OK;
    SortKey *keys = (SortKey *)canopy_alloc((size_t)n * sizeof *keys);
    c->nodes = (CanopyCNode *)canopy_pool_alloc(&c->pool, (size_t)n * sizeof(CanopyCNode));
    if (!keys || !c->nodes) {
        status = memory_error(engine);
        goto done;
    }
    for (i = 0; i < n; i++) {
        keys[i].id = graph->nodes[i].id;
        keys[i].source = i;
    }
    qsort(keys, (size_t)n, sizeof *keys, compare_keys);
    for (i = 1; i < n; i++)
        if (keys[i].id == keys[i - 1].id) {
            status = GRAPH_ERROR(engine, "node %lld is added more than once", LL(keys[i].id));
            goto done;
        }
    c->n_nodes = n;
    for (i = 0; i < n; i++) {
        const CanopyGraphNode *source = &graph->nodes[keys[i].source];
        const CanopyNodeType *type = canopy_registry_find(engine->registry, source->type_key);
        CanopyCNode *node = &c->nodes[i];
        if (!type) {
            status = GRAPH_ERROR(engine, "node %lld uses the unknown node type \"%s\"", LL(source->id), source->type_key);
            goto done;
        }
        node->id = source->id;
        node->type = type;
        node->links = (CanopyLink *)canopy_pool_alloc(&c->pool, (size_t)type->n_inlets * sizeof(CanopyLink));
        node->knobs = (CanopySlot **)canopy_pool_alloc(&c->pool, (size_t)type->n_inlets * sizeof(CanopySlot *));
        node->knob_start = (float *)canopy_pool_alloc(&c->pool, (size_t)type->n_inlets * sizeof(float));
        node->settings = (CanopySettingValue *)canopy_pool_alloc(&c->pool, (size_t)type->n_settings * sizeof(CanopySettingValue));
        node->setting_gen = (uint64_t *)canopy_pool_alloc(&c->pool, (size_t)type->n_settings * sizeof(uint64_t));
        if (!node->links || !node->knobs || !node->knob_start || !node->settings || !node->setting_gen) {
            status = memory_error(engine);
            goto done;
        }
        for (j = 0; j < type->n_inlets; j++) {
            node->links[j].node = -1;
            node->links[j].outlet = -1;
            node->knob_start[j] = type->inlets[j].default_knob;
        }
        for (j = 0; j < type->n_settings; j++) {
            const CanopySettingDesc *desc = &type->settings[j];
            CanopySettingValue *value = &node->settings[j];
            if (desc->kind == CANOPY_SETTING_FLOAT) {
                value->f = desc->default_float;
            } else if (desc->kind == CANOPY_SETTING_STRING || desc->kind == CANOPY_SETTING_PATH) {
                value->s = canopy_pool_strdup(&c->pool, desc->default_string ? desc->default_string : "");
                if (!value->s) {
                    status = memory_error(engine);
                    goto done;
                }
            } else {
                value->i = desc->default_int;                         /* INT, and the index of a CHOICE */
            }
        }
    }
done:
    canopy_free(keys);
    return status;
}

static int32_t apply_settings(CanopyEngine *engine, const CanopyGraph *graph, CanopyCompiled *c)
{
    int32_t k;
    for (k = 0; k < graph->n_settings; k++) {
        const CanopyGraphSetting *given = &graph->settings[k];
        int32_t node_index, index;
        CanopyCNode *node;
        const CanopySettingDesc *desc;
        CanopySettingValue *value;
        int allowed;
        if (!canopy_compiled_find(c, given->node, &node_index))
            return GRAPH_ERROR(engine, "there is no node %lld for the setting \"%s\"", LL(given->node), given->key);
        node = &c->nodes[node_index];
        index = find_setting(node->type, given->key);
        if (index < 0)
            return GRAPH_ERROR(engine, "node %lld (%s) has no setting \"%s\"", LL(node->id), node->type->key, given->key);
        desc = &node->type->settings[index];
        value = &node->settings[index];
        allowed = (given->kind == CANOPY_VALUE_INT && (desc->kind == CANOPY_SETTING_INT || desc->kind == CANOPY_SETTING_CHOICE)) ||
                  (given->kind == CANOPY_VALUE_FLOAT && desc->kind == CANOPY_SETTING_FLOAT) ||
                  (given->kind == CANOPY_VALUE_STRING && (desc->kind == CANOPY_SETTING_STRING || desc->kind == CANOPY_SETTING_PATH));
        if (!allowed)
            return GRAPH_ERROR(engine, "node %lld (%s): the setting \"%s\" is %s setting and cannot be set with %s", LL(node->id),
                               node->type->key, given->key, setting_kind_name(desc->kind), call_kind_name(given->kind));
        switch (desc->kind) {
        case CANOPY_SETTING_CHOICE:
            if (given->i < 0 || given->i >= desc->n_choices)
                return GRAPH_ERROR(engine, "node %lld (%s): the setting \"%s\" is a choice and its index must be from 0 to %d, not %lld",
                                   LL(node->id), node->type->key, given->key, (int)desc->n_choices - 1, LL(given->i));
            value->i = given->i;
            break;
        case CANOPY_SETTING_INT:
            if (strcmp(desc->key, CANOPY_INTERNAL_RATE_KEY) == 0 && (given->i < CANOPY_INTERNAL_RATE_MIN || given->i > CANOPY_INTERNAL_RATE_MAX))
                return GRAPH_ERROR(engine, "node %lld (%s): the setting \"%s\" must be a whole number of Hz from %d to %d, not %lld",
                                   LL(node->id), node->type->key, given->key, CANOPY_INTERNAL_RATE_MIN, CANOPY_INTERNAL_RATE_MAX,
                                   LL(given->i));
            value->i = given->i;
            break;
        case CANOPY_SETTING_FLOAT:
            if (!isfinite(given->f))
                return GRAPH_ERROR(engine, "node %lld (%s): the setting \"%s\" must be a finite number", LL(node->id), node->type->key,
                                   given->key);
            value->f = given->f;
            break;
        default:                                                       /* STRING and PATH */
            value->s = canopy_pool_strdup(&c->pool, given->s);
            if (!value->s) return memory_error(engine);
            break;
        }
    }
    return CANOPY_OK;
}

static int32_t apply_knobs(CanopyEngine *engine, const CanopyGraph *graph, CanopyCompiled *c)
{
    int32_t k;
    for (k = 0; k < graph->n_knobs; k++) {
        const CanopyGraphKnob *given = &graph->knobs[k];
        int32_t node_index, inlet;
        CanopyCNode *node;
        if (!canopy_compiled_find(c, given->node, &node_index))
            return GRAPH_ERROR(engine, "there is no node %lld for the knob of inlet \"%s\"", LL(given->node), given->key);
        node = &c->nodes[node_index];
        inlet = find_inlet(node->type, given->key);
        if (inlet < 0) return GRAPH_ERROR(engine, "node %lld (%s) has no inlet \"%s\"", LL(node->id), node->type->key, given->key);
        if (!(given->value >= -1.0f && given->value <= 1.0f))
            return GRAPH_ERROR(engine, "node %lld (%s): the knob of inlet \"%s\" must be a number from -1 to 1", LL(node->id),
                               node->type->key, given->key);
        node->knob_start[inlet] = given->value;
    }
    return CANOPY_OK;
}

static int32_t apply_connections(CanopyEngine *engine, const CanopyGraph *graph, CanopyCompiled *c)
{
    int32_t k;
    for (k = 0; k < graph->n_connections; k++) {
        const CanopyGraphConnection *given = &graph->connections[k];
        int32_t from_index, to_index, outlet, inlet;
        const CanopyCNode *from;
        CanopyCNode *to;
        if (!canopy_compiled_find(c, given->from_node, &from_index))
            return GRAPH_ERROR(engine, "the connection from node %lld \"%s\": there is no node %lld", LL(given->from_node), given->outlet_key,
                               LL(given->from_node));
        if (!canopy_compiled_find(c, given->to_node, &to_index))
            return GRAPH_ERROR(engine, "the connection to node %lld \"%s\": there is no node %lld", LL(given->to_node), given->inlet_key,
                               LL(given->to_node));
        from = &c->nodes[from_index];
        to = &c->nodes[to_index];
        outlet = find_outlet(from->type, given->outlet_key);
        if (outlet < 0)
            return GRAPH_ERROR(engine, "node %lld (%s) has no outlet \"%s\"", LL(from->id), from->type->key, given->outlet_key);
        inlet = find_inlet(to->type, given->inlet_key);
        if (inlet < 0) return GRAPH_ERROR(engine, "node %lld (%s) has no inlet \"%s\"", LL(to->id), to->type->key, given->inlet_key);
        if (to->links[inlet].node >= 0)
            return GRAPH_ERROR(engine, "node %lld (%s): inlet \"%s\" is already connected (to node %lld)", LL(to->id), to->type->key,
                               given->inlet_key, LL(c->nodes[to->links[inlet].node].id));
        to->links[inlet].node = from_index;
        to->links[inlet].outlet = outlet;
    }
    return CANOPY_OK;
}

int32_t canopy_arena_floats(int64_t buffers, int64_t *floats)
{
    /* the size in bytes (4 per float) must fit a signed 64-bit integer too, with a buffer to spare for alignment */
    if (buffers < 0 || buffers > INT64_MAX / ((int64_t)CANOPY_MAX_N * (int64_t)sizeof(float)) - 1) return CANOPY_ERR_OVERFLOW;
    *floats = buffers * CANOPY_MAX_N;
    return CANOPY_OK;
}

/* The scratch arena of one instance (design section 8): the most scratch buffers held at once by a chain of queries, times the largest n.
   A node holds its declared buffers while it queries upstream, so the weight of a node is its own count plus the heaviest of the nodes
   feeding it; the arena fits the heaviest node. The weights are found in dependency order (Kahn's algorithm, no recursion). With a loop
   anywhere the order does not exist, and the arena is sized for every node holding its buffers at once. */
static int32_t compute_arena(CanopyEngine *engine, CanopyCompiled *c)
{
    CanopyPool temp;
    int32_t n = c->n_nodes, i, j, head = 0, tail = 0, edge_count = 0, status = CANOPY_OK;
    int32_t *first, *fill, *edges, *indegree, *queue;
    int64_t *weight;
    int64_t total = 0, best = 0, buffers;
    memset(&temp, 0, sizeof temp);
    for (i = 0; i < n; i++)
        for (j = 0; j < c->nodes[i].type->n_inlets; j++)
            if (c->nodes[i].links[j].node >= 0) edge_count++;
    first = (int32_t *)canopy_pool_alloc(&temp, (size_t)(n + 1) * sizeof *first);
    fill = (int32_t *)canopy_pool_alloc(&temp, (size_t)(n + 1) * sizeof *fill);
    edges = (int32_t *)canopy_pool_alloc(&temp, (size_t)edge_count * sizeof *edges);
    indegree = (int32_t *)canopy_pool_alloc(&temp, (size_t)n * sizeof *indegree);
    queue = (int32_t *)canopy_pool_alloc(&temp, (size_t)n * sizeof *queue);
    weight = (int64_t *)canopy_pool_alloc(&temp, (size_t)n * sizeof *weight);
    if (!first || !fill || !edges || !indegree || !queue || !weight) {
        status = memory_error(engine);
        goto done;
    }
    for (i = 0; i < n; i++)
        for (j = 0; j < c->nodes[i].type->n_inlets; j++)
            if (c->nodes[i].links[j].node >= 0) first[c->nodes[i].links[j].node + 1]++;      /* how many inlets each node feeds */
    for (i = 0; i < n; i++) first[i + 1] += first[i];
    memcpy(fill, first, (size_t)(n + 1) * sizeof *fill);
    for (i = 0; i < n; i++)
        for (j = 0; j < c->nodes[i].type->n_inlets; j++) {
            int32_t source = c->nodes[i].links[j].node;
            if (source >= 0) {
                edges[fill[source]++] = i;                                                   /* source feeds node i */
                indegree[i]++;
            }
        }
    for (i = 0; i < n; i++)
        if (indegree[i] == 0) queue[tail++] = i;
    while (head < tail) {
        int32_t x = queue[head++], e;
        int64_t heaviest = 0;
        for (j = 0; j < c->nodes[x].type->n_inlets; j++) {
            int32_t source = c->nodes[x].links[j].node;
            if (source >= 0 && weight[source] > heaviest) heaviest = weight[source];
        }
        weight[x] = c->nodes[x].type->scratch_buffers + heaviest;
        if (weight[x] > best) best = weight[x];
        for (e = first[x]; e < first[x + 1]; e++)
            if (--indegree[edges[e]] == 0) queue[tail++] = edges[e];
    }
    for (i = 0; i < n; i++) total += c->nodes[i].type->scratch_buffers;
    c->has_cycle = tail < n;
    buffers = c->has_cycle ? total : best;
    if (canopy_arena_floats(buffers, &c->arena_floats) != CANOPY_OK) {
        status = GRAPH_ERROR(engine, "the scratch buffers the nodes declare along their longest chain are too many (%lld)", LL(buffers));
        goto done;
    }
done:
    canopy_pool_free(&temp);
    return status;
}

static int compare_boundary(const void *a, const void *b)
{
    return strcmp(((const CanopyBoundary *)a)->name, ((const CanopyBoundary *)b)->name);
}

/* The boundary nodes sorted by name; a name that is empty, or used by two nodes of either kind, is a fault. */
static int32_t build_boundary(CanopyEngine *engine, CanopyCompiled *c)
{
    int32_t i, count = 0, k = 0;
    for (i = 0; i < c->n_nodes; i++)
        if (c->nodes[i].type->flags & CANOPY_FLAG_BOUNDARY_NODE) count++;
    if (count == 0) return CANOPY_OK;
    c->boundary = (CanopyBoundary *)canopy_pool_alloc(&c->pool, (size_t)count * sizeof *c->boundary);
    if (!c->boundary) return memory_error(engine);
    for (i = 0; i < c->n_nodes; i++) {
        const CanopyCNode *node = &c->nodes[i];
        if (node->type->flags & CANOPY_FLAG_BOUNDARY_NODE) {
            int32_t setting = find_setting(node->type, CANOPY_BOUNDARY_NAME_KEY);       /* (the registry made sure there is one) */
            const char *name = node->settings[setting].s;
            if (name[0] == '\0')
                return GRAPH_ERROR(engine, "node %lld (%s) is a boundary node and needs a name", LL(node->id), node->type->key);
            c->boundary[k].name = name;
            c->boundary[k].node = i;
            c->boundary[k].kind = (node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT) ? CANOPY_BOUNDARY_INLET : CANOPY_BOUNDARY_OUTLET;
            k++;
        }
    }
    c->n_boundary = count;
    qsort(c->boundary, (size_t)count, sizeof *c->boundary, compare_boundary);
    for (i = 1; i < count; i++)
        if (strcmp(c->boundary[i].name, c->boundary[i - 1].name) == 0) {
            int32_t first = c->boundary[i - 1].node < c->boundary[i].node ? c->boundary[i - 1].node : c->boundary[i].node;
            int32_t second = c->boundary[i - 1].node < c->boundary[i].node ? c->boundary[i].node : c->boundary[i - 1].node;
            return GRAPH_ERROR(engine, "the boundary name \"%s\" is used by node %lld and by node %lld; boundary names must be unique",
                               c->boundary[i].name, LL(c->nodes[first].id), LL(c->nodes[second].id));
        }
    return CANOPY_OK;
}

const CanopyBoundary *canopy_compiled_find_boundary(const CanopyCompiled *graph, const char *name)
{
    int32_t lo = 0, hi = graph->n_boundary - 1;
    while (lo <= hi) {
        int32_t mid = lo + (hi - lo) / 2;
        int order = strcmp(graph->boundary[mid].name, name);
        if (order == 0) return &graph->boundary[mid];
        if (order < 0) lo = mid + 1; else hi = mid - 1;
    }
    return NULL;
}

static int32_t compile(CanopyEngine *engine, const CanopyGraph *graph, CanopyCompiled **result)
{
    int32_t status;
    CanopyCompiled *c = (CanopyCompiled *)canopy_alloc(sizeof *c);
    if (!c) return memory_error(engine);
    status = build_nodes(engine, graph, c);
    if (status == CANOPY_OK) status = apply_settings(engine, graph, c);
    if (status == CANOPY_OK) status = apply_knobs(engine, graph, c);
    if (status == CANOPY_OK) status = apply_connections(engine, graph, c);
    if (status == CANOPY_OK) status = build_boundary(engine, c);
    if (status == CANOPY_OK) status = compute_arena(engine, c);
    if (status != CANOPY_OK) {
        canopy_compiled_release(c);
        return status;
    }
    *result = c;
    return CANOPY_OK;
}

/* ---- the engine ---- */

CanopyEngine *canopy_engine_new(const CanopyRegistry *registry)
{
    CanopyEngine *engine;
    if (!registry) return NULL;
    engine = (CanopyEngine *)canopy_alloc(sizeof *engine);
    if (!engine) return NULL;
    engine->registry = registry;
    InitializeSRWLock(&engine->lock);
    InitializeSRWLock(&engine->retire_lock);
    InitializeSRWLock(&engine->message_lock);
    return engine;
}

int32_t canopy_engine_free(CanopyEngine *engine)
{
    if (!engine) return CANOPY_OK;
    canopy_lock_exclusive(&engine->lock);
    if (engine->n_instances - engine->n_service != 0) {            /* (the instances the engine made for its own nodes do not hold it) */
        canopy_unlock_exclusive(&engine->lock);
        return CANOPY_ERR_BUSY;
    }
    canopy_services_stop(engine);                                  /* nodes with a thread of their own stop first, while every graph they may refer to is still there */
    atomic_store_explicit(&engine->current, NULL, memory_order_release);
    while (engine->n_compiled > 0) {                 /* oldest first; the last one to go takes the last records, and their shared resources */
        CanopyCompiled *oldest = engine->compiled[0];
        memmove(&engine->compiled[0], &engine->compiled[1], (size_t)(engine->n_compiled - 1) * sizeof *engine->compiled);
        engine->n_compiled--;
        canopy_free_graph(engine, oldest);
    }
    canopy_free(engine->compiled);
    canopy_free(engine->records);
    canopy_free(engine->instances);
    canopy_unlock_exclusive(&engine->lock);
    canopy_free(engine);
    return CANOPY_OK;
}

int32_t canopy_engine_set_graph(CanopyEngine *engine, const CanopyGraph *graph)
{
    CanopyCompiled *compiled = NULL;
    int32_t status;
    if (!engine || !graph) return CANOPY_ERR_ARGUMENT;
    engine->error[0] = '\0';
    status = compile(engine, graph, &compiled);
    if (status != CANOPY_OK) return status;
    canopy_lock_exclusive(&engine->lock);
    status = canopy_install(engine, compiled);
    if (status == CANOPY_OK) canopy_reclaim(engine);
    else memory_error(engine);
    canopy_unlock_exclusive(&engine->lock);
    return status;
}

int32_t canopy_engine_collect(CanopyEngine *engine)
{
    int32_t held;
    if (!engine) return 0;
    canopy_lock_exclusive(&engine->lock);
    canopy_reclaim(engine);
    held = engine->n_compiled;
    canopy_unlock_exclusive(&engine->lock);
    return held;
}

const char *canopy_engine_last_error(const CanopyEngine *engine)
{
    return engine ? engine->error : "";
}

int32_t canopy_engine_node_count(CanopyEngine *engine)
{
    const CanopyCompiled *graph;
    int32_t count;
    if (!engine) return 0;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    count = graph ? graph->n_nodes : 0;
    canopy_unlock_shared(&engine->lock);
    return count;
}

int64_t canopy_engine_graph_serial(CanopyEngine *engine)
{
    const CanopyCompiled *graph;
    int64_t serial;
    if (!engine) return 0;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    serial = graph ? (int64_t)graph->serial : 0;
    canopy_unlock_shared(&engine->lock);
    return serial;
}

/* The slot of an inlet's knob in the installed graph, or the status for why there is none. The shared lock must be held: it keeps the graph
   and its records from being freed while the slot is used. */
static int32_t find_knob(CanopyEngine *engine, int64_t node_id, int32_t inlet, CanopySlot **slot)
{
    const CanopyCompiled *graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    const CanopyCNode *node = graph ? canopy_compiled_find(graph, node_id, NULL) : NULL;
    if (!node) return CANOPY_ERR_NODE;
    if (inlet < 0 || inlet >= node->type->n_inlets) return CANOPY_ERR_PORT;
    *slot = node->knobs[inlet];
    return CANOPY_OK;
}

int32_t canopy_engine_set_knob(CanopyEngine *engine, int64_t node_id, int32_t inlet, float value)
{
    CanopySlot *slot = NULL;
    int32_t status;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    if (!(value >= -1.0f && value <= 1.0f)) return CANOPY_ERR_ARGUMENT;        /* false for NaN too */
    canopy_lock_shared(&engine->lock);
    status = find_knob(engine, node_id, inlet, &slot);
    if (status == CANOPY_OK) canopy_slot_write(slot, value);
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_engine_get_knob(CanopyEngine *engine, int64_t node_id, int32_t inlet, float *value, uint64_t *generation)
{
    CanopySlot *slot = NULL;
    int32_t status;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_knob(engine, node_id, inlet, &slot);
    if (status == CANOPY_OK) {
        if (generation) *generation = (uint64_t)atomic_load_explicit(&slot->generation, memory_order_acquire);   /* generation first, then value */
        if (value) *value = canopy_slot_load(slot);
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_engine_set_boundary_value(CanopyEngine *engine, int64_t node_id, float value)
{
    const CanopyCompiled *graph;
    const CanopyCNode *node;
    int32_t status = CANOPY_OK;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    node = graph ? canopy_compiled_find(graph, node_id, NULL) : NULL;
    if (!node) status = CANOPY_ERR_NODE;
    else if (!(node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT)) status = CANOPY_ERR_ARGUMENT;
    else canopy_slot_write(&node->record->boundary, value);                  /* any float: nothing is clamped on the way in */
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_engine_set_boundary(CanopyEngine *engine, const char *name, float value)
{
    const CanopyCompiled *graph;
    const CanopyBoundary *entry;
    int32_t status = CANOPY_OK;
    if (!engine || !name) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    entry = graph ? canopy_compiled_find_boundary(graph, name) : NULL;
    if (!entry || entry->kind != CANOPY_BOUNDARY_INLET) status = CANOPY_ERR_NODE;
    else canopy_slot_write(&graph->nodes[entry->node].record->boundary, value);          /* any float: nothing is clamped on the way in */
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_engine_boundary_count(CanopyEngine *engine)
{
    const CanopyCompiled *graph;
    int32_t count;
    if (!engine) return 0;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    count = graph ? graph->n_boundary : 0;
    canopy_unlock_shared(&engine->lock);
    return count;
}

int32_t canopy_engine_boundary_at(CanopyEngine *engine, int32_t index, char *name, int32_t name_capacity, int32_t *name_length,
                                  int32_t *kind, int64_t *node_id)
{
    const CanopyCompiled *graph;
    int32_t status = CANOPY_OK;
    if (!engine || name_capacity < 0 || (name_capacity > 0 && !name)) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    if (!graph || index < 0 || index >= graph->n_boundary) {
        status = CANOPY_ERR_INDEX;
    } else {
        const CanopyBoundary *entry = &graph->boundary[index];
        size_t length = strlen(entry->name);
        if (name_capacity > 0) {
            size_t copied = length < (size_t)name_capacity - 1 ? length : (size_t)name_capacity - 1;
            memcpy(name, entry->name, copied);
            name[copied] = '\0';
        }
        if (name_length) *name_length = (int32_t)length;
        if (kind) *kind = entry->kind;
        if (node_id) *node_id = graph->nodes[entry->node].id;
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}

static void (*action_window_hook)(void);           /* test hook: called while a service node's button has let go of the lock and not yet taken it again */

void canopy_engine_test_action_window(void (*hook)(void))
{
    action_window_hook = hook;
}

int32_t canopy_engine_action(CanopyEngine *engine, int64_t node_id, const char *action)
{
    const CanopyCompiled *graph;
    const CanopyCNode *node;
    int32_t index = 0, status = CANOPY_OK;
    int exclusive = 0;
    if (!engine || !action) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    node = graph ? canopy_compiled_find(graph, node_id, &index) : NULL;
    if (node && (node->type->flags & CANOPY_FLAG_SERVICE)) {      /* the buttons of a node with a thread of its own make and free its instance: exclusive */
        canopy_unlock_shared(&engine->lock);
        if (action_window_hook) action_window_hook();
        canopy_lock_exclusive(&engine->lock);
        exclusive = 1;
        graph = atomic_load_explicit(&engine->current, memory_order_acquire);          /* (it may have changed while the lock was let go) */
        node = graph ? canopy_compiled_find(graph, node_id, &index) : NULL;
    }
    if (!node) {
        status = CANOPY_ERR_NODE;
    } else if (node->type->handlers.on_action) {
        struct CanopyCtx ctx;
        canopy_ctx_setup(&ctx, node, index, NULL);
        node->type->handlers.on_action(&ctx, action);
    }
    if (exclusive) canopy_unlock_exclusive(&engine->lock); else canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_engine_set_audio_backend(CanopyEngine *engine, int32_t backend)
{
    if (!engine || (backend != CANOPY_AUDIO_SYSTEM && backend != CANOPY_AUDIO_NULL)) return CANOPY_ERR_ARGUMENT;
    atomic_store(&engine->audio_backend, backend);
    return CANOPY_OK;
}

int32_t canopy_engine_service_count(CanopyEngine *engine)
{
    int32_t count;
    if (!engine) return -1;
    canopy_lock_shared(&engine->lock);
    count = engine->n_service;
    canopy_unlock_shared(&engine->lock);
    return count;
}
