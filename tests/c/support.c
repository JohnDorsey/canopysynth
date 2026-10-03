#include <stdlib.h>
#include <string.h>
#include "support.h"

/* ---- guarded buffers ---- */

#define CANARY_BITS 0x7FC0CA9Au          /* quiet NaN patterns that no test node ever produces */
#define UNWRITTEN_BITS 0xFFC0DEADu

uint32_t float_bits(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof bits);
    return bits;
}

static void put_bits(float *where, uint32_t bits)
{
    memcpy(where, &bits, sizeof bits);
}

void guarded_reset(Guarded *g)
{
    int64_t i, total = g->n + 2 * GUARD_FLOATS;
    for (i = 0; i < total; i++) put_bits(&g->block[i], (i < GUARD_FLOATS || i >= GUARD_FLOATS + g->n) ? CANARY_BITS : UNWRITTEN_BITS);
}

Guarded guarded_new(int64_t n)
{
    Guarded g;
    g.n = n;
    g.block = (float *)malloc((size_t)(n + 2 * GUARD_FLOATS) * sizeof(float));
    g.data = g.block ? g.block + GUARD_FLOATS : NULL;
    if (!g.block) {
        CHECK(g.block != NULL);
        return g;
    }
    guarded_reset(&g);
    return g;
}

void guarded_free(Guarded *g)
{
    free(g->block);
    g->block = g->data = NULL;
}

int guarded_guards_intact(const Guarded *g)
{
    int64_t i;
    for (i = 0; i < GUARD_FLOATS; i++)
        if (float_bits(g->block[i]) != CANARY_BITS || float_bits(g->data[g->n + i]) != CANARY_BITS) return 0;
    return 1;
}

int64_t guarded_unwritten(const Guarded *g)
{
    int64_t i, count = 0;
    for (i = 0; i < g->n; i++)
        if (float_bits(g->data[i]) == UNWRITTEN_BITS) count++;
    return count;
}

int guarded_all_zero(const Guarded *g)
{
    int64_t i;
    for (i = 0; i < g->n; i++)
        if (float_bits(g->data[i]) != 0u) return 0;
    return 1;
}

int guarded_equals(const Guarded *g, const float *expected)
{
    return memcmp(g->data, expected, (size_t)g->n * sizeof(float)) == 0;
}

int guarded_bits_equal(const Guarded *a, const Guarded *b)
{
    return a->n == b->n && memcmp(a->data, b->data, (size_t)a->n * sizeof(float)) == 0;
}

/* ---- the call log ---- */

LoggedCall support_calls[CALL_LOG_MAX];
int support_ncalls = 0;

void support_calls_reset(void)
{
    support_ncalls = 0;
}

static void log_call(int is_span, int32_t outlet, int64_t t0, int64_t t1, int64_t n)
{
    if (support_ncalls < CALL_LOG_MAX) {
        LoggedCall *call = &support_calls[support_ncalls];
        call->is_span = is_span;
        call->outlet = outlet;
        call->t0 = t0;
        call->t1 = t1;
        call->n = n;
    }
    support_ncalls++;
}

/* ---- the test node types ---- */

static void fill(float *out, int64_t n, float value)
{
    int64_t i;
    for (i = 0; i < n; i++) out[i] = value;
}

static float const_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet; (void)t;
    return (float)canopy_ctx_float(ctx, 0);
}

static int32_t const_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    (void)outlet; (void)t0; (void)t1;
    fill(out, n, (float)canopy_ctx_float(ctx, 0));
    return CANOPY_OK;
}

static float time_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx;
    return outlet == 0 ? (float)t : 2.0f * (float)t;
}

static float recorder_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx;
    log_call(0, outlet, t, t, 1);
    return 0.5f;
}

static int32_t recorder_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    (void)ctx;
    log_call(1, outlet, t0, t1, n);
    fill(out, n, 0.25f);
    return CANOPY_OK;
}

static float gain_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet;
    return canopy_inlet_at(ctx, 0, t) * canopy_inlet_at(ctx, 1, t);
}

static int32_t gain_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    float *gain;
    int32_t status;
    int64_t i;
    (void)outlet;
    gain = canopy_scratch(ctx, n);
    if (!gain) return CANOPY_ERR_MEMORY;
    status = canopy_inlet_span(ctx, 0, t0, t1, n, out);
    if (status != CANOPY_OK) return status;
    status = canopy_inlet_span(ctx, 1, t0, t1, n, gain);
    if (status != CANOPY_OK) return status;
    for (i = 0; i < n; i++) out[i] *= gain[i];
    return CANOPY_OK;
}

static float sum_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet;
    return canopy_inlet_at(ctx, 0, t) + canopy_inlet_at(ctx, 1, t);
}

static float shift_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet;
    return canopy_inlet_at(ctx, 0, t + canopy_ctx_int(ctx, 0));
}

static int32_t shift_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    int64_t shift = canopy_ctx_int(ctx, 0);
    (void)outlet;
    return canopy_inlet_span(ctx, 0, t0 + shift, t1 + shift, n, out);
}

static float failing_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx; (void)outlet; (void)t;
    return 5.0f;
}

static int32_t failing_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    (void)ctx; (void)outlet; (void)t0; (void)t1;
    fill(out, n, 123.0f);                                   /* garbage that the engine must replace with zeros */
    return FAILING_STATUS;
}

/* ---- node types of plan step 4 ---- */

int support_counts[SUPPORT_TAGS];
uint64_t support_stamps[SUPPORT_TAGS];
int support_shared_created, support_shared_destroyed, support_state_created, support_state_destroyed;

void support_counters_reset(void)
{
    memset(support_counts, 0, sizeof support_counts);
    memset(support_stamps, 0, sizeof support_stamps);
    support_shared_created = support_shared_destroyed = support_state_created = support_state_destroyed = 0;
}

#define SAW_PERIOD 250000000LL

float support_saw(int64_t t)
{
    int64_t r = t % SAW_PERIOD;
    if (r < 0) r += SAW_PERIOD;
    return (float)((double)r * (2.0 / (double)SAW_PERIOD) - 1.0);
}

static float saw_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx; (void)outlet;
    return support_saw(t);
}

float support_jitter(int64_t t)
{
    int64_t r = t % 1000;
    if (r < 0) r += 1000;
    return (float)r / 1000.0f;
}

static float jitter_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx; (void)outlet;
    return support_jitter(t);
}

static int tag_of(CanopyCtx *ctx, int32_t setting)
{
    int64_t tag = canopy_ctx_int(ctx, setting);
    return (tag >= 0 && tag < SUPPORT_TAGS) ? (int)tag : 0;
}

static float counter_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet; (void)t;
    support_counts[tag_of(ctx, 1)]++;
    return (float)canopy_ctx_float(ctx, 0);
}

static float config_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx; (void)outlet; (void)t;
    return 0.0f;                                            /* the settings are there to be changed, not read */
}

static float stamp_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet;
    support_stamps[tag_of(ctx, 0)] = canopy_ctx_upstream_stamp(ctx);
    return canopy_ctx_int(ctx, 1) ? canopy_inlet_at(ctx, 0, t) : 0.0f;
}

static void *source_create_shared(CanopyCtx *ctx)
{
    float *value = (float *)malloc(sizeof(float));
    (void)ctx;
    *value = 1.0f;
    support_shared_created++;
    return value;
}

static void source_destroy_shared(CanopyCtx *ctx, void *shared)
{
    (void)ctx;
    free(shared);
    support_shared_destroyed++;
}

static float source_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    const float *value = (const float *)canopy_ctx_shared(ctx);
    (void)outlet; (void)t;
    return value ? *value : -1.0f;
}

static void source_action(CanopyCtx *ctx, const char *action)
{
    float *value = (float *)canopy_ctx_shared(ctx);
    if (value && strcmp(action, "bump") == 0) {
        *value += 1.0f;
        canopy_ctx_shared_changed(ctx);
    }
}

static void *state_create(CanopyCtx *ctx)
{
    int *counter = (int *)malloc(sizeof(int));
    (void)ctx;
    *counter = 3;
    support_state_created++;
    return counter;
}

static void state_destroy(CanopyCtx *ctx, void *state)
{
    (void)ctx;
    free(state);
    support_state_destroyed++;
}

static float state_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    int *counter = (int *)canopy_ctx_state(ctx);
    (void)outlet; (void)t;
    return counter ? (float)(++*counter) : -1.0f;
}

static float boundary_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet; (void)t;
    return canopy_ctx_boundary_value(ctx);
}

static const CanopyOutletDesc OUT_ONE[] = {{"out", "Out"}};
static const CanopyOutletDesc OUT_AB[] = {{"a", "A"}, {"b", "B"}};
static const CanopyInletDesc IN_ONE[] = {{"in", "In", 0.0f}};
static const CanopyInletDesc IN_GAIN[] = {{"in", "In", 0.0f}, {"gain", "Gain", 1.0f}};
static const CanopyInletDesc IN_AB[] = {{"a", "A", 0.0f}, {"b", "B", 0.0f}};
static const CanopyInletDesc IN_SINK[] = {{"in0", "In 0", 0.0f}, {"in1", "In 1", 0.5f}};
static const CanopySettingDesc SETTING_VALUE[] = {{"value", CANOPY_SETTING_FLOAT, 0, 0.0, NULL, 0, NULL}};
static const CanopySettingDesc SETTING_SHIFT[] = {{"shift", CANOPY_SETTING_INT, 0, 0.0, NULL, 0, NULL}};
static const CanopySettingDesc SETTINGS_COUNTER[] = {{"value", CANOPY_SETTING_FLOAT, 0, 0.0, NULL, 0, NULL},
                                                     {"tag", CANOPY_SETTING_INT, 0, 0.0, NULL, 0, NULL}};
static const CanopySettingDesc SETTINGS_STAMP[] = {{"tag", CANOPY_SETTING_INT, 0, 0.0, NULL, 0, NULL},
                                                   {"pass", CANOPY_SETTING_INT, 1, 0.0, NULL, 0, NULL},
                                                   {"salt", CANOPY_SETTING_INT, 0, 0.0, NULL, 0, NULL}};
static const char *const CONFIG_CHOICES[] = {"x", "y", "z"};
static const CanopySettingDesc SETTINGS_CONFIG[] = {{"text", CANOPY_SETTING_STRING, 0, 0.0, "a", 0, NULL},
                                                    {"file", CANOPY_SETTING_PATH, 0, 0.0, NULL, 0, NULL},
                                                    {"mode", CANOPY_SETTING_CHOICE, 0, 0.0, NULL, 3, CONFIG_CHOICES},
                                                    {"level", CANOPY_SETTING_FLOAT, 0, 0.0, NULL, 0, NULL},
                                                    {"count", CANOPY_SETTING_INT, 0, 0.0, NULL, 0, NULL}};

CanopyNodeType support_base_type(const char *key, const char *name)
{
    CanopyNodeType type;
    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = (uint32_t)sizeof type;
    type.key = key;
    type.name = name;
    type.type_version = 1;
    return type;
}

void support_add_type(CanopyRegistry *registry, const CanopyNodeType *type)
{
    int32_t status = canopy_registry_register(registry, type);
    CHECK_INT(status, CANOPY_OK);
    if (status != CANOPY_OK) printf("    registry says: %s\n", canopy_registry_last_error(registry));
}

void support_add_builtin(CanopyRegistry *registry, const CanopyNodeType *type)
{
    int32_t status = canopy_registry_register_builtin(registry, type);
    CHECK_INT(status, CANOPY_OK);
    if (status != CANOPY_OK) printf("    registry says: %s\n", canopy_registry_last_error(registry));
}

CanopyRegistry *support_registry(void)
{
    CanopyRegistry *registry = canopy_registry_new();
    CanopyNodeType t;

    t = support_base_type("test.const", "Const");
    t.n_outlets = 1; t.outlets = OUT_ONE; t.n_settings = 1; t.settings = SETTING_VALUE;
    t.handlers.query_at = const_at;
    support_add_type(registry, &t);

    t = support_base_type("test.const_span", "Const (span only)");
    t.n_outlets = 1; t.outlets = OUT_ONE; t.n_settings = 1; t.settings = SETTING_VALUE;
    t.handlers.query_span = const_span;
    support_add_type(registry, &t);

    t = support_base_type("test.time", "Time");
    t.n_outlets = 2; t.outlets = OUT_AB;
    t.handlers.query_at = time_at;
    support_add_type(registry, &t);

    t = support_base_type("test.recorder", "Recorder");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_at = recorder_at;
    support_add_type(registry, &t);

    t = support_base_type("test.recorder_span", "Recorder (span)");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_span = recorder_span;
    support_add_type(registry, &t);

    t = support_base_type("test.gain", "Gain");
    t.n_inlets = 2; t.inlets = IN_GAIN; t.n_outlets = 1; t.outlets = OUT_ONE; t.scratch_buffers = 1;
    t.handlers.query_at = gain_at; t.handlers.query_span = gain_span;
    support_add_type(registry, &t);

    t = support_base_type("test.sum", "Sum");
    t.n_inlets = 2; t.inlets = IN_AB; t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_at = sum_at;
    support_add_type(registry, &t);

    t = support_base_type("test.shift", "Shift");
    t.n_inlets = 1; t.inlets = IN_ONE; t.n_outlets = 1; t.outlets = OUT_ONE; t.n_settings = 1; t.settings = SETTING_SHIFT;
    t.handlers.query_at = shift_at; t.handlers.query_span = shift_span;
    support_add_type(registry, &t);

    t = support_base_type("test.sink", "Sink");
    t.n_inlets = 2; t.inlets = IN_SINK;
    support_add_type(registry, &t);

    t = support_base_type("test.failing", "Failing");
    t.n_inlets = 1; t.inlets = IN_ONE; t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_at = failing_at; t.handlers.query_span = failing_span;
    support_add_type(registry, &t);

    t = support_base_type("test.failing_span_only", "Failing (span only)");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_span = failing_span;
    support_add_type(registry, &t);

    t = support_base_type("test.saw", "Saw");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_at = saw_at;
    support_add_type(registry, &t);

    t = support_base_type("test.jitter", "Jitter");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_at = jitter_at;
    support_add_type(registry, &t);

    t = support_base_type("test.counter", "Counter");
    t.n_outlets = 1; t.outlets = OUT_ONE; t.n_settings = 2; t.settings = SETTINGS_COUNTER;
    t.handlers.query_at = counter_at;
    support_add_type(registry, &t);

    t = support_base_type("test.config", "Config");
    t.n_outlets = 1; t.outlets = OUT_ONE; t.n_settings = 5; t.settings = SETTINGS_CONFIG;
    t.handlers.query_at = config_at;
    support_add_type(registry, &t);

    t = support_base_type("test.stamp", "Stamp");
    t.n_inlets = 1; t.inlets = IN_ONE; t.n_outlets = 1; t.outlets = OUT_ONE; t.n_settings = 3; t.settings = SETTINGS_STAMP;
    t.handlers.query_at = stamp_at;
    support_add_type(registry, &t);

    t = support_base_type("test.source", "Source");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.create_shared = source_create_shared; t.handlers.destroy_shared = source_destroy_shared;
    t.handlers.query_at = source_at; t.handlers.on_action = source_action;
    support_add_type(registry, &t);

    t = support_base_type("test.state", "State");
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.create_instance = state_create; t.handlers.destroy_instance = state_destroy;
    t.handlers.query_at = state_at;
    support_add_type(registry, &t);

    t = support_base_type("test_boundary", "Boundary value");
    t.flags = CANOPY_FLAG_BOUNDARY_SLOT;
    t.n_outlets = 1; t.outlets = OUT_ONE;
    t.handlers.query_at = boundary_at;
    support_add_builtin(registry, &t);

    CHECK_INT(canopy_registry_add_test_nodes(registry), CANOPY_OK);
    return registry;
}

/* ---- the rig ---- */

void rig_open(Rig *rig)
{
    memset(rig, 0, sizeof *rig);
    rig->live_before = canopy_alloc_live();
    rig->registry = support_registry();
    rig->graph = canopy_graph_new();
    rig->engine = canopy_engine_new(rig->registry);
    CHECK(rig->registry != NULL && rig->graph != NULL && rig->engine != NULL);
}

void rig_node(Rig *rig, int64_t id, const char *type)
{
    CHECK_INT(canopy_graph_add_node(rig->graph, id, type), CANOPY_OK);
}

void rig_connect(Rig *rig, int64_t from, const char *outlet, int64_t to, const char *inlet)
{
    CHECK_INT(canopy_graph_connect(rig->graph, from, outlet, to, inlet), CANOPY_OK);
}

void rig_install(Rig *rig)
{
    int32_t status = canopy_engine_set_graph(rig->engine, rig->graph);
    CHECK_INT(status, CANOPY_OK);
    if (status != CANOPY_OK) printf("    engine says: %s\n", canopy_engine_last_error(rig->engine));
    if (rig->instance) {
        canopy_instance_free(rig->instance);
        rig->instance = NULL;
    }
    rig->instance = canopy_engine_new_instance(rig->engine);
    CHECK(rig->instance != NULL);
}

void rig_close(Rig *rig)
{
    if (rig->instance) canopy_instance_free(rig->instance);
    CHECK_INT(canopy_engine_free(rig->engine), CANOPY_OK);
    canopy_graph_free(rig->graph);
    canopy_registry_free(rig->registry);
    CHECK_INT(canopy_alloc_live(), rig->live_before);
    CHECK_HEAP();
    memset(rig, 0, sizeof *rig);
}
