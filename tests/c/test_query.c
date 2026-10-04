/* Tests: point and span queries through the engine (docs/canopy_design.md sections 5 and 6): knob fallback, sample placement, pointwise nodes,
   span-only nodes, error statuses and zero-fill, lookahead, fan-out, determinism, the ownership of `out`. */
#include <stdlib.h>
#include <string.h>
#include "support.h"

static void fill_floats(float *out, int64_t n, float value)
{
    int64_t i;
    for (i = 0; i < n; i++) out[i] = value;
}

/* node 1 = test.time, node 2 = test.sink; time.a -> sink.in0 and time.b -> sink.in1 */
static void time_to_sink(Rig *rig)
{
    rig_open(rig);
    rig_node(rig, 1, "test.time");
    rig_node(rig, 2, "test.sink");
    rig_connect(rig, 1, "a", 2, "in0");
    rig_connect(rig, 1, "b", 2, "in1");
    rig_install(rig);
}

/* queries sink 2 and reports whether the span query returned `expected_status`, kept the guards and wrote what it should */
static int32_t host_span(Rig *rig, int32_t inlet, int64_t t0, int64_t t1, int64_t n, Guarded *g)
{
    int32_t status = canopy_instance_inlet_span(rig->instance, 2, inlet, t0, t1, n, g->data);
    CHECK(guarded_guards_intact(g));
    return status;
}

/* ---- the knob fallback (design section 6) ---- */

static void test_c_an_unconnected_inlet_answers_with_its_knob_for_points_and_spans_whatever_the_times(void)
{
    Rig rig;
    static const int64_t times[] = {0, 5, -5, INT64_MAX, INT64_MIN};
    static const int64_t counts[] = {1, 2, 7, 4096, CANOPY_MAX_N};
    size_t i, c;
    rig_open(&rig);
    rig_node(&rig, 1, "test.sink");                                        /* in0 starts at 0.0, in1 at 0.5 (their declared defaults) */
    rig_install(&rig);
    for (i = 0; i < sizeof times / sizeof times[0]; i++) {
        CHECK(host_inlet_at(rig.instance, 1, 0, times[i]) == 0.0f);
        CHECK(host_inlet_at(rig.instance, 1, 1, times[i]) == 0.5f);
    }
    for (c = 0; c < sizeof counts / sizeof counts[0]; c++) {
        Guarded g = guarded_new(counts[c]);
        Guarded expected = guarded_new(counts[c]);
        fill_floats(expected.data, counts[c], 0.5f);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 1, 1, 0, 100, counts[c], g.data), CANOPY_OK);
        CHECK(guarded_bits_equal(&g, &expected) && guarded_guards_intact(&g));
        fill_floats(g.data, counts[c], -7.0f);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 1, 1, 100, 0, counts[c], g.data), CANOPY_OK);          /* reversed */
        CHECK(guarded_bits_equal(&g, &expected));
        fill_floats(g.data, counts[c], -7.0f);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 1, 1, 5, 5, counts[c], g.data), CANOPY_OK);            /* t1 == t0 */
        CHECK(guarded_bits_equal(&g, &expected));
        fill_floats(g.data, counts[c], -7.0f);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 1, 1, INT64_MIN, INT64_MAX - 1, counts[c], g.data), CANOPY_ERR_OVERFLOW);
        CHECK(guarded_all_zero(&g));
        guarded_free(&g);
        guarded_free(&expected);
    }
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 1, -0.25f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, 0.125f), CANOPY_OK);
    CHECK(host_inlet_at(rig.instance, 1, 1, 99) == -0.25f);          /* a knob move takes effect on the next query */
    CHECK(host_inlet_at(rig.instance, 1, 0, 99) == 0.125f);
    {
        Guarded g = guarded_new(3);
        const float expected[3] = {-0.25f, -0.25f, -0.25f};
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 1, 1, 0, 9, 3, g.data), CANOPY_OK);
        CHECK(guarded_equals(&g, expected));
        guarded_free(&g);
    }
    rig_close(&rig);
}

static void test_c_a_connected_inlet_gets_the_outlets_answer_and_ignores_its_own_knob(void)
{
    Rig rig;
    Guarded g = guarded_new(5);
    const float expected[5] = {3.5f, 3.5f, 3.5f, 3.5f, 3.5f};
    rig_open(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 3.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(rig.graph, 2, "in0", 0.9f), CANOPY_OK);
    rig_install(&rig);
    CHECK(host_inlet_at(rig.instance, 2, 0, 12345) == 3.5f);
    CHECK_INT(host_span(&rig, 0, 0, 40, 5, &g), CANOPY_OK);
    CHECK(guarded_equals(&g, expected));
    CHECK(host_inlet_at(rig.instance, 2, 1, 1) == 0.5f);               /* the unconnected neighbour still answers its knob */
    guarded_free(&g);
    rig_close(&rig);
}

/* ---- sample placement (design section 5) ---- */

typedef struct {
    int64_t t0, t1, n;
    float expected[10];
} Placement;

static const Placement PLACEMENTS[] = {
    {0, 100, 4, {0, 25, 50, 75}},
    {0, 10, 3, {0, 3, 6}},
    {-5, 0, 2, {-5, -3}},
    {100, 0, 4, {100, 75, 50, 25}},
    {0, -5, 2, {0, -3}},
    {5, 0, 3, {5, 3, 1}},
    {42, 42, 5, {42, 42, 42, 42, 42}},
    {7, 9, 1, {7}},
    {0, 3, 8, {0, 0, 0, 1, 1, 1, 2, 2}},
    {-1, 1, 8, {-1, -1, -1, -1, 0, 0, 0, 0}},
};

static void test_c_span_samples_are_placed_by_the_formula_including_reversed_and_empty_spans(void)
{
    Rig rig;
    size_t p;
    time_to_sink(&rig);
    for (p = 0; p < sizeof PLACEMENTS / sizeof PLACEMENTS[0]; p++) {
        const Placement *pl = &PLACEMENTS[p];
        Guarded a = guarded_new(pl->n), b = guarded_new(pl->n);
        float doubled[10];
        int64_t i;
        CHECK_INT(host_span(&rig, 0, pl->t0, pl->t1, pl->n, &a), CANOPY_OK);
        if (!guarded_equals(&a, pl->expected)) {
            ctest_current_failed = 1;
            printf("    placement %zu (t0=%lld t1=%lld n=%lld): wrong samples\n", p, (long long)pl->t0, (long long)pl->t1, (long long)pl->n);
        }
        for (i = 0; i < pl->n; i++) doubled[i] = 2.0f * pl->expected[i];
        CHECK_INT(host_span(&rig, 1, pl->t0, pl->t1, pl->n, &b), CANOPY_OK);      /* the second outlet answers 2t */
        CHECK(guarded_equals(&b, doubled));
        guarded_free(&a);
        guarded_free(&b);
    }
    rig_close(&rig);
}

static void test_c_point_queries_reach_the_node_and_the_right_outlet(void)
{
    Rig rig;
    time_to_sink(&rig);
    CHECK(host_inlet_at(rig.instance, 2, 0, 10) == 10.0f);
    CHECK(host_inlet_at(rig.instance, 2, 1, 10) == 20.0f);
    CHECK(host_inlet_at(rig.instance, 2, 0, -7) == -7.0f);
    CHECK(host_inlet_at(rig.instance, 2, 1, -7) == -14.0f);
    rig_close(&rig);
}

/* ---- pointwise and span-only nodes ---- */

/* a host span query on sink 2 reaches the recorder; checks the recorder was called exactly once per sample time */
static void check_one_point_call_per_sample(Rig *rig, int64_t t0, int64_t t1, int64_t n)
{
    Guarded g = guarded_new(n);
    int64_t i, wrong = 0;
    support_calls_reset();
    CHECK_INT(canopy_instance_inlet_span(rig->instance, 2, 0, t0, t1, n, g.data), CANOPY_OK);
    CHECK(guarded_guards_intact(&g));
    CHECK_INT(guarded_unwritten(&g), 0);
    CHECK_INT(support_ncalls, n);
    if (support_ncalls == n) {
        for (i = 0; i < n; i++) {
            int64_t expected;
            CHECK_INT(canopy_sample_time(t0, t1, n, i, &expected), CANOPY_OK);
            if (support_calls[i].is_span || support_calls[i].t0 != expected) wrong++;
        }
    }
    if (wrong) {
        ctest_current_failed = 1;
        printf("    %lld of %lld point calls were at the wrong time or were span calls (t0=%lld t1=%lld)\n", (long long)wrong, (long long)n,
               (long long)t0, (long long)t1);
    }
    guarded_free(&g);
}

static void test_c_the_span_of_a_pointwise_node_is_one_point_query_per_sample_time(void)
{
    Rig rig;
    rig_open(&rig);
    rig_node(&rig, 1, "test.recorder");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    check_one_point_call_per_sample(&rig, 0, 100, 4);
    check_one_point_call_per_sample(&rig, 100, 0, 4);
    check_one_point_call_per_sample(&rig, 42, 42, 5);
    check_one_point_call_per_sample(&rig, -1000003, 77777, 1000);
    check_one_point_call_per_sample(&rig, 1, 1, 1);
    check_one_point_call_per_sample(&rig, 0, INT64_MAX, CANOPY_MAX_N);              /* the largest span and the largest n */
    check_one_point_call_per_sample(&rig, INT64_MAX, 0, CANOPY_MAX_N);
    check_one_point_call_per_sample(&rig, 0, INT64_MIN, CANOPY_MAX_N);
    check_one_point_call_per_sample(&rig, -1, INT64_MAX - 1, 4097);
    support_calls_reset();
    CHECK(host_inlet_at(rig.instance, 2, 0, 77) == 0.5f);                /* a point query is one point call, not a span */
    CHECK_INT(support_ncalls, 1);
    CHECK(support_calls[0].is_span == 0 && support_calls[0].t0 == 77);
    rig_close(&rig);
}

static void test_c_a_span_only_node_gets_the_span_and_answers_a_point_query_with_a_one_sample_span(void)
{
    Rig rig;
    Guarded g = guarded_new(4);
    const float expected[4] = {0.25f, 0.25f, 0.25f, 0.25f};
    rig_open(&rig);
    rig_node(&rig, 1, "test.recorder_span");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    support_calls_reset();
    CHECK_INT(host_span(&rig, 0, 0, 100, 4, &g), CANOPY_OK);
    CHECK(guarded_equals(&g, expected));
    CHECK_INT(support_ncalls, 1);
    CHECK(support_calls[0].is_span && support_calls[0].t0 == 0 && support_calls[0].t1 == 100 && support_calls[0].n == 4);
    support_calls_reset();
    CHECK(host_inlet_at(rig.instance, 2, 0, 77) == 0.25f);
    CHECK_INT(support_ncalls, 1);
    CHECK(support_calls[0].is_span && support_calls[0].t0 == 77 && support_calls[0].t1 == 77 && support_calls[0].n == 1);
    guarded_free(&g);
    rig_close(&rig);
}

static void test_c_a_span_only_node_that_fails_reports_its_status_for_a_point_query_and_the_answer_is_zero(void)
{
    Rig rig;
    float value = 9.0f;
    rig_open(&rig);
    rig_node(&rig, 1, "test.failing_span_only");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 5, &value), FAILING_STATUS);     /* the node scribbled 123 and returned a status */
    CHECK(value == 0.0f);
    rig_close(&rig);
}

static void test_c_a_point_query_reports_statuses_like_a_span_query_and_the_answer_is_zero_when_it_fails(void)
{
    Rig rig;
    float value = 9.0f;
    rig_open(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.sink");
    rig_node(&rig, 3, "test.failing");
    rig_node(&rig, 4, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_connect(&rig, 3, "out", 4, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.375), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 7, &value), CANOPY_OK);          /* a connected inlet */
    CHECK(value == 0.375f);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 1, 7, &value), CANOPY_OK);          /* an unconnected one: its knob (0.5 by default) */
    CHECK(value == 0.5f);
    value = 9.0f;
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 4, 0, 7, &value), FAILING_STATUS);     /* the node wrote 5.0 and failed: the status, and zero */
    CHECK(value == 0.0f);
    value = 9.0f;
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 99, 7, &value), CANOPY_ERR_PORT);
    CHECK(value == 0.0f);
    value = 9.0f;
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, -1, 7, &value), CANOPY_ERR_PORT);
    CHECK(value == 0.0f);
    value = 9.0f;
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 77, 0, 7, &value), CANOPY_ERR_NODE);   /* no such node */
    CHECK(value == 0.0f);
    value = 9.0f;
    CHECK_INT(canopy_instance_inlet_at(NULL, 2, 0, 7, &value), CANOPY_ERR_ARGUMENT);
    CHECK(value == 0.0f);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 7, NULL), CANOPY_ERR_ARGUMENT);
    rig_close(&rig);
}

/* ---- bad arguments ---- */

static void test_c_bad_span_arguments_from_the_host_give_the_documented_status_and_zero_fill_when_n_is_valid(void)
{
    Rig rig;
    Guarded g = guarded_new(8);
    static const int64_t bad_n[] = {0, -1, CANOPY_MAX_N + 1, INT64_MIN, INT64_MAX, 1000000};
    size_t i;
    int32_t inlet;
    time_to_sink(&rig);
    for (inlet = 0; inlet < 2; inlet++) {
        guarded_reset(&g);
        for (i = 0; i < sizeof bad_n / sizeof bad_n[0]; i++) {
            CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 0, 100, bad_n[i], g.data), CANOPY_ERR_N);
            CHECK_INT(guarded_unwritten(&g), 8);                                    /* the buffer's size is unknown, so it is not touched */
            CHECK(guarded_guards_intact(&g));
        }
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 0, 100, 4, NULL), CANOPY_ERR_ARGUMENT);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 0, 100, 0, NULL), CANOPY_ERR_N);       /* n is checked first */
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, -2, INT64_MAX, 4, g.data), CANOPY_ERR_OVERFLOW);
        CHECK(guarded_unwritten(&g) == 4 && g.data[0] == 0.0f && g.data[3] == 0.0f);   /* the first n = 4 floats were zero-filled, no more */
        fill_floats(g.data, 8, -1.0f);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 2, INT64_MIN, 8, g.data), CANOPY_ERR_OVERFLOW);
        CHECK(guarded_all_zero(&g) && guarded_guards_intact(&g));
        fill_floats(g.data, 8, -1.0f);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 0, INT64_MAX, 8, g.data), CANOPY_OK);      /* the widest legal spans */
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 0, INT64_MIN, 8, g.data), CANOPY_OK);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, -1, INT64_MAX - 1, 8, g.data), CANOPY_OK);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, inlet, 0, 100, 8, g.data), CANOPY_OK);
        CHECK(guarded_guards_intact(&g));
    }
    /* an unknown node or inlet is an error too, with the buffer zero-filled; overflow is reported before the address is looked at */
    fill_floats(g.data, 8, -1.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 99, 0, 0, 100, 8, g.data), CANOPY_ERR_NODE);
    CHECK(guarded_all_zero(&g));
    fill_floats(g.data, 8, -1.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, 2, 0, 100, 8, g.data), CANOPY_ERR_PORT);
    CHECK(guarded_all_zero(&g));
    fill_floats(g.data, 8, -1.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, -1, 0, 100, 8, g.data), CANOPY_ERR_PORT);
    CHECK(guarded_all_zero(&g));
    fill_floats(g.data, 8, -1.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 99, 0, -2, INT64_MAX, 8, g.data), CANOPY_ERR_OVERFLOW);
    CHECK(guarded_all_zero(&g) && guarded_guards_intact(&g));
    /* point queries cannot report an error: they return 0.0 */
    CHECK(host_inlet_at(rig.instance, 99, 0, 5) == 0.0f);
    CHECK(host_inlet_at(rig.instance, 2, 2, 5) == 0.0f);
    CHECK(host_inlet_at(rig.instance, 2, -1, 5) == 0.0f);
    guarded_free(&g);
    rig_close(&rig);
}

static void test_c_the_largest_n_works_through_every_kind_of_source(void)
{
    Rig rig;
    static const int64_t counts[] = {1, 2, 3, 34, 100, 4096, CANOPY_MAX_N - 1, CANOPY_MAX_N};
    size_t c;
    int32_t sink, inlet;
    rig_open(&rig);
    rig_node(&rig, 1, "test.time");
    rig_node(&rig, 2, "test.const_span");
    rig_node(&rig, 3, "test.gain");
    rig_node(&rig, 4, "test.sum");
    rig_node(&rig, 5, "test.shift");
    rig_node(&rig, 10, "test.sink");
    rig_node(&rig, 11, "test.sink");
    rig_node(&rig, 12, "test.sink");
    rig_connect(&rig, 1, "a", 10, "in0");              /* pointwise */
    rig_connect(&rig, 2, "out", 10, "in1");            /* span only */
    rig_connect(&rig, 1, "a", 3, "in");                /* gain: both handlers, uses scratch */
    rig_connect(&rig, 3, "out", 11, "in0");
    rig_connect(&rig, 1, "a", 4, "a");                 /* sum: pointwise with two inputs, one of them a knob */
    rig_connect(&rig, 4, "out", 11, "in1");
    rig_connect(&rig, 1, "b", 5, "in");                /* shift: both handlers, passes the span on */
    rig_connect(&rig, 5, "out", 12, "in0");
    rig_install(&rig);                                 /* sink 12 in1 is unconnected: a knob */
    for (c = 0; c < sizeof counts / sizeof counts[0]; c++) {
        int64_t n = counts[c];
        for (sink = 10; sink <= 12; sink++)
            for (inlet = 0; inlet < 2; inlet++) {
                Guarded g = guarded_new(n);
                CHECK_INT(canopy_instance_inlet_span(rig.instance, sink, inlet, -1000, 123456, n, g.data), CANOPY_OK);
                CHECK(guarded_guards_intact(&g));
                CHECK_INT(guarded_unwritten(&g), 0);                                  /* every float was written */
                guarded_free(&g);
            }
    }
    {
        Guarded g = guarded_new(CANOPY_MAX_N);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 10, 0, 0, 65536000, CANOPY_MAX_N, g.data), CANOPY_OK);
        CHECK(g.data[0] == 0.0f && g.data[1] == 1000.0f && g.data[CANOPY_MAX_N - 1] == 65535000.0f);
        CHECK_HEAP();
        guarded_free(&g);
    }
    rig_close(&rig);
}

/* ---- the same checks inside a node, through the context ---- */

static struct {
    int32_t inlet;
    int64_t t, t0, t1, n;
    float *out;
    int32_t status, point_status;
    float point;
    int calls;
} probe;

static int32_t probe_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    (void)outlet; (void)t;
    probe.point = 9.0f;                                                       /* (to see that a failure sets it to zero) */
    probe.point_status = canopy_inlet_at(ctx, probe.inlet, probe.t, &probe.point);
    probe.calls++;
    { *out = 1.0f; return CANOPY_OK; }
}

static int32_t probe_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    (void)outlet; (void)t0; (void)t1;
    probe.status = canopy_inlet_span(ctx, probe.inlet, probe.t0, probe.t1, probe.n, probe.out);
    probe.calls++;
    fill_floats(out, n, 1.0f);
    return CANOPY_OK;
}

static const CanopyInletDesc PROBE_IN[] = {{"in", "In", 0.25f}};
static const CanopyOutletDesc PROBE_OUT[] = {{"out", "Out"}};

static CanopyNodeType probe_type(void)
{
    CanopyNodeType type = support_base_type("test.probe", "Probe");
    type.n_inlets = 1; type.inlets = PROBE_IN; type.n_outlets = 1; type.outlets = PROBE_OUT;
    type.handlers.query_at = probe_at; type.handlers.query_span = probe_span;
    return type;
}

/* node 2 is a probe whose inlet is connected to time.a, node 3 a probe whose inlet is a knob (0.25); sink 4 reads them */
static void probes(Rig *rig)
{
    CanopyNodeType type = probe_type();
    rig_open(rig);
    support_add_type(rig->registry, &type);
    rig_node(rig, 1, "test.time");
    rig_node(rig, 2, "test.probe");
    rig_node(rig, 3, "test.probe");
    rig_node(rig, 4, "test.sink");
    rig_connect(rig, 1, "a", 2, "in");
    rig_connect(rig, 2, "out", 4, "in0");
    rig_connect(rig, 3, "out", 4, "in1");
    rig_install(rig);
}

/* makes the probe at `sink_inlet` (0: connected, 1: knob) run the query described by `probe` */
static void run_probe_span(Rig *rig, int32_t sink_inlet)
{
    float trigger[1] = {0.0f};
    probe.status = -1000;
    probe.calls = 0;
    CHECK_INT(canopy_instance_inlet_span(rig->instance, 4, sink_inlet, 0, 1, 1, trigger), CANOPY_OK);
    CHECK_INT(probe.calls, 1);
}

static void test_c_a_node_gets_the_same_statuses_through_its_context_whether_or_not_the_inlet_is_connected(void)
{
    Rig rig;
    Guarded g = guarded_new(8);
    int32_t which;
    probes(&rig);
    for (which = 0; which < 2; which++) {                      /* 0: the inlet is connected to time.a, 1: it is a knob at 0.25 */
        guarded_reset(&g);
        probe.inlet = 0;
        probe.out = g.data;
        probe.t0 = 0; probe.t1 = 100; probe.n = 0;
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_ERR_N);
        CHECK_INT(guarded_unwritten(&g), 8);
        probe.n = CANOPY_MAX_N + 1;
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_ERR_N);
        probe.n = 4; probe.out = NULL;
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_ERR_ARGUMENT);
        probe.out = g.data; probe.t0 = -2; probe.t1 = INT64_MAX;
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_ERR_OVERFLOW);
        CHECK(g.data[0] == 0.0f && g.data[3] == 0.0f && guarded_unwritten(&g) == 4);
        probe.t0 = 0; probe.t1 = 100; probe.inlet = 1;         /* the probe node has only one inlet */
        fill_floats(g.data, 8, -1.0f);
        probe.n = 8;
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_ERR_PORT);
        CHECK(guarded_all_zero(&g));
        probe.inlet = -1;
        fill_floats(g.data, 8, -1.0f);
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_ERR_PORT);
        CHECK(guarded_all_zero(&g));
        probe.inlet = 0;                                       /* and the good case, for contrast */
        probe.n = 4;
        run_probe_span(&rig, which);
        CHECK_INT(probe.status, CANOPY_OK);
        if (which == 0) {
            CHECK(g.data[0] == 0.0f && g.data[1] == 25.0f && g.data[2] == 50.0f && g.data[3] == 75.0f);
        } else {
            CHECK(g.data[0] == 0.25f && g.data[3] == 0.25f);
        }
        CHECK(guarded_guards_intact(&g));
        /* point queries through the context: a bad inlet is CANOPY_ERR_PORT and reads 0.0, as for a span */
        probe.t = 40;
        probe.inlet = 5;
        CHECK(host_inlet_at(rig.instance, 4, which, 0) == 1.0f);
        CHECK_INT(probe.point_status, CANOPY_ERR_PORT);
        CHECK(probe.point == 0.0f);
        probe.inlet = -3;
        CHECK(host_inlet_at(rig.instance, 4, which, 0) == 1.0f);
        CHECK_INT(probe.point_status, CANOPY_ERR_PORT);
        CHECK(probe.point == 0.0f);
        probe.inlet = 0;
        CHECK(host_inlet_at(rig.instance, 4, which, 0) == 1.0f);
        CHECK_INT(probe.point_status, CANOPY_OK);
        CHECK(probe.point == (which == 0 ? 40.0f : 0.25f));
    }
    guarded_free(&g);
    rig_close(&rig);
}

/* ---- errors from nodes ---- */

static void test_c_a_status_from_a_node_is_passed_through_unchanged_and_the_engine_zero_fills_out(void)
{
    Rig rig;
    Guarded g = guarded_new(16);
    rig_open(&rig);
    rig_node(&rig, 1, "test.failing");
    rig_node(&rig, 2, "test.gain");
    rig_node(&rig, 3, "test.sink");
    rig_node(&rig, 4, "test.failing");
    rig_connect(&rig, 1, "out", 3, "in0");             /* sink <- failing */
    rig_connect(&rig, 1, "out", 2, "in");              /* gain <- failing, so sink.in1 <- gain <- failing */
    rig_connect(&rig, 2, "out", 3, "in1");
    rig_connect(&rig, 4, "out", 2, "gain");
    rig_install(&rig);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 3, 0, 0, 100, 16, g.data), FAILING_STATUS);
    CHECK(guarded_all_zero(&g));                       /* the node wrote 123.0 before failing; the engine replaced it */
    fill_floats(g.data, 16, -1.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 3, 1, 0, 100, 16, g.data), FAILING_STATUS);
    CHECK(guarded_all_zero(&g));                       /* passed on through the gain node's context call */
    CHECK(guarded_guards_intact(&g));
    {
        float value = 9.0f;
        CHECK_INT(canopy_instance_inlet_at(rig.instance, 3, 0, 1, &value), FAILING_STATUS);     /* a point query fails with the same status... */
        CHECK(value == 0.0f);                                                                   /* ...and the 5.0 the node wrote is replaced by zero */
    }
    guarded_free(&g);
    rig_close(&rig);
}

static struct { int64_t fail_from; int calls; } pointwise;

static int32_t pointwise_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    (void)ctx; (void)outlet;
    pointwise.calls++;
    *out = (float)t + 1000.0f;                                       /* a value that must not survive a failure */
    return t >= pointwise.fail_from ? FAILING_STATUS : CANOPY_OK;
}

static void test_c_a_pointwise_node_whose_point_query_fails_fails_the_derived_span_at_the_first_failure_and_it_is_zero_filled(void)
{
    Rig rig;
    CanopyNodeType type = support_base_type("test.pointwise", "Pointwise");
    Guarded g = guarded_new(10);
    float value = 9.0f;
    int i;
    type.n_outlets = 1; type.outlets = PROBE_OUT;
    type.handlers.query_at = pointwise_at;                          /* no span handler: the engine asks once per sample time */
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.pointwise");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    pointwise.fail_from = 1000;                                      /* never fails: the span is 0, 10, ... 90 (plus 1000) */
    pointwise.calls = 0;
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, 0, 0, 100, 10, g.data), CANOPY_OK);
    CHECK(pointwise.calls == 10);
    for (i = 0; i < 10; i++) CHECK(g.data[i] == 1000.0f + 10.0f * (float)i);
    pointwise.fail_from = 50;                                        /* the sixth sample (t = 50) fails */
    pointwise.calls = 0;
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, 0, 0, 100, 10, g.data), FAILING_STATUS);
    CHECK(pointwise.calls == 6);                                     /* it stopped at the first failure */
    CHECK(guarded_all_zero(&g));                                     /* and the five good samples it had written are zero too */
    CHECK(guarded_guards_intact(&g));
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 49, &value), CANOPY_OK);
    CHECK(value == 1049.0f);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 50, &value), FAILING_STATUS);
    CHECK(value == 0.0f);
    guarded_free(&g);
    rig_close(&rig);
}

/* ---- lookahead (design section 5) ---- */

static void test_c_a_node_may_query_later_or_earlier_times_than_it_was_asked(void)
{
    Rig rig;
    Guarded g = guarded_new(4);
    const float ahead[4] = {1000.0f, 1025.0f, 1050.0f, 1075.0f};
    const float behind_reversed[4] = {-400.0f, -425.0f, -450.0f, -475.0f};      /* span (100, 0) shifted by -500 */
    const float chained[4] = {1020.0f, 1045.0f, 1070.0f, 1095.0f};
    rig_open(&rig);
    rig_node(&rig, 1, "test.time");
    rig_node(&rig, 2, "test.shift");
    rig_node(&rig, 3, "test.sink");
    rig_node(&rig, 4, "test.shift");
    rig_node(&rig, 5, "test.shift");
    rig_node(&rig, 6, "test.sink");
    rig_connect(&rig, 1, "a", 2, "in");
    rig_connect(&rig, 2, "out", 3, "in0");
    rig_connect(&rig, 2, "out", 4, "in");             /* 4 shifts the output of 2 again: shifts add up */
    rig_connect(&rig, 4, "out", 6, "in0");
    rig_connect(&rig, 1, "a", 5, "in");
    rig_connect(&rig, 5, "out", 3, "in1");
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "shift", 1000), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "shift", 20), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 5, "shift", -500), CANOPY_OK);
    rig_install(&rig);
    CHECK(host_inlet_at(rig.instance, 3, 0, 5) == 1005.0f);
    CHECK(host_inlet_at(rig.instance, 3, 1, 5) == -495.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 3, 0, 0, 100, 4, g.data), CANOPY_OK);
    CHECK(guarded_equals(&g, ahead));
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 3, 1, 100, 0, 4, g.data), CANOPY_OK);
    CHECK(guarded_equals(&g, behind_reversed));
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, 0, 100, 4, g.data), CANOPY_OK);
    CHECK(guarded_equals(&g, chained));
    CHECK(host_inlet_at(rig.instance, 6, 0, 5) == 1025.0f);
    guarded_free(&g);
    rig_close(&rig);
}

/* ---- fan-out ---- */

static void test_c_one_outlet_may_feed_many_inlets_and_every_consumer_gets_its_own_answer(void)
{
    Rig rig;
    Guarded g = guarded_new(4);
    const float doubled[4] = {0.0f, 50.0f, 100.0f, 150.0f};
    rig_open(&rig);
    rig_node(&rig, 1, "test.time");
    rig_node(&rig, 2, "test.sum");
    rig_node(&rig, 3, "test.gain");
    rig_node(&rig, 4, "test.sink");
    rig_connect(&rig, 1, "a", 2, "a");                 /* time.a feeds both inlets of the sum... */
    rig_connect(&rig, 1, "a", 2, "b");
    rig_connect(&rig, 1, "a", 3, "in");                /* ...and a gain */
    rig_connect(&rig, 1, "b", 3, "gain");              /* and time.b feeds the gain's gain: out = t * 2t */
    rig_connect(&rig, 2, "out", 4, "in0");
    rig_connect(&rig, 3, "out", 4, "in1");
    rig_install(&rig);
    CHECK(host_inlet_at(rig.instance, 4, 0, 21) == 42.0f);
    CHECK(host_inlet_at(rig.instance, 4, 1, 21) == 882.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 4, 0, 0, 100, 4, g.data), CANOPY_OK);
    CHECK(guarded_equals(&g, doubled));
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 4, 1, 0, 100, 4, g.data), CANOPY_OK);
    {
        const float product[4] = {0.0f, 25.0f * 50.0f, 50.0f * 100.0f, 75.0f * 150.0f};
        CHECK(guarded_equals(&g, product));
    }
    guarded_free(&g);
    rig_close(&rig);
}

/* ---- determinism (design section 5) ---- */

static void build_mixed_graph(Rig *rig)
{
    rig_open(rig);
    rig_node(rig, 1, "test.time");
    rig_node(rig, 2, "test.gain");
    rig_node(rig, 3, "test.shift");
    rig_node(rig, 4, "test.const");
    rig_node(rig, 5, "test.sum");
    rig_node(rig, 6, "test.sink");
    rig_connect(rig, 1, "a", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    rig_connect(rig, 3, "out", 5, "a");
    rig_connect(rig, 4, "out", 5, "b");
    rig_connect(rig, 5, "out", 6, "in0");
    CHECK_INT(canopy_graph_set_knob(rig->graph, 2, "gain", 0.3f), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 3, "shift", 123), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig->graph, 4, "value", 0.7), CANOPY_OK);
    rig_install(rig);
}

static void test_c_the_same_query_returns_identical_floats_every_time_and_in_every_instance(void)
{
    Rig rig, other;
    Guarded first = guarded_new(1000), again = guarded_new(1000), noise = guarded_new(37), from_other = guarded_new(1000);
    CanopyInstance *second;
    float point;
    int round;
    build_mixed_graph(&rig);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, -5000, 77777, 1000, first.data), CANOPY_OK);
    point = host_inlet_at(rig.instance, 6, 0, 12345);
    for (round = 0; round < 3; round++) {
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, 3, 99999, 37, noise.data), CANOPY_OK);      /* other queries in between... */
        (void)host_inlet_at(rig.instance, 6, 0, -1);
        CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 1, -0.9f), CANOPY_OK);                               /* ...and a knob moved away... */
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, -5000, 77777, 1000, again.data), CANOPY_OK);
        CHECK(!guarded_bits_equal(&first, &again));                                                          /* (it did change the answer) */
        CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 1, 0.3f), CANOPY_OK);                                /* ...and back */
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, -5000, 77777, 1000, again.data), CANOPY_OK);
        CHECK(guarded_bits_equal(&first, &again));
        CHECK(float_bits(host_inlet_at(rig.instance, 6, 0, 12345)) == float_bits(point));
    }
    second = canopy_engine_new_instance(rig.engine);                         /* another instance of the same engine... */
    CHECK(second != NULL);
    if (second) {
        CHECK_INT(canopy_instance_inlet_span(second, 6, 0, -5000, 77777, 1000, again.data), CANOPY_OK);
        CHECK(guarded_bits_equal(&first, &again));
        canopy_instance_free(second);
    }
    build_mixed_graph(&other);                                               /* ...and a second engine built from the same description */
    CHECK_INT(canopy_instance_inlet_span(other.instance, 6, 0, -5000, 77777, 1000, from_other.data), CANOPY_OK);
    CHECK(guarded_bits_equal(&first, &from_other));
    rig_close(&other);
    guarded_free(&first);
    guarded_free(&again);
    guarded_free(&noise);
    guarded_free(&from_other);
    rig_close(&rig);
}

/* the same graph as build_mixed_graph, described in the opposite order: nodes, settings and connections last to first */
static void build_mixed_graph_reversed(Rig *rig)
{
    rig_open(rig);
    rig_node(rig, 6, "test.sink");
    rig_node(rig, 5, "test.sum");
    rig_node(rig, 4, "test.const");
    rig_node(rig, 3, "test.shift");
    rig_node(rig, 2, "test.gain");
    rig_node(rig, 1, "test.time");
    CHECK_INT(canopy_graph_set_float(rig->graph, 4, "value", 0.7), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 3, "shift", 123), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(rig->graph, 2, "gain", 0.3f), CANOPY_OK);
    rig_connect(rig, 5, "out", 6, "in0");
    rig_connect(rig, 4, "out", 5, "b");
    rig_connect(rig, 3, "out", 5, "a");
    rig_connect(rig, 2, "out", 3, "in");
    rig_connect(rig, 1, "a", 2, "in");
    rig_install(rig);
}

static void test_c_the_order_in_which_a_graph_is_described_does_not_change_its_answers(void)
{
    Rig forward, backward;
    Guarded a = guarded_new(777), b = guarded_new(777);
    build_mixed_graph(&forward);
    build_mixed_graph_reversed(&backward);
    CHECK_INT(canopy_instance_inlet_span(forward.instance, 6, 0, -123456, 7654321, 777, a.data), CANOPY_OK);
    CHECK_INT(canopy_instance_inlet_span(backward.instance, 6, 0, -123456, 7654321, 777, b.data), CANOPY_OK);
    CHECK(guarded_bits_equal(&a, &b));
    CHECK(float_bits(host_inlet_at(forward.instance, 6, 0, 99)) == float_bits(host_inlet_at(backward.instance, 6, 0, 99)));
    CHECK_INT(canopy_instance_arena_floats(forward.instance), canopy_instance_arena_floats(backward.instance));
    guarded_free(&a);
    guarded_free(&b);
    rig_close(&backward);
    rig_close(&forward);
}

static void test_c_node_ids_may_be_any_int64_value(void)
{
    Rig rig;
    Guarded g = guarded_new(3);
    rig_open(&rig);
    rig_node(&rig, INT64_MIN, "test.time");
    rig_node(&rig, -1, "test.gain");
    rig_node(&rig, 0, "test.sum");
    rig_node(&rig, 7, "test.const");
    rig_node(&rig, INT64_MAX, "test.sink");
    rig_connect(&rig, INT64_MIN, "a", -1, "in");
    rig_connect(&rig, -1, "out", 0, "a");
    rig_connect(&rig, 7, "out", 0, "b");
    rig_connect(&rig, 0, "out", INT64_MAX, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 7, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_engine_node_count(rig.engine), 5);
    CHECK(host_inlet_at(rig.instance, INT64_MAX, 0, 100) == 100.5f);          /* time(100) * gain knob 1.0 + 0.5 */
    CHECK_INT(canopy_engine_set_knob(rig.engine, -1, 1, 0.5f), CANOPY_OK);
    CHECK(host_inlet_at(rig.instance, INT64_MAX, 0, 100) == 50.5f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, INT64_MAX, 0, 0, 30, 3, g.data), CANOPY_OK);
    {
        const float expected[3] = {0.5f, 5.5f, 10.5f};
        CHECK(guarded_equals(&g, expected));
    }
    CHECK(host_inlet_at(rig.instance, INT64_MAX - 1, 0, 100) == 0.0f);        /* the neighbours of the extreme IDs do not exist */
    CHECK(host_inlet_at(rig.instance, INT64_MIN + 1, 0, 100) == 0.0f);
    CHECK_INT(canopy_engine_set_knob(rig.engine, INT64_MIN + 1, 0, 0.0f), CANOPY_ERR_NODE);
    guarded_free(&g);
    rig_close(&rig);
}

static void test_c_answering_queries_allocates_nothing(void)
{
    Rig rig;
    Guarded g = guarded_new(CANOPY_MAX_N);
    int64_t total_before;
    int i;
    build_mixed_graph(&rig);
    total_before = canopy_alloc_total();
    for (i = 0; i < 50; i++) {
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, -5000, 77777 + i, 1000 + 40 * i, g.data), CANOPY_OK);
        (void)host_inlet_at(rig.instance, 6, 0, i);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, 0, 1, CANOPY_MAX_N, g.data), CANOPY_OK);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, 0, INT64_MIN, 10, g.data), CANOPY_OK);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 6, 0, 0, 5, 0, g.data), CANOPY_ERR_N);
    }
    CHECK_INT(canopy_alloc_total(), total_before);
    guarded_free(&g);
    rig_close(&rig);
}

/* ---- the instance is for one caller at a time ---- */

static struct {
    CanopyInstance *instance;
    float point;
    int32_t point_status, span_status;
    float span_out[4];
} reenter;

static int32_t reenter_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    (void)ctx; (void)outlet; (void)t;
    reenter.point = 9.0f;
    reenter.point_status = canopy_instance_inlet_at(reenter.instance, 3, 0, 0, &reenter.point);      /* node 3 would answer 9.0 if the instance were free */
    fill_floats(reenter.span_out, 4, 7.0f);
    reenter.span_status = canopy_instance_inlet_span(reenter.instance, 3, 0, 0, 10, 4, reenter.span_out);
    { *out = 2.0f; return CANOPY_OK; }
}

static void test_c_using_an_instance_while_it_is_answering_is_refused_as_busy_and_afterwards_it_works_again(void)
{
    Rig rig;
    CanopyNodeType type = support_base_type("test.reenter", "Reenter");
    type.n_outlets = 1; type.outlets = PROBE_OUT;
    type.handlers.query_at = reenter_at;
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.reenter");
    rig_node(&rig, 2, "test.sink");
    rig_node(&rig, 3, "test.sink");
    rig_node(&rig, 4, "test.const");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_connect(&rig, 4, "out", 3, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 4, "value", 9.0), CANOPY_OK);
    rig_install(&rig);
    reenter.instance = rig.instance;
    reenter.point = -1.0f;
    reenter.point_status = reenter.span_status = -1;
    CHECK(host_inlet_at(rig.instance, 2, 0, 0) == 2.0f);               /* the outer query is not disturbed */
    CHECK_INT(reenter.point_status, CANOPY_ERR_BUSY);                             /* the nested point query was refused, with a status... */
    CHECK(reenter.point == 0.0f);                                                 /* ...and a zero */
    CHECK_INT(reenter.span_status, CANOPY_ERR_BUSY);
    CHECK(reenter.span_out[0] == 0.0f && reenter.span_out[3] == 0.0f);            /* and zero-filled */
    CHECK(host_inlet_at(rig.instance, 3, 0, 0) == 9.0f);               /* afterwards the instance answers again */
    rig_close(&rig);
}

void register_test_query(void)
{
    RUN(test_c_an_unconnected_inlet_answers_with_its_knob_for_points_and_spans_whatever_the_times);
    RUN(test_c_a_connected_inlet_gets_the_outlets_answer_and_ignores_its_own_knob);
    RUN(test_c_span_samples_are_placed_by_the_formula_including_reversed_and_empty_spans);
    RUN(test_c_point_queries_reach_the_node_and_the_right_outlet);
    RUN(test_c_the_span_of_a_pointwise_node_is_one_point_query_per_sample_time);
    RUN(test_c_a_span_only_node_gets_the_span_and_answers_a_point_query_with_a_one_sample_span);
    RUN(test_c_a_span_only_node_that_fails_reports_its_status_for_a_point_query_and_the_answer_is_zero);
    RUN(test_c_a_point_query_reports_statuses_like_a_span_query_and_the_answer_is_zero_when_it_fails);
    RUN(test_c_a_pointwise_node_whose_point_query_fails_fails_the_derived_span_at_the_first_failure_and_it_is_zero_filled);
    RUN(test_c_bad_span_arguments_from_the_host_give_the_documented_status_and_zero_fill_when_n_is_valid);
    RUN(test_c_the_largest_n_works_through_every_kind_of_source);
    RUN(test_c_a_node_gets_the_same_statuses_through_its_context_whether_or_not_the_inlet_is_connected);
    RUN(test_c_a_status_from_a_node_is_passed_through_unchanged_and_the_engine_zero_fills_out);
    RUN(test_c_a_node_may_query_later_or_earlier_times_than_it_was_asked);
    RUN(test_c_one_outlet_may_feed_many_inlets_and_every_consumer_gets_its_own_answer);
    RUN(test_c_the_same_query_returns_identical_floats_every_time_and_in_every_instance);
    RUN(test_c_the_order_in_which_a_graph_is_described_does_not_change_its_answers);
    RUN(test_c_node_ids_may_be_any_int64_value);
    RUN(test_c_answering_queries_allocates_nothing);
    RUN(test_c_using_an_instance_while_it_is_answering_is_refused_as_busy_and_afterwards_it_works_again);
}
