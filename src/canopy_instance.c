/* Queries: the point and span queries with their error rules (design section 5), the context handed to node handlers (section 12) and the
   scratch arena (section 8). Nothing in the query path allocates, frees or locks (the lifecycle of instances is in canopy_package.c). */
#include <stdint.h>
#include <string.h>
#include "canopy_core.h"

int64_t canopy_instance_arena_floats(const CanopyInstance *instance)
{
    return instance ? instance->arena_floats : 0;
}

int64_t canopy_instance_graph_serial(const CanopyInstance *instance)
{
    return instance ? (int64_t)instance->graph->serial : 0;
}

/* ---- running a handler ----
   Each call of a handler gets a context of its own on the stack; the arena is emptied back to where it was when the handler returns. */

static void ctx_begin(struct CanopyCtx *ctx, CanopyInstance *instance, int32_t node_index)
{
    ctx->instance = instance;
    ctx->node = &instance->graph->nodes[node_index];
    ctx->node_index = node_index;
    ctx->querying = 1;
    ctx->mark = instance->arena_top;
    ctx->scratch_taken = 0;
    ctx->state = instance->states[node_index];
}

static void ctx_end(struct CanopyCtx *ctx)
{
    ctx->instance->arena_top = ctx->mark;
}

static void zero_fill(float *out, int64_t n)
{
    memset(out, 0, (size_t)n * sizeof(float));
}

/* The point answer of an outlet. A node with only a span handler is asked for a one-sample span at (t, t); a failure gives 0.0. */
static float outlet_at(CanopyInstance *instance, int32_t node_index, int32_t outlet, int64_t t)
{
    const CanopyHandlers *handlers = &instance->graph->nodes[node_index].type->handlers;
    struct CanopyCtx ctx;
    float value = 0.0f;
    if (handlers->query_at) {
        ctx_begin(&ctx, instance, node_index);
        value = handlers->query_at(&ctx, outlet, t);
        ctx_end(&ctx);
    } else if (handlers->query_span) {
        ctx_begin(&ctx, instance, node_index);
        if (handlers->query_span(&ctx, outlet, t, t, 1, &value) != CANOPY_OK) value = 0.0f;
        ctx_end(&ctx);
    }
    return value;
}

/* The span answer of an outlet; the arguments have been checked (n, out, overflow). A node with only a point handler is asked once per
   sample time. Whatever the node did to `out`, a failure leaves it zero-filled. */
static int32_t outlet_span(CanopyInstance *instance, int32_t node_index, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    const CanopyHandlers *handlers = &instance->graph->nodes[node_index].type->handlers;
    struct CanopyCtx ctx;
    int32_t status;
    if (handlers->query_span) {
        ctx_begin(&ctx, instance, node_index);
        status = handlers->query_span(&ctx, outlet, t0, t1, n, out);
        ctx_end(&ctx);
    } else if (handlers->query_at) {
        CanopySpanPlan plan;
        int64_t i;
        status = canopy_span_plan(t0, t1, n, &plan);
        if (status == CANOPY_OK) {
            for (i = 0; i < n; i++) {
                ctx_begin(&ctx, instance, node_index);
                out[i] = handlers->query_at(&ctx, outlet, canopy_span_plan_time(&plan, i));
                ctx_end(&ctx);
            }
        }
    } else {
        status = CANOPY_ERR_DESCRIPTOR;                          /* the registry does not let a node with outlets lack both handlers */
    }
    if (status != CANOPY_OK) zero_fill(out, n);
    return status;
}

/* The checks every span request gets before anything is addressed, in this order: n (then `out` is not touched: its size is unknown),
   out != NULL, and t1 - t0 (then out is zero-filled). */
static int32_t check_span(int64_t t0, int64_t t1, int64_t n, float *out)
{
    if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;
    if (!out) return CANOPY_ERR_ARGUMENT;
    if (canopy_span_overflows(t0, t1)) {
        zero_fill(out, n);
        return CANOPY_ERR_OVERFLOW;
    }
    return CANOPY_OK;
}

/* ---- inlets: the connected outlet, or the knob ---- */

static float inlet_at(CanopyInstance *instance, int32_t node_index, int32_t inlet, int64_t t)
{
    const CanopyCNode *node = &instance->graph->nodes[node_index];
    CanopyLink link;
    if (inlet < 0 || inlet >= node->type->n_inlets) return 0.0f;
    link = node->links[inlet];
    if (link.node < 0) return canopy_slot_load(node->knobs[inlet]);
    return outlet_at(instance, link.node, link.outlet, t);
}

static int32_t inlet_span(CanopyInstance *instance, int32_t node_index, int32_t inlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    const CanopyCNode *node = &instance->graph->nodes[node_index];
    CanopyLink link;
    if (inlet < 0 || inlet >= node->type->n_inlets) {
        zero_fill(out, n);
        return CANOPY_ERR_PORT;
    }
    link = node->links[inlet];
    if (link.node < 0) {
        float knob = canopy_slot_load(node->knobs[inlet]);
        int64_t i;
        for (i = 0; i < n; i++) out[i] = knob;
        return CANOPY_OK;
    }
    return outlet_span(instance, link.node, link.outlet, t0, t1, n, out);
}

/* ---- what a handler may call ---- */

float canopy_inlet_at(CanopyCtx *ctx, int32_t inlet, int64_t t)
{
    if (!ctx || !ctx->querying) return 0.0f;
    return inlet_at(ctx->instance, ctx->node_index, inlet, t);
}

int32_t canopy_inlet_span(CanopyCtx *ctx, int32_t inlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    int32_t status = check_span(t0, t1, n, out);
    if (status != CANOPY_OK) return status;
    if (!ctx || !ctx->querying) {
        zero_fill(out, n);
        return CANOPY_ERR_ARGUMENT;
    }
    return inlet_span(ctx->instance, ctx->node_index, inlet, t0, t1, n, out);
}

float *canopy_scratch(CanopyCtx *ctx, int64_t n)
{
    CanopyInstance *instance;
    int64_t rounded;
    float *block;
    if (!ctx || !ctx->querying) return NULL;
    if (n < 1 || n > CANOPY_MAX_N) return NULL;
    if (ctx->scratch_taken >= ctx->node->type->scratch_buffers) return NULL;
    instance = ctx->instance;
    rounded = (n + 15) & ~(int64_t)15;                          /* whole cache lines of 16 floats, so every buffer starts aligned */
    if (instance->arena_top + rounded > instance->arena_floats) return NULL;
    block = instance->arena + instance->arena_top;
    instance->arena_top += rounded;
    ctx->scratch_taken++;
    return block;
}

void *canopy_ctx_state(CanopyCtx *ctx)
{
    return ctx ? ctx->state : NULL;
}

void *canopy_ctx_shared(CanopyCtx *ctx)
{
    return ctx && ctx->node ? ctx->node->shared : NULL;
}

uint64_t canopy_ctx_upstream_stamp(CanopyCtx *ctx)
{
    const CanopyCNode *node;
    uint64_t digest;
    int32_t i;
    if (!ctx || !ctx->node) return 0;
    node = ctx->node;
    digest = node->cone_static;
    for (i = 0; i < node->n_cone_gens; i++)
        digest = canopy_mix(digest, (uint64_t)atomic_load_explicit(node->cone_gens[i], memory_order_acquire));
    return digest;
}

void canopy_ctx_shared_changed(CanopyCtx *ctx)
{
    if (ctx && ctx->node && ctx->node->record) atomic_fetch_add_explicit(&ctx->node->record->shared_generation, 1, memory_order_acq_rel);
}

float canopy_ctx_boundary_value(CanopyCtx *ctx)
{
    if (!ctx || !ctx->node || !ctx->node->record || !(ctx->node->type->flags & CANOPY_FLAG_BOUNDARY_SLOT)) return 0.0f;
    return canopy_slot_load(&ctx->node->record->boundary);
}

/* the setting `index` of the node, if there is one of the given kinds */
static const CanopySettingValue *setting_of(CanopyCtx *ctx, int32_t index, int32_t kind_a, int32_t kind_b)
{
    int32_t kind;
    if (!ctx || !ctx->node || index < 0 || index >= ctx->node->type->n_settings) return NULL;
    kind = ctx->node->type->settings[index].kind;
    return kind == kind_a || kind == kind_b ? &ctx->node->settings[index] : NULL;
}

int64_t canopy_ctx_int(CanopyCtx *ctx, int32_t setting)
{
    const CanopySettingValue *value = setting_of(ctx, setting, CANOPY_SETTING_INT, CANOPY_SETTING_CHOICE);
    return value ? value->i : 0;
}

double canopy_ctx_float(CanopyCtx *ctx, int32_t setting)
{
    const CanopySettingValue *value = setting_of(ctx, setting, CANOPY_SETTING_FLOAT, CANOPY_SETTING_FLOAT);
    return value ? value->f : 0.0;
}

const char *canopy_ctx_string(CanopyCtx *ctx, int32_t setting)
{
    const CanopySettingValue *value = setting_of(ctx, setting, CANOPY_SETTING_STRING, CANOPY_SETTING_PATH);
    return value ? value->s : "";
}

/* ---- the host reads through an inlet ---- */

/* One caller at a time: an instance is used by one thread, and a second concurrent use (or a call from inside one of its own handlers) is
   refused rather than allowed to corrupt the arena. */
static int acquire(CanopyInstance *instance)
{
    if (atomic_exchange_explicit(&instance->busy, 1, memory_order_acquire) != 0) return 0;
    atomic_fetch_add_explicit(&instance->epoch, 1, memory_order_seq_cst);          /* odd: a query is running (see canopy_ctx_retire) */
    return 1;
}

static void release(CanopyInstance *instance)
{
    atomic_fetch_add_explicit(&instance->epoch, 1, memory_order_seq_cst);          /* even again */
    atomic_store_explicit(&instance->busy, 0, memory_order_release);
}

float canopy_instance_inlet_at(CanopyInstance *instance, int64_t node_id, int32_t inlet, int64_t t)
{
    int32_t index = 0;
    float value = 0.0f;
    if (!instance || !acquire(instance)) return 0.0f;
    canopy_instance_adopt(instance);                                          /* a newly installed graph is taken up here, by swapping pointers */
    if (canopy_compiled_find(instance->graph, node_id, &index)) value = inlet_at(instance, index, inlet, t);
    release(instance);
    return value;
}

/* The boundary outlet called `name` in the graph the instance runs, as a node index, or -1. */
static int32_t outlet_by_name(const CanopyInstance *instance, const char *name)
{
    const CanopyBoundary *entry = canopy_compiled_find_boundary(instance->graph, name);
    return entry && entry->kind == CANOPY_BOUNDARY_OUTLET ? entry->node : -1;
}

int32_t canopy_instance_read_at_status(CanopyInstance *instance, const char *name, int64_t t, float *value)
{
    int32_t index, status = CANOPY_OK;
    if (value) *value = 0.0f;
    if (!instance || !name || !value) return CANOPY_ERR_ARGUMENT;
    if (!acquire(instance)) return CANOPY_ERR_BUSY;
    canopy_instance_adopt(instance);
    index = outlet_by_name(instance, name);
    if (index >= 0) *value = inlet_at(instance, index, 0, t);
    else status = CANOPY_ERR_NODE;
    release(instance);
    return status;
}

float canopy_instance_read_at(CanopyInstance *instance, const char *name, int64_t t)
{
    float value = 0.0f;
    canopy_instance_read_at_status(instance, name, t, &value);
    return value;
}

int32_t canopy_instance_read_span(CanopyInstance *instance, const char *name, int64_t t0, int64_t t1, int64_t n, float *out)
{
    int32_t index;
    int32_t status = check_span(t0, t1, n, out);
    if (status != CANOPY_OK) return status;
    if (!instance || !name) {
        zero_fill(out, n);
        return CANOPY_ERR_ARGUMENT;
    }
    if (!acquire(instance)) {
        zero_fill(out, n);
        return CANOPY_ERR_BUSY;
    }
    canopy_instance_adopt(instance);
    index = outlet_by_name(instance, name);
    if (index < 0) {
        zero_fill(out, n);
        status = CANOPY_ERR_NODE;
    } else {
        status = inlet_span(instance, index, 0, t0, t1, n, out);
    }
    release(instance);
    return status;
}

int32_t canopy_instance_inlet_span(CanopyInstance *instance, int64_t node_id, int32_t inlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    int32_t index = 0;
    int32_t status = check_span(t0, t1, n, out);
    if (status != CANOPY_OK) return status;
    if (!instance) {
        zero_fill(out, n);
        return CANOPY_ERR_ARGUMENT;
    }
    if (!acquire(instance)) {
        zero_fill(out, n);
        return CANOPY_ERR_BUSY;
    }
    canopy_instance_adopt(instance);
    if (!canopy_compiled_find(instance->graph, node_id, &index)) {
        zero_fill(out, n);
        status = CANOPY_ERR_NODE;
    } else {
        status = inlet_span(instance, index, inlet, t0, t1, n, out);
    }
    release(instance);
    return status;
}
