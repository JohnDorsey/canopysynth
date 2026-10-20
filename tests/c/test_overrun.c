/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Tests: nothing writes outside the buffer it was given (plan step 13). Every node type of the DLL and of the test suite is asked, through the
   host's calls, for spans of 27 sizes (from 1 to the limit of 65536, with the ones either side of every power of two between) over 16 shapes of
   time (forward, reversed, empty, negative, around zero, enormous, very wide, the exact edges of what fits and one step beyond them), through
   buffers with canary values on both sides (see Guarded in support.h) that are exactly as big as asked: so the debug heap and AddressSanitizer
   also see an overrun. A span that succeeds must have written every one of its n floats; one that fails must have zero-filled all n (when n is
   valid), or touched nothing at all (when n is not). The same for point queries at the ends of time, and for the preview's audio callback. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "support.h"

static const int64_t N_LIST[] = {1, 2, 3, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65, 100, 255, 256, 257, 1000, 4095, 4096, 4097, 16383, 16384,
                                 32767, 32768, 65535, 65536};
#define N_COUNT ((int)(sizeof N_LIST / sizeof N_LIST[0]))
enum { SHAPES = 16 };

static int reported;                                    /* problems printed so far (the rest are counted, not printed) */
#define PROBLEM(...) do { ctest_current_failed = 1; if (reported++ < 8) { printf("    "); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* The times of a shape of span for n samples. */
static void shape_times(int shape, int64_t n, int64_t *t0, int64_t *t1)
{
    switch (shape) {
    case 0: *t0 = 0; *t1 = n * 20833; break;                                   /* forward, about a 48 kHz block */
    case 1: *t0 = n * 20833; *t1 = 0; break;                                   /* reversed */
    case 2: *t0 = *t1 = 123456789; break;                                      /* empty: every sample at one time */
    case 3: *t0 = -n * 1000; *t1 = -1; break;                                  /* negative times */
    case 4: *t0 = -n * 500; *t1 = n * 500; break;                              /* around zero */
    case 5: *t0 = 4000000000000000000LL; *t1 = *t0 + n * 7919; break;          /* enormous, valid */
    case 6: *t1 = -4000000000000000000LL; *t0 = *t1 - n * 7919; break;         /* enormous and negative */
    case 7: *t0 = -(INT64_MAX / 2); *t1 = INT64_MAX / 2; break;                /* a very wide span that fits (t1 - t0 = INT64_MAX - 1) */
    case 8: *t0 = INT64_MIN; *t1 = INT64_MAX; break;                           /* t1 - t0 does not fit in 64 bits */
    case 9: *t0 = INT64_MAX - 3; *t1 = INT64_MAX - 1; break;                   /* at the very top of time */
    case 10: *t0 = 0; *t1 = INT64_MAX; break;                                  /* t1 - t0 is exactly INT64_MAX: fits */
    case 11: *t0 = -1; *t1 = INT64_MAX; break;                                 /* one more: does not fit */
    case 12: *t0 = INT64_MAX; *t1 = 0; break;                                  /* reversed, t1 - t0 = -INT64_MAX: fits */
    case 13: *t0 = INT64_MAX; *t1 = -1; break;                                 /* t1 - t0 is exactly INT64_MIN: fits */
    case 14: *t0 = INT64_MAX; *t1 = -2; break;                                 /* one less: does not fit */
    default: *t0 = -1; *t1 = INT64_MAX - 1; break;                             /* a negative start and t1 - t0 exactly INT64_MAX: fits */
    }
}

/* 1 if t1 - t0 does not fit in a signed 64-bit integer: worked out here with unsigned arithmetic, not with the library's own check (a fault in that
   would otherwise change the expected status and the result together). The distance is exact as an unsigned number; forward it must be at most
   INT64_MAX, backward at most 2^63 (INT64_MIN's magnitude). */
static int overflows(int64_t t0, int64_t t1)
{
    uint64_t distance = t1 >= t0 ? (uint64_t)t1 - (uint64_t)t0 : (uint64_t)t0 - (uint64_t)t1;
    return t1 >= t0 ? distance > (uint64_t)INT64_MAX : distance > 9223372036854775808ULL;
}

static int64_t magnitude(int64_t t)
{
    return t == INT64_MIN ? INT64_MAX : (t < 0 ? -t : t);
}

typedef struct {
    const char *name;
    void (*build)(Rig *rig);          /* nodes as needed; the probe is node 100, a test.sink, whose inlets in0 and in1 are read */
    int32_t status;                   /* what a span that fits gives: CANOPY_OK, or the status of a node that always fails */
    int64_t limit;                    /* the node cannot take times beyond this (a node of the test suite that adds to t, a filter that renders forward) */
    int64_t max_n;                    /* the most samples worth asking for (the filter's cost grows with the span) */
    int linked;                       /* which inlets of the sink the node feeds: bit 0 is in0, bit 1 is in1. The other is unconnected and gives its knob (0.5 for in1) */
    const char *boundary;             /* if not NULL, a boundary outlet of this name to read as well */
} Case;

static const char *wav_mono, *wav_stereo;               /* paths of the two files the file cases use */

static void sink(Rig *rig, int64_t from, const char *outlet, const char *inlet)
{
    rig_node(rig, 100, "test.sink");
    rig_connect(rig, from, outlet, 100, inlet);
}

static void build_const(Rig *rig)
{
    rig_node(rig, 1, "test.const");
    CHECK_INT(canopy_graph_set_float(rig->graph, 1, "value", 0.5), CANOPY_OK);
    sink(rig, 1, "out", "in0");
}

static void build_const_span(Rig *rig)
{
    rig_node(rig, 1, "test.const_span");
    CHECK_INT(canopy_graph_set_float(rig->graph, 1, "value", -0.25), CANOPY_OK);
    sink(rig, 1, "out", "in0");
}

static void build_time(Rig *rig)
{
    rig_node(rig, 1, "test.time");
    sink(rig, 1, "a", "in0");
    rig_connect(rig, 1, "b", 100, "in1");
}

static void build_recorder(Rig *rig)
{
    rig_node(rig, 1, "test.recorder");
    sink(rig, 1, "out", "in0");
}

static void build_recorder_span(Rig *rig)
{
    rig_node(rig, 1, "test.recorder_span");
    sink(rig, 1, "out", "in0");
}

static void build_gain_chain(Rig *rig)             /* const -> gain -> gain -> gain: three scratch buffers held at once at the largest n */
{
    rig_node(rig, 1, "test.const");
    CHECK_INT(canopy_graph_set_float(rig->graph, 1, "value", 0.5), CANOPY_OK);
    rig_node(rig, 2, "test.gain");
    rig_node(rig, 3, "test.gain");
    rig_node(rig, 4, "test.gain");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    rig_connect(rig, 3, "out", 4, "in");
    sink(rig, 4, "out", "in0");
}

static void build_sum(Rig *rig)
{
    rig_node(rig, 1, "test.const");
    rig_node(rig, 2, "test.saw");
    rig_node(rig, 3, "test.sum");
    rig_connect(rig, 1, "out", 3, "a");
    rig_connect(rig, 2, "out", 3, "b");
    sink(rig, 3, "out", "in0");
}

static void build_shift(Rig *rig)                  /* looks ahead by 3 s */
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test.shift");
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "shift", 3000000000LL), CANOPY_OK);
    rig_connect(rig, 1, "out", 2, "in");
    sink(rig, 2, "out", "in0");
}

static void build_failing(Rig *rig)
{
    rig_node(rig, 1, "test.failing");
    sink(rig, 1, "out", "in0");
}

static void build_failing_span_only(Rig *rig)
{
    rig_node(rig, 1, "test.failing_span_only");
    sink(rig, 1, "out", "in0");
}

static void build_saw(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    sink(rig, 1, "out", "in0");
}

static void build_jitter(Rig *rig)
{
    rig_node(rig, 1, "test.jitter");
    sink(rig, 1, "out", "in0");
}

static void build_stamp_and_state(Rig *rig)       /* two stateful point nodes at once: a stamp node over a state node, and a counter */
{
    rig_node(rig, 1, "test.state");
    rig_node(rig, 2, "test.stamp");
    rig_node(rig, 3, "test.counter");
    rig_connect(rig, 1, "out", 2, "in");
    sink(rig, 2, "out", "in0");
    rig_connect(rig, 3, "out", 100, "in1");
}

static void build_source_config(Rig *rig)         /* a node with a shared resource and one with every kind of setting */
{
    rig_node(rig, 1, "test.source");
    rig_node(rig, 2, "test.config");
    sink(rig, 1, "out", "in0");
    rig_connect(rig, 2, "out", 100, "in1");
}

static void build_boundary_slot(Rig *rig)         /* the built-in type with a boundary slot, written by the host by node ID */
{
    rig_node(rig, 1, "test_boundary");
    sink(rig, 1, "out", "in0");
}

static void build_boundary_pair(Rig *rig)         /* boundary inlet "in" -> boundary outlet "out" (read by name) */
{
    rig_node(rig, 1, "boundary_inlet");
    rig_node(rig, 2, "boundary_outlet");
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "name", "in"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig->graph, 2, "name", "out"), CANOPY_OK);
    rig_connect(rig, 1, "out", 2, "in");
    sink(rig, 1, "out", "in0");
}

static void build_file_mono(Rig *rig)
{
    rig_node(rig, 1, "file_read");
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "path", wav_mono), CANOPY_OK);
    sink(rig, 1, "left", "in0");
    rig_connect(rig, 1, "right", 100, "in1");
}

static void build_file_stereo(Rig *rig)
{
    rig_node(rig, 1, "file_read");
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "path", wav_stereo), CANOPY_OK);
    sink(rig, 1, "left", "in0");
    rig_connect(rig, 1, "right", 100, "in1");
}

static void build_filter(Rig *rig)                 /* saw -> the hidden filter (allocates, keeps checkpoints) */
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test_filter");
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "internal_sampling_rate", 8000), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "checkpoint_seconds", 1), CANOPY_OK);
    rig_connect(rig, 1, "out", 2, "in");
    sink(rig, 2, "out", "in0");
}

static const Case CASES[] = {
    {"test.const (point only)", build_const, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"test.const_span (span only)", build_const_span, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"test.time (two outlets)", build_time, CANOPY_OK, INT64_MAX, 65536, 3, NULL},
    {"test.recorder", build_recorder, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"test.recorder_span", build_recorder_span, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"three test.gain in a row (scratch)", build_gain_chain, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"test.sum of const and saw", build_sum, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"test.shift (looks ahead)", build_shift, CANOPY_OK, 4600000000000000000LL, 65536, 1, NULL},
    {"test.failing (always fails)", build_failing, FAILING_STATUS, INT64_MAX, 65536, 1, NULL},
    {"test.failing_span_only", build_failing_span_only, FAILING_STATUS, INT64_MAX, 65536, 1, NULL},
    {"test.saw", build_saw, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"test.jitter", build_jitter, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"stateful test nodes", build_stamp_and_state, CANOPY_OK, INT64_MAX, 65536, 3, NULL},
    {"shared resource and settings", build_source_config, CANOPY_OK, INT64_MAX, 65536, 3, NULL},
    {"a built-in type with a boundary slot", build_boundary_slot, CANOPY_OK, INT64_MAX, 65536, 1, NULL},
    {"boundary inlet and outlet", build_boundary_pair, CANOPY_OK, INT64_MAX, 65536, 1, "out"},
    {"file_read, mono 16-bit file", build_file_mono, CANOPY_OK, INT64_MAX, 65536, 3, NULL},
    {"file_read, stereo float file", build_file_stereo, CANOPY_OK, INT64_MAX, 65536, 3, NULL},
    {"the hidden filter", build_filter, CANOPY_OK, 3000000000LL, 4097, 1, NULL},
};

/* ---- the checks ---- */

/* The result of one span query, given the guarded buffer it was made into and the status a span that fits gives (the node's own for an inlet it feeds, CANOPY_OK for
   an unconnected one, which gives its knob: then every float must be that knob's position). */
static void check_result(const Case *c, const char *how, int64_t t0, int64_t t1, int64_t n, int32_t status, const Guarded *g, int32_t fits, int unconnected)
{
    int32_t expected = overflows(t0, t1) ? CANOPY_ERR_OVERFLOW : fits;
    int64_t i;
    if (status != expected) PROBLEM("%s, %s: n=%lld [%lld, %lld): status %d, expected %d", c->name, how, (long long)n, (long long)t0, (long long)t1, status, expected);
    if (unconnected && status == CANOPY_OK)
        for (i = 0; i < n; i++)
            if (g->data[i] != 0.5f) {
                PROBLEM("%s, %s: n=%lld: an unconnected inlet gave %g at sample %lld, not its knob 0.5", c->name, how, (long long)n, (double)g->data[i], (long long)i);
                break;
            }
    if (!guarded_guards_intact(g)) PROBLEM("%s, %s: n=%lld [%lld, %lld): something was written outside the buffer", c->name, how, (long long)n, (long long)t0, (long long)t1);
    if (status == CANOPY_OK && guarded_unwritten(g) != 0) PROBLEM("%s, %s: n=%lld: a successful span left %lld floats unwritten", c->name, how, (long long)n, (long long)guarded_unwritten(g));
    if (status != CANOPY_OK && !guarded_all_zero(g)) PROBLEM("%s, %s: n=%lld [%lld, %lld): a failed span was not zero-filled (status %d)", c->name, how, (long long)n, (long long)t0, (long long)t1, status);
}

static void sweep_case(const Case *c)
{
    Rig rig;
    int shape, i, inlet, tests = 0;
    rig_open(&rig);
    c->build(&rig);
    rig_install(&rig);
    if (c->boundary) CHECK_INT(canopy_engine_set_boundary(rig.engine, "in", 3.5f), CANOPY_OK);
    for (shape = 0; shape < SHAPES; shape++)
        for (i = 0; i < N_COUNT; i++) {
            int64_t n = N_LIST[i], t0, t1;
            if (n > c->max_n) continue;
            shape_times(shape, n, &t0, &t1);
            if (magnitude(t0) > c->limit || magnitude(t1) > c->limit) continue;
            for (inlet = 0; inlet < 2; inlet++) {                                 /* both inlets of the sink: the one the node feeds, and the one that is left alone */
                Guarded g = guarded_new(n);
                int linked = (c->linked >> inlet) & 1;
                int32_t status;
                support_calls_reset();
                status = canopy_instance_inlet_span(rig.instance, 100, inlet, t0, t1, n, g.data);
                check_result(c, linked ? "host span through a connected inlet" : "host span through an unconnected inlet", t0, t1, n, status, &g,
                             linked ? c->status : CANOPY_OK, !linked);
                guarded_free(&g);
                tests++;
            }
            if (c->boundary) {
                Guarded g = guarded_new(n);
                int32_t status = canopy_instance_read_span(rig.instance, c->boundary, t0, t1, n, g.data);
                check_result(c, "host span through a boundary outlet", t0, t1, n, status, &g, c->status, 0);
                guarded_free(&g);
                tests++;
            }
        }
    CHECK(tests > 100);                                  /* (the sweep did run) */
    CHECK_HEAP();
    rig_close(&rig);
}

static void test_c_no_span_query_writes_outside_its_buffer_for_any_node_size_or_time(void)
{
    int k;
    reported = 0;
    for (k = 0; k < (int)(sizeof CASES / sizeof CASES[0]); k++) sweep_case(&CASES[k]);
}

/* A span whose n is not valid must leave the buffer untouched (its size is not known); a NULL buffer is refused; neither may crash. */
static void test_c_a_span_with_a_bad_n_touches_nothing_and_a_null_buffer_is_refused_for_every_kind_of_source(void)
{
    static const int64_t BAD_N[] = {0, -1, -65536, 65537, 1000000, 4294967296LL, INT64_MIN, INT64_MAX};
    int k, b;
    reported = 0;
    for (k = 0; k < (int)(sizeof CASES / sizeof CASES[0]); k++) {
        const Case *c = &CASES[k];
        Rig rig;
        rig_open(&rig);
        c->build(&rig);
        rig_install(&rig);
        for (b = 0; b < (int)(sizeof BAD_N / sizeof BAD_N[0]); b++) {
            Guarded g = guarded_new(8);                                        /* eight floats: a call that believed n would run off the end */
            int32_t status = canopy_instance_inlet_span(rig.instance, 100, 0, 0, 1000, BAD_N[b], g.data);
            if (status != CANOPY_ERR_N) PROBLEM("%s: n=%lld gave status %d, not %d", c->name, (long long)BAD_N[b], status, CANOPY_ERR_N);
            if (!guarded_guards_intact(&g) || guarded_unwritten(&g) != 8) PROBLEM("%s: n=%lld touched the buffer", c->name, (long long)BAD_N[b]);
            if (c->boundary) {
                guarded_reset(&g);
                status = canopy_instance_read_span(rig.instance, c->boundary, 0, 1000, BAD_N[b], g.data);
                if (status != CANOPY_ERR_N || !guarded_guards_intact(&g) || guarded_unwritten(&g) != 8) PROBLEM("%s: n=%lld through a boundary outlet", c->name, (long long)BAD_N[b]);
            }
            guarded_free(&g);
        }
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 100, 0, 0, 1000, 64, NULL), CANOPY_ERR_ARGUMENT);
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 100, 0, 0, 1000, 0, NULL), CANOPY_ERR_N);       /* (n is checked first) */
        CHECK_HEAP();
        rig_close(&rig);
    }
}

/* Point queries at the ends of time and next to them: any status the node may give, never a crash, and 0.0 after a failure. */
static void test_c_point_queries_at_the_ends_of_time_never_crash_and_give_zero_after_a_failure(void)
{
    static const int64_t TIMES[] = {0, 1, -1, 1000000000LL, -1000000000LL, 4000000000000000000LL, -4000000000000000000LL, INT64_MAX - 1, INT64_MAX,
                                    INT64_MIN + 1, INT64_MIN};
    int k, i, inlet;
    reported = 0;
    for (k = 0; k < (int)(sizeof CASES / sizeof CASES[0]); k++) {
        const Case *c = &CASES[k];
        Rig rig;
        rig_open(&rig);
        c->build(&rig);
        rig_install(&rig);
        for (i = 0; i < (int)(sizeof TIMES / sizeof TIMES[0]); i++) {
            if (magnitude(TIMES[i]) > c->limit) continue;
            for (inlet = 0; inlet < 2; inlet++) {
                float value = 9.0f;
                int linked = (c->linked >> inlet) & 1;
                int32_t status = canopy_instance_inlet_at(rig.instance, 100, inlet, TIMES[i], &value), expected = linked ? c->status : CANOPY_OK;
                if (status != expected) PROBLEM("%s: a point query at %lld through %s gave status %d, expected %d", c->name, (long long)TIMES[i], linked ? "a connected inlet" : "an unconnected one", status, expected);
                if (status != CANOPY_OK && float_bits(value) != 0u) PROBLEM("%s: a failed point query at %lld left %g, not 0.0", c->name, (long long)TIMES[i], (double)value);
                if (!linked && status == CANOPY_OK && value != 0.5f) PROBLEM("%s: an unconnected inlet gave %g at %lld, not its knob 0.5", c->name, (double)value, (long long)TIMES[i]);
            }
        }
        CHECK_HEAP();
        rig_close(&rig);
    }
}

/* ---- the preview's audio callback ---- */

static void test_c_the_preview_callback_writes_exactly_two_floats_per_frame_for_any_frame_count_including_more_than_one_chunk(void)
{
    static const uint32_t FRAMES[] = {1, 2, 3, 63, 64, 959, 960, 961, 4096, 65535, 65536, 65537, 100000, 131072, 131073};
    Rig rig;
    int i, state;
    reported = 0;
    for (state = 0; state < 2; state++) {                                      /* paused (it must write silence), then playing */
        rig_open(&rig);
        rig_node(&rig, 1, "test.const");
        CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.375), CANOPY_OK);
        rig_node(&rig, 2, "realtime_preview");
        rig_connect(&rig, 1, "out", 2, "left");
        rig_connect(&rig, 1, "out", 2, "center");
        rig_install(&rig);
        CHECK_INT(canopy_preview_prepare(rig.engine, 2, state), CANOPY_OK);
        for (i = 0; i < (int)(sizeof FRAMES / sizeof FRAMES[0]); i++) {
            Guarded g = guarded_new(2 * (int64_t)FRAMES[i]);
            int64_t k, wrong = 0;
            CHECK_INT(canopy_preview_fill(rig.engine, 2, g.data, FRAMES[i]), CANOPY_OK);
            if (!guarded_guards_intact(&g)) PROBLEM("a callback of %u frames wrote outside its buffer", (unsigned)FRAMES[i]);
            if (guarded_unwritten(&g) != 0) PROBLEM("a callback of %u frames left %lld floats unwritten", (unsigned)FRAMES[i], (long long)guarded_unwritten(&g));
            for (k = 0; k < (int64_t)FRAMES[i]; k++) {
                float left = g.data[2 * k], right = g.data[2 * k + 1];
                if (state == 1 ? (left != 0.75f || right != 0.375f) : (left != 0.0f || right != 0.0f)) wrong++;     /* left = const + const, right = center only */
            }
            if (wrong) PROBLEM("a callback of %u frames (%s): %lld frames hold the wrong value", (unsigned)FRAMES[i], state ? "playing" : "paused", (long long)wrong);
            guarded_free(&g);
        }
        CHECK_HEAP();
        rig_close(&rig);
    }
}

/* ---- the files the file cases read ---- */

static char path_mono[MAX_PATH + 64], path_stereo[MAX_PATH + 64];

static void write_wav(const char *path, int channels, int float_samples, int frames)
{
    FILE *file = fopen(path, "wb");
    int bytes = float_samples ? 4 : 2, i, c;
    uint32_t data_bytes = (uint32_t)(frames * channels * bytes), rate = 8000, riff = 36u + data_bytes, fmt = 16;
    uint32_t byte_rate = rate * (uint32_t)(channels * bytes);
    uint16_t tag = float_samples ? 3 : 1, ch = (uint16_t)channels, block = (uint16_t)(channels * bytes), bits = (uint16_t)(bytes * 8);
    CHECK(file != NULL);
    if (!file) return;
    fwrite("RIFF", 1, 4, file); fwrite(&riff, 4, 1, file); fwrite("WAVEfmt ", 1, 8, file); fwrite(&fmt, 4, 1, file);
    fwrite(&tag, 2, 1, file); fwrite(&ch, 2, 1, file); fwrite(&rate, 4, 1, file); fwrite(&byte_rate, 4, 1, file);
    fwrite(&block, 2, 1, file); fwrite(&bits, 2, 1, file);
    fwrite("data", 1, 4, file); fwrite(&data_bytes, 4, 1, file);
    for (i = 0; i < frames; i++)
        for (c = 0; c < channels; c++) {
            int step = (i * 37 + c * 11) % 200 - 100;
            if (float_samples) {
                float value = (float)step / 100.0f;
                fwrite(&value, 4, 1, file);
            } else {
                int16_t value = (int16_t)(step * 300);
                fwrite(&value, 2, 1, file);
            }
        }
    fclose(file);
}

static void make_files(void)
{
    DWORD n = GetTempPathA(MAX_PATH, path_mono);
    memcpy(path_stereo, path_mono, n + 1);
    snprintf(path_mono + n, 64, "canopy_overrun_mono_%lu.wav", (unsigned long)GetCurrentProcessId());
    snprintf(path_stereo + n, 64, "canopy_overrun_stereo_%lu.wav", (unsigned long)GetCurrentProcessId());
    write_wav(path_mono, 1, 0, 9000);
    write_wav(path_stereo, 2, 1, 12000);
    wav_mono = path_mono;
    wav_stereo = path_stereo;
}

static void remove_files(void)
{
    remove(path_mono);
    remove(path_stereo);
}

void register_test_overrun(void)
{
    make_files();                                        /* (the file cases read them; removed again after the last test) */
    RUN(test_c_no_span_query_writes_outside_its_buffer_for_any_node_size_or_time);
    RUN(test_c_a_span_with_a_bad_n_touches_nothing_and_a_null_buffer_is_refused_for_every_kind_of_source);
    RUN(test_c_point_queries_at_the_ends_of_time_never_crash_and_give_zero_after_a_failure);
    RUN(test_c_the_preview_callback_writes_exactly_two_floats_per_frame_for_any_frame_count_including_more_than_one_chunk);
    remove_files();
}
