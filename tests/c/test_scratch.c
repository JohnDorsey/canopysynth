/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Tests: the scratch arena (docs/canopy_design.md sections 8 and 12): its size from the declared counts along the deepest chain, and
   canopy_scratch() with its rules (up to 65536 floats, no more buffers than declared, released when the handler returns). */
#include <stdint.h>
#include <string.h>
#include "support.h"

static const CanopyInletDesc IN_AB[] = {{"a", "A", 0.0f}, {"b", "B", 0.0f}};
static const CanopyInletDesc IN_ONE[] = {{"in", "In", 0.0f}};
static const CanopyOutletDesc OUT_ONE[] = {{"out", "Out"}};

static int32_t zero_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    (void)ctx; (void)outlet; (void)t;
    { *out = 0.0f; return CANOPY_OK; }
}

static void add_budget_type(CanopyRegistry *registry, const char *key, int32_t budget)
{
    CanopyNodeType type = support_base_type(key, key);
    type.n_inlets = 2; type.inlets = IN_AB; type.n_outlets = 1; type.outlets = OUT_ONE;
    type.scratch_buffers = budget;
    type.handlers.query_at = zero_at;
    support_add_type(registry, &type);
}

/* test.b0 .. test.b5: two inlets, one outlet, declaring that many scratch buffers; they do nothing when queried */
static void add_budget_types(CanopyRegistry *registry)
{
    add_budget_type(registry, "test.b0", 0);
    add_budget_type(registry, "test.b1", 1);
    add_budget_type(registry, "test.b2", 2);
    add_budget_type(registry, "test.b3", 3);
    add_budget_type(registry, "test.b4", 4);
    add_budget_type(registry, "test.b5", 5);
}

static int64_t arena_buffers(Rig *rig)
{
    int64_t floats = canopy_instance_arena_floats(rig->instance);
    CHECK_INT(floats % CANOPY_MAX_N, 0);                                   /* always whole buffers of the largest size */
    return floats / CANOPY_MAX_N;
}

/* ---- the size of the arena ---- */

static void test_c_the_arena_is_sized_for_the_deepest_chain_of_declared_buffers(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b2");
    rig_node(&rig, 2, "test.b1");
    rig_node(&rig, 3, "test.b3");
    rig_connect(&rig, 3, "out", 2, "a");                 /* 1 asks 2 asks 3: 2 + 1 + 3 buffers held at once */
    rig_connect(&rig, 2, "out", 1, "a");
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 6);
    CHECK_INT(canopy_instance_arena_floats(rig.instance), 6LL * CANOPY_MAX_N);
    rig_close(&rig);
}

static void test_c_in_a_diamond_the_heavier_branch_decides(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b1");                        /* S, the source */
    rig_node(&rig, 2, "test.b2");                        /* P */
    rig_node(&rig, 3, "test.b5");                        /* Q */
    rig_node(&rig, 4, "test.b1");                        /* R, the consumer */
    rig_connect(&rig, 1, "out", 2, "a");
    rig_connect(&rig, 1, "out", 3, "a");
    rig_connect(&rig, 2, "out", 4, "a");
    rig_connect(&rig, 3, "out", 4, "b");
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 1 + 5 + 1);           /* R, then Q (heavier than P), then S */
    rig_close(&rig);
}

static void test_c_separate_parts_of_a_graph_do_not_add_up(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b3");                        /* alone */
    rig_node(&rig, 2, "test.b2");
    rig_node(&rig, 3, "test.b0");
    rig_node(&rig, 4, "test.b1");
    rig_connect(&rig, 3, "out", 2, "a");                 /* 2 + 0 */
    rig_connect(&rig, 4, "out", 2, "b");                 /* 2 + 1 */
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 3);                   /* the larger of 3, and 2 + 1 */
    rig_close(&rig);
}

static void test_c_a_source_feeding_two_inlets_of_one_node_is_counted_once(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b1");
    rig_node(&rig, 2, "test.b3");
    rig_connect(&rig, 1, "out", 2, "a");
    rig_connect(&rig, 1, "out", 2, "b");
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 4);
    rig_close(&rig);
}

static void test_c_a_graph_whose_nodes_declare_no_buffers_has_no_arena_and_still_works(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b0");
    rig_node(&rig, 2, "test.b0");
    rig_node(&rig, 3, "test.sink");
    rig_connect(&rig, 1, "out", 2, "a");
    rig_connect(&rig, 2, "out", 3, "in0");
    rig_install(&rig);
    CHECK_INT(canopy_instance_arena_floats(rig.instance), 0);
    CHECK(host_inlet_at(rig.instance, 3, 0, 0) == 0.0f);
    rig_close(&rig);
}

static void test_c_with_a_loop_anywhere_the_arena_is_sized_for_every_node_holding_its_buffers_at_once(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b1");
    rig_node(&rig, 2, "test.b2");
    rig_node(&rig, 3, "test.b5");                        /* not in the loop */
    rig_connect(&rig, 2, "out", 1, "a");
    rig_connect(&rig, 1, "out", 2, "a");                 /* 1 and 2 ask each other */
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 1 + 2 + 5);
    rig_close(&rig);
    rig_open(&rig);
    add_budget_types(rig.registry);
    rig_node(&rig, 1, "test.b2");
    rig_connect(&rig, 1, "out", 1, "a");                 /* a node asking itself */
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 2);
    rig_close(&rig);
}

static void test_c_the_arena_size_refuses_a_buffer_count_whose_byte_size_would_not_fit(void)
{
    int64_t floats = -1, lo = 1, hi = INT64_MAX;
    const int64_t true_limit = INT64_MAX / (CANOPY_MAX_N * 4);          /* the most buffers whose size in bytes fits an int64 */
    CHECK_INT(canopy_arena_floats(0, &floats), CANOPY_OK);
    CHECK_INT(floats, 0);
    CHECK_INT(canopy_arena_floats(1, &floats), CANOPY_OK);
    CHECK_INT(floats, CANOPY_MAX_N);
    CHECK_INT(canopy_arena_floats(7, &floats), CANOPY_OK);
    CHECK_INT(floats, 7LL * CANOPY_MAX_N);
    CHECK_INT(canopy_arena_floats(-1, &floats), CANOPY_ERR_OVERFLOW);
    CHECK_INT(canopy_arena_floats(INT64_MAX, &floats), CANOPY_ERR_OVERFLOW);
    while (hi - lo > 1) {                                               /* bisect: lo is accepted, hi refused */
        int64_t mid = lo + (hi - lo) / 2;
        if (canopy_arena_floats(mid, &floats) == CANOPY_OK) lo = mid; else hi = mid;
    }
    CHECK_INT(canopy_arena_floats(lo, &floats), CANOPY_OK);
    CHECK(floats <= INT64_MAX / 4);                                      /* what is accepted can be addressed in bytes */
    CHECK_INT(floats, lo * CANOPY_MAX_N);
    CHECK_INT(lo, true_limit - 1);                      /* exactly one buffer is kept back, so that the byte size plus alignment still fits */
    CHECK_INT(canopy_arena_floats(hi, &floats), CANOPY_ERR_OVERFLOW);
}

static void test_c_an_arena_too_big_to_allocate_gives_no_instance_instead_of_a_crash(void)
{
    Rig rig;
    rig_open(&rig);
    add_budget_type(rig.registry, "test.huge", INT32_MAX);               /* declares two billion buffers of 256 KiB */
    rig_node(&rig, 1, "test.huge");
    rig_node(&rig, 2, "test.huge");
    rig_node(&rig, 3, "test.huge");
    rig_connect(&rig, 1, "out", 2, "a");
    rig_connect(&rig, 2, "out", 3, "a");
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK(canopy_engine_new_instance(rig.engine) == NULL);              /* about 1.7e15 bytes cannot be had */
    rig_close(&rig);                                                     /* and nothing was left counted as an instance */
}

/* ---- canopy_scratch ---- */

/* a node that takes scratch buffers as told by `taker`, writes a pattern into each, and checks that no buffer disturbed another */
#define MAX_TAKES 8
static struct {
    int ntake;
    int64_t sizes[MAX_TAKES];
    float *got[MAX_TAKES];
    float *extra;                    /* the result of one more request of 1 float after all the others */
    int intact;
    int calls;
} taker;

static void taker_run(CanopyCtx *ctx)
{
    int i;
    int64_t k;
    taker.calls++;
    taker.intact = 1;
    for (i = 0; i < taker.ntake; i++) {
        taker.got[i] = canopy_scratch(ctx, taker.sizes[i]);
        if (taker.got[i])
            for (k = 0; k < taker.sizes[i]; k++) taker.got[i][k] = (float)(i + 1);
    }
    taker.extra = canopy_scratch(ctx, 1);
    for (i = 0; i < taker.ntake; i++)
        if (taker.got[i])
            for (k = 0; k < taker.sizes[i]; k++)
                if (taker.got[i][k] != (float)(i + 1)) taker.intact = 0;
}

static int32_t taker_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    (void)outlet; (void)t;
    taker_run(ctx);
    { *out = 1.0f; return CANOPY_OK; }
}

static int32_t taker_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    (void)outlet;
    taker_run(ctx);
    return canopy_inlet_span(ctx, 0, t0, t1, n, out);            /* the upstream node runs while this one still holds its buffers */
}

static void add_taker_types(CanopyRegistry *registry)
{
    static const char *const keys[] = {"test.taker0", "test.taker1", "test.taker2", "test.taker3"};
    int32_t budget;
    for (budget = 0; budget < 4; budget++) {
        CanopyNodeType type = support_base_type(keys[budget], keys[budget]);
        type.n_inlets = 1; type.inlets = IN_ONE; type.n_outlets = 1; type.outlets = OUT_ONE;
        type.scratch_buffers = budget;
        type.handlers.query_at = taker_at; type.handlers.query_span = taker_span;
        support_add_type(registry, &type);
    }
}

static void reset_taker(void)
{
    memset(&taker, 0, sizeof taker);
}

/* node 1 = the taker type `key`, node 2 = a sink reading it */
static void taker_rig(Rig *rig, const char *key)
{
    rig_open(rig);
    add_taker_types(rig->registry);
    rig_node(rig, 1, key);
    rig_node(rig, 2, "test.sink");
    rig_connect(rig, 1, "out", 2, "in0");
    rig_install(rig);
    reset_taker();
}

static void take(Rig *rig)                                      /* runs the taker once, as a span query */
{
    Guarded g = guarded_new(4);
    CHECK_INT(canopy_instance_inlet_span(rig->instance, 2, 0, 0, 100, 4, g.data), CANOPY_OK);
    CHECK(guarded_guards_intact(&g));
    guarded_free(&g);
}

static void test_c_scratch_buffers_are_disjoint_aligned_and_limited_to_the_declared_count(void)
{
    Rig rig;
    taker_rig(&rig, "test.taker2");
    taker.ntake = 2;
    taker.sizes[0] = CANOPY_MAX_N;
    taker.sizes[1] = CANOPY_MAX_N;
    take(&rig);
    CHECK_INT(taker.calls, 1);
    CHECK(taker.got[0] != NULL && taker.got[1] != NULL);
    CHECK(taker.intact);                                              /* writing one whole buffer did not touch the other */
    CHECK(taker.extra == NULL);                                       /* a third buffer is over the declared count */
    if (taker.got[0] && taker.got[1]) {
        CHECK_INT(((uintptr_t)taker.got[0]) % 64, 0);
        CHECK_INT(((uintptr_t)taker.got[1]) % 64, 0);
        CHECK(taker.got[1] == taker.got[0] + CANOPY_MAX_N);           /* handed out one after the other */
    }
    CHECK_INT(canopy_instance_arena_floats(rig.instance), 2LL * CANOPY_MAX_N);
    CHECK_HEAP();
    rig_close(&rig);
}

static void test_c_small_buffers_are_rounded_up_to_whole_cache_lines_and_stay_apart(void)
{
    Rig rig;
    taker_rig(&rig, "test.taker3");
    taker.ntake = 3;
    taker.sizes[0] = 1; taker.sizes[1] = 17; taker.sizes[2] = 16;
    take(&rig);
    CHECK(taker.got[0] && taker.got[1] && taker.got[2] && taker.intact);
    if (taker.got[0] && taker.got[1] && taker.got[2]) {
        CHECK_INT(taker.got[1] - taker.got[0], 16);                   /* 1 float uses 16 (64 bytes)... */
        CHECK_INT(taker.got[2] - taker.got[1], 32);                   /* ...17 floats use 32 */
        CHECK_INT(((uintptr_t)taker.got[2]) % 64, 0);
    }
    rig_close(&rig);
}

static void test_c_a_request_that_cannot_be_met_returns_null_and_does_not_use_up_the_declared_count(void)
{
    Rig rig;
    taker_rig(&rig, "test.taker2");
    taker.ntake = 6;
    taker.sizes[0] = 0;                       /* nothing to give */
    taker.sizes[1] = CANOPY_MAX_N + 1;        /* more than the largest n */
    taker.sizes[2] = -1;
    taker.sizes[3] = INT64_MIN;
    taker.sizes[4] = 10;                      /* these two are fine... */
    taker.sizes[5] = 10;
    take(&rig);
    CHECK(taker.got[0] == NULL && taker.got[1] == NULL && taker.got[2] == NULL && taker.got[3] == NULL);
    CHECK(taker.got[4] != NULL && taker.got[5] != NULL);              /* ...because the failed requests did not count */
    CHECK(taker.extra == NULL);
    CHECK(taker.intact);
    reset_taker();
    taker.ntake = 1;
    taker.sizes[0] = INT64_MAX;
    take(&rig);
    CHECK(taker.got[0] == NULL);
    rig_close(&rig);
}

static void test_c_a_node_that_declared_no_buffers_gets_none(void)
{
    Rig rig;
    taker_rig(&rig, "test.taker0");
    taker.ntake = 1;
    taker.sizes[0] = 10;
    take(&rig);
    CHECK(taker.got[0] == NULL && taker.extra == NULL);
    CHECK_INT(canopy_instance_arena_floats(rig.instance), 0);
    rig_close(&rig);
}

static void test_c_buffers_are_released_when_the_handler_returns(void)
{
    Rig rig;
    float *first;
    taker_rig(&rig, "test.taker1");
    taker.ntake = 1;
    taker.sizes[0] = CANOPY_MAX_N;
    take(&rig);
    first = taker.got[0];
    CHECK(first != NULL);
    take(&rig);
    CHECK(taker.got[0] == first);                                     /* the same buffer again: the arena was emptied on return */
    CHECK(host_inlet_at(rig.instance, 2, 0, 0) == 1.0f);   /* also after a point query (a different handler) */
    CHECK(taker.got[0] == first);
    take(&rig);
    CHECK(taker.got[0] == first && taker.calls == 4);
    rig_close(&rig);
}

static void test_c_two_instances_have_arenas_of_their_own(void)
{
    Rig rig;
    CanopyInstance *second;
    Guarded g = guarded_new(4);
    float *from_first;
    taker_rig(&rig, "test.taker1");
    taker.ntake = 1;
    taker.sizes[0] = 100;
    take(&rig);
    from_first = taker.got[0];
    second = canopy_engine_new_instance(rig.engine);
    CHECK(second != NULL);
    if (second) {
        CHECK_INT(canopy_instance_inlet_span(second, 2, 0, 0, 100, 4, g.data), CANOPY_OK);
        CHECK(taker.got[0] != NULL && taker.got[0] != from_first);
        CHECK_INT(canopy_instance_arena_floats(second), canopy_instance_arena_floats(rig.instance));
        canopy_instance_free(second);
    }
    guarded_free(&g);
    rig_close(&rig);
}

/* a node that takes 100 floats, holds them while its upstream runs, and checks them afterwards: buffers of nodes that ask each other
   in a chain must not overlap */
static struct {
    int depth;
    float *ptr[8];
    int intact[8];
    int64_t size;
} chain;

static int32_t chain_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    int d = chain.depth++;
    float *mine = canopy_scratch(ctx, chain.size);
    int64_t k;
    int32_t status;
    (void)outlet;
    chain.ptr[d] = mine;
    if (mine)
        for (k = 0; k < chain.size; k++) mine[k] = (float)(d + 1);
    status = canopy_inlet_span(ctx, 0, t0, t1, n, out);
    chain.intact[d] = mine != NULL;
    if (mine)
        for (k = 0; k < chain.size; k++)
            if (mine[k] != (float)(d + 1)) chain.intact[d] = 0;
    return status;
}

static void add_chain_type(CanopyRegistry *registry)
{
    CanopyNodeType type = support_base_type("test.chain", "Chain");
    type.n_inlets = 1; type.inlets = IN_ONE; type.n_outlets = 1; type.outlets = OUT_ONE;
    type.scratch_buffers = 1;
    type.handlers.query_span = chain_span;
    support_add_type(registry, &type);
}

static void test_c_the_buffers_of_nodes_that_ask_each_other_do_not_overlap(void)
{
    Rig rig;
    Guarded g = guarded_new(4);
    int d;
    rig_open(&rig);
    add_chain_type(rig.registry);
    rig_node(&rig, 1, "test.chain");
    rig_node(&rig, 2, "test.chain");
    rig_node(&rig, 3, "test.chain");
    rig_node(&rig, 4, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 3, "in");
    rig_connect(&rig, 3, "out", 4, "in0");
    rig_install(&rig);
    memset(&chain, 0, sizeof chain);
    chain.size = 100;
    CHECK_INT(arena_buffers(&rig), 3);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 4, 0, 0, 100, 4, g.data), CANOPY_OK);
    CHECK_INT(chain.depth, 3);
    for (d = 0; d < 3; d++) CHECK(chain.ptr[d] != NULL && chain.intact[d]);
    CHECK(chain.ptr[1] == chain.ptr[0] + 112 && chain.ptr[2] == chain.ptr[1] + 112);       /* 100 floats rounded up to 112 */
    guarded_free(&g);
    rig_close(&rig);
}

static void test_c_a_node_that_asks_for_more_than_it_declared_cannot_starve_the_node_upstream(void)
{
    Rig rig;
    Guarded g = guarded_new(4);
    rig_open(&rig);
    add_taker_types(rig.registry);
    add_chain_type(rig.registry);
    rig_node(&rig, 1, "test.taker1");                  /* declares one buffer but tries to take three of the largest size */
    rig_node(&rig, 2, "test.chain");                   /* its upstream node, which needs its own */
    rig_node(&rig, 3, "test.sink");
    rig_connect(&rig, 2, "out", 1, "in");
    rig_connect(&rig, 1, "out", 3, "in0");
    rig_install(&rig);
    reset_taker();
    memset(&chain, 0, sizeof chain);
    chain.size = CANOPY_MAX_N;
    taker.ntake = 3;
    taker.sizes[0] = taker.sizes[1] = taker.sizes[2] = CANOPY_MAX_N;
    CHECK_INT(arena_buffers(&rig), 2);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 3, 0, 0, 100, 4, g.data), CANOPY_OK);
    CHECK(taker.got[0] != NULL && taker.got[1] == NULL && taker.got[2] == NULL);
    CHECK(chain.ptr[0] != NULL && chain.intact[0]);                      /* the upstream node still got its buffer */
    guarded_free(&g);
    rig_close(&rig);
}

/* a pointwise node that takes scratch in its point handler: the engine calls that handler once per sample of a derived span, and the
   buffer is released after each call */
static float *point_seen[64];
static int point_calls;

static int32_t point_taker_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    float *p = canopy_scratch(ctx, 8);
    (void)outlet; (void)t;
    if (point_calls < 64) point_seen[point_calls] = p;
    point_calls++;
    if (p) {
        int k;
        for (k = 0; k < 8; k++) p[k] = 1.0f;
    }
    { *out = p ? 1.0f : -1.0f; return CANOPY_OK; }
}

static void test_c_a_pointwise_nodes_derived_span_gets_its_buffer_afresh_for_every_sample(void)
{
    Rig rig;
    CanopyNodeType type = support_base_type("test.point_taker", "Point taker");
    Guarded g = guarded_new(10);
    int i;
    type.n_outlets = 1; type.outlets = OUT_ONE; type.scratch_buffers = 1;
    type.handlers.query_at = point_taker_at;
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.point_taker");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    point_calls = 0;
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, 0, 0, 100, 10, g.data), CANOPY_OK);
    CHECK_INT(point_calls, 10);
    for (i = 0; i < 10; i++) {
        CHECK(point_seen[i] != NULL && point_seen[i] == point_seen[0]);   /* released after each call, so always the same place */
        CHECK(g.data[i] == 1.0f);
    }
    guarded_free(&g);
    rig_close(&rig);
}

/* two nodes in a loop, asking each other until scratch runs out: a loop gets a finite arena and NULL, not a crash */
static struct {
    int takes, nulls;
} loop;

static int32_t loopy_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    int32_t wanted;
    int32_t i;
    (void)outlet;
    wanted = (int32_t)canopy_ctx_int(ctx, 0);                           /* how many buffers this node takes (its setting) */
    for (i = 0; i < wanted; i++) {
        if (!canopy_scratch(ctx, CANOPY_MAX_N)) {
            loop.nulls++;
            { *out = 0.0f; return CANOPY_OK; }
        }
        loop.takes++;
    }
    { *out = 1.0f + inlet_value(ctx, 0, t - 1); return CANOPY_OK; }
}

static void test_c_a_loop_that_keeps_taking_buffers_meets_null_when_the_arena_is_used_up(void)
{
    Rig rig;
    static const CanopySettingDesc TAKES[] = {{"takes", CANOPY_SETTING_INT, 1, 0.0, NULL, 0, NULL}};
    CanopyNodeType one = support_base_type("test.loopy1", "Loopy 1"), two = support_base_type("test.loopy2", "Loopy 2");
    rig_open(&rig);
    one.n_inlets = 1; one.inlets = IN_ONE; one.n_outlets = 1; one.outlets = OUT_ONE; one.scratch_buffers = 1;
    one.n_settings = 1; one.settings = TAKES; one.handlers.query_at = loopy_at;
    two = one;
    two.key = "test.loopy2"; two.name = "Loopy 2"; two.scratch_buffers = 2;
    support_add_type(rig.registry, &one);
    support_add_type(rig.registry, &two);
    rig_node(&rig, 1, "test.loopy1");
    rig_node(&rig, 2, "test.loopy2");
    rig_node(&rig, 3, "test.sink");
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "takes", 2), CANOPY_OK);
    rig_connect(&rig, 2, "out", 1, "in");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 1, "out", 3, "in0");
    rig_install(&rig);
    CHECK_INT(arena_buffers(&rig), 3);                                  /* 1 + 2: the sum over the nodes, as there is a loop */
    memset(&loop, 0, sizeof loop);
    /* sink asks node 1 (takes 1), which asks node 2 (takes 2), which asks node 1 again: no buffer left, so it stops there */
    CHECK(host_inlet_at(rig.instance, 3, 0, 0) == 2.0f);
    CHECK_INT(loop.takes, 3);
    CHECK_INT(loop.nulls, 1);
    CHECK_HEAP();
    rig_close(&rig);
}

void register_test_scratch(void)
{
    RUN(test_c_the_arena_is_sized_for_the_deepest_chain_of_declared_buffers);
    RUN(test_c_in_a_diamond_the_heavier_branch_decides);
    RUN(test_c_separate_parts_of_a_graph_do_not_add_up);
    RUN(test_c_a_source_feeding_two_inlets_of_one_node_is_counted_once);
    RUN(test_c_a_graph_whose_nodes_declare_no_buffers_has_no_arena_and_still_works);
    RUN(test_c_with_a_loop_anywhere_the_arena_is_sized_for_every_node_holding_its_buffers_at_once);
    RUN(test_c_the_arena_size_refuses_a_buffer_count_whose_byte_size_would_not_fit);
    RUN(test_c_an_arena_too_big_to_allocate_gives_no_instance_instead_of_a_crash);
    RUN(test_c_scratch_buffers_are_disjoint_aligned_and_limited_to_the_declared_count);
    RUN(test_c_small_buffers_are_rounded_up_to_whole_cache_lines_and_stay_apart);
    RUN(test_c_a_request_that_cannot_be_met_returns_null_and_does_not_use_up_the_declared_count);
    RUN(test_c_a_node_that_declared_no_buffers_gets_none);
    RUN(test_c_buffers_are_released_when_the_handler_returns);
    RUN(test_c_two_instances_have_arenas_of_their_own);
    RUN(test_c_the_buffers_of_nodes_that_ask_each_other_do_not_overlap);
    RUN(test_c_a_node_that_asks_for_more_than_it_declared_cannot_starve_the_node_upstream);
    RUN(test_c_a_pointwise_nodes_derived_span_gets_its_buffer_afresh_for_every_sample);
    RUN(test_c_a_loop_that_keeps_taking_buffers_meets_null_when_the_arena_is_used_up);
}
