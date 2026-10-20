/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The hidden, test-only node types (design section 11: "a hidden, test-only stateful node exists so that the generation numbers and checkpoints
   are exercised by the tests"). They are registered only by canopy_registry_add_test_nodes(), so no editor or host listing sees them.

   test_filter: a one-pole low-pass filter whose output depends on all of its past.
     Settings: `initial` (FLOAT, 0): the state before the first sample; `checkpoint_seconds` (INT, 10; below 1 counts as 1): how often the
     state is checkpointed; `internal_sampling_rate` (the registry adds it: whole Hz, 1 to 384000, default 48000).
     Inlets: `in` (the signal) and `coef` (a = clamp((coef + 1) / 2, 0, 1), so a knob at 0 gives 0.5).
     The grid: sample k is at k / rate seconds (anchored at t = 0). Its time in ns is the exact value rounded half up. The filter asks both
     inlets, with POINT queries, at the grid times: y[k] = y[k-1] + a[k] * (x[k] - y[k-1]) for k >= 0, in float32 arithmetic, one operation at a
     time; y[k] = initial for k < 0. The answer at a time t between two samples is the linear interpolation of y[k] and y[k+1], with k the
     floor of t * rate / 1e9 and the position between them exact: (float)(y0 + fraction * (y1 - y0)) computed in double.
     History: a checkpoint holds y[j * M - 1] (M = checkpoint_seconds * rate samples), j = 0, 1, 2... (j = 0 is `initial`); they are made in
     order as the filter renders forward. A query starts from the nearest checkpoint at or before the sample it needs, or from where the
     previous query stopped if that is nearer. At the start of every query the filter reads the upstream stamp; if it differs from the one the
     checkpoints were made under, they are all thrown away. The node allocates while querying, so it is not flagged realtime_safe. */
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "canopy_core.h"

enum { SETTING_INITIAL = 0, SETTING_SECONDS = 1, SETTING_RATE = 2 };          /* the third is the one the registry adds */

typedef struct {
    int have_stamp;
    uint64_t stamp;                          /* the upstream stamp the checkpoints and the cursor were made under */
    float *checkpoints;
    int64_t n_checkpoints, cap_checkpoints;
    int cursor_valid;                        /* the two values y[cursor_k] and y[cursor_k + 1] of the previous query */
    int64_t cursor_k;
    float cursor_y[2];
} FilterState;

typedef struct {
    CanopyCtx *ctx;
    FilterState *state;
    int64_t rate, interval;                  /* the internal rate, and the samples between checkpoints */
    float initial;
} Run;

static void *filter_create(CanopyCtx *ctx)
{
    (void)ctx;
    return canopy_alloc(sizeof(FilterState));
}

static void filter_destroy(CanopyCtx *ctx, void *state)
{
    FilterState *filter = (FilterState *)state;
    (void)ctx;
    canopy_free(filter->checkpoints);
    canopy_free(filter);
}

static int append_checkpoint(FilterState *filter, float y)
{
    if (filter->n_checkpoints == filter->cap_checkpoints) {
        int64_t capacity = filter->cap_checkpoints ? filter->cap_checkpoints * 2 : 16;
        float *grown = (float *)canopy_realloc(filter->checkpoints, (size_t)filter->cap_checkpoints * sizeof(float), (size_t)capacity * sizeof(float));
        if (!grown) return 0;                                              /* no more checkpoints: the filter still answers, only slower */
        filter->checkpoints = grown;
        filter->cap_checkpoints = capacity;
    }
    filter->checkpoints[filter->n_checkpoints++] = y;
    return 1;
}

/* Reads the settings and, FIRST of all, the upstream stamp; throws the checkpoints away if the stamp is not the one they were made under. */
static void run_begin(Run *run, CanopyCtx *ctx, FilterState *filter)
{
    int64_t seconds = canopy_ctx_int(ctx, SETTING_SECONDS);
    uint64_t stamp = canopy_ctx_upstream_stamp(ctx);
    run->ctx = ctx;
    run->state = filter;
    run->rate = canopy_ctx_int(ctx, SETTING_RATE);
    if (seconds < 1) seconds = 1;
    if (seconds > 3600000) seconds = 3600000;                              /* (a thousand hours: keeps seconds * rate far from overflow) */
    run->interval = seconds * run->rate;
    run->initial = (float)canopy_ctx_float(ctx, SETTING_INITIAL);
    if (!filter->have_stamp || stamp != filter->stamp) {
        filter->n_checkpoints = 0;
        filter->cursor_valid = 0;
        filter->stamp = stamp;
        filter->have_stamp = 1;
        (void)append_checkpoint(filter, run->initial);                     /* checkpoint 0: the state before the first sample */
    }
}

/* One step of the filter: the next value from the previous one, for grid sample i. */
static float step(const Run *run, float y, int64_t i)
{
    int64_t t = 0;
    float x = 0.0f, c = 0.0f, a, difference, scaled;
    if (canopy_frame_to_ns(i, run->rate, &t) != CANOPY_OK) t = INT64_MAX;
    (void)canopy_inlet_at(run->ctx, 0, t, &x);                             /* an input that fails is silence: the status is of no use here */
    (void)canopy_inlet_at(run->ctx, 1, t, &c);
    a = fminf(fmaxf((c + 1.0f) * 0.5f, 0.0f), 1.0f);
    difference = x - y;
    scaled = a * difference;
    return y + scaled;
}

/* Having just computed y[i]: keeps it if it is the state just before a checkpoint boundary that has no checkpoint yet. */
static void note(const Run *run, int64_t i, float y)
{
    FilterState *filter = run->state;
    if ((i + 1) % run->interval == 0 && (i + 1) / run->interval == filter->n_checkpoints) (void)append_checkpoint(filter, y);
}

/* y[k] for k >= 0, rendered forward from the nearest known state at or before it. */
static float y_at(const Run *run, int64_t k)
{
    FilterState *filter = run->state;
    int64_t s = -1, i;                                                     /* y[s] is known; it is `y` */
    float y = run->initial;
    if (filter->n_checkpoints > 0) {
        int64_t j = k / run->interval;
        if (j >= filter->n_checkpoints) j = filter->n_checkpoints - 1;     /* ahead of the checkpoints made so far: from the last one */
        s = j * run->interval - 1;
        y = filter->checkpoints[j];
    }
    if (filter->cursor_valid) {                                            /* where the previous query stopped, if that is nearer */
        if (filter->cursor_k + 1 <= k && filter->cursor_k + 1 > s) {
            s = filter->cursor_k + 1;
            y = filter->cursor_y[1];
        } else if (filter->cursor_k == k && filter->cursor_k > s) {
            s = filter->cursor_k;
            y = filter->cursor_y[0];
        }
    }
    for (i = s + 1; i <= k; i++) {
        y = step(run, y, i);
        note(run, i, y);
    }
    return y;
}

/* y[k] and y[k + 1] for any k (the initial value before the first sample). */
static void pair_at(const Run *run, int64_t k, float *y0, float *y1)
{
    FilterState *filter = run->state;
    if (k < 0) {
        *y0 = run->initial;
        *y1 = k + 1 < 0 ? run->initial : y_at(run, 0);
        return;
    }
    if (filter->cursor_valid && filter->cursor_k == k) {
        *y0 = filter->cursor_y[0];
        *y1 = filter->cursor_y[1];
        return;
    }
    *y0 = y_at(run, k);
    *y1 = step(run, *y0, k + 1);
    note(run, k + 1, *y1);
    filter->cursor_valid = 1;
    filter->cursor_k = k;
    filter->cursor_y[0] = *y0;
    filter->cursor_y[1] = *y1;
}

static float value_at(const Run *run, int64_t t)
{
    int64_t k = 0;
    double fraction = 0.0;
    float y0, y1;
    if (canopy_ns_to_frame_fraction(t, run->rate, &k, &fraction) != CANOPY_OK) return 0.0f;
    pair_at(run, k, &y0, &y1);
    return (float)((double)y0 + fraction * ((double)y1 - (double)y0));
}

static int32_t filter_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    FilterState *filter = (FilterState *)canopy_ctx_state(ctx);
    Run run;
    (void)outlet;
    if (!filter) return CANOPY_ERR_MEMORY;
    run_begin(&run, ctx, filter);
    *out = value_at(&run, t);
    return CANOPY_OK;
}

static int32_t filter_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    FilterState *filter = (FilterState *)canopy_ctx_state(ctx);
    CanopySpanPlan plan;
    Run run;
    int64_t i;
    int32_t status;
    (void)outlet;
    if (!filter) return CANOPY_ERR_MEMORY;
    status = canopy_span_plan(t0, t1, n, &plan);
    if (status != CANOPY_OK) return status;
    run_begin(&run, ctx, filter);                                          /* the stamp is read once, before the first input */
    for (i = 0; i < n; i++) out[i] = value_at(&run, canopy_span_plan_time(&plan, i));
    return CANOPY_OK;
}

static const CanopyInletDesc FILTER_INLETS[] = {{"in", "In", 0.0f}, {"coef", "Coefficient", 0.0f}};
static const CanopyOutletDesc FILTER_OUTLETS[] = {{"out", "Out"}};
static const CanopySettingDesc FILTER_SETTINGS[] = {
    {"initial", CANOPY_SETTING_FLOAT, 0, 0.0, NULL, 0, NULL},
    {"checkpoint_seconds", CANOPY_SETTING_INT, 10, 0.0, NULL, 0, NULL},
};

int32_t canopy_registry_add_test_nodes(CanopyRegistry *registry)
{
    CanopyNodeType type;
    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = (uint32_t)sizeof type;
    type.key = "test_filter";
    type.name = "Test filter (hidden)";
    type.type_version = 1;
    type.flags = CANOPY_FLAG_HAS_INTERNAL_RATE;                         /* not realtime_safe: it allocates while querying */
    type.n_inlets = 2; type.inlets = FILTER_INLETS;
    type.n_outlets = 1; type.outlets = FILTER_OUTLETS;
    type.n_settings = 2; type.settings = FILTER_SETTINGS;
    type.handlers.create_instance = filter_create;
    type.handlers.destroy_instance = filter_destroy;
    type.handlers.query_at = filter_at;
    type.handlers.query_span = filter_span;
    return canopy_registry_register_builtin(registry, &type);
}
