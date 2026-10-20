/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Determinism (plan step 13; design section 5: while the graph, the knob positions, the boundary values, the settings and the files stay the same, a query
   with the same arguments returns identical floats every time; design section 12: "recorded-output tests made possible by the determinism rule").
   Recorded outputs: twelve whole graphs, each asked a fixed list of queries (spans of every shape, forward and reversed, before and after t = 0, with all n
   samples at one time, the biggest span, points). The bits of the answers are hashed (FNV-1a, 64 bits) and the hash is compared with the one recorded here.
   The three C test programs (normal, debug heap, AddressSanitizer) run the same table, so it also says that the optimiser and the instrumentation change not
   one bit. A deliberate change of a node's arithmetic changes a hash: run with CANOPY_RECORD=1 to print a new table.
   Properties (nothing recorded): asked again, asked in the opposite order by a cold instance, asked by instances in other threads, asked at random of a long
   lived instance and of a fresh one (the filter keeps checkpoints and a cursor: what it has been asked must never show), asked after the same description is
   installed again and after changes that cannot matter (a setting of the filter that only moves its checkpoints, an unrelated node), and a span against the
   point queries at its sample times. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <process.h>
#include "support.h"

#define FNV_START 0xCBF29CE484222325ULL
#define MAX_QUERIES 40
#define THREADS 3

static uint64_t fnv_add(uint64_t hash, const void *data, size_t size)
{
    const unsigned char *bytes = (const unsigned char *)data;
    size_t i;
    for (i = 0; i < size; i++) {
        hash ^= bytes[i];
        hash *= 0x100000001B3ULL;
    }
    return hash;
}

typedef struct {
    int point;                         /* 1: a point query at t0 (n is 1), 0: a span */
    const char *outlet;
    int64_t t0, t1, n;
} Query;

/* The same shapes for every outlet. */
static const struct { int point; int64_t t0, t1, n; } SHAPES[] = {
    {0, 0, 1000000000LL, 4800},                      /* one second at 4.8 kHz */
    {0, -250000000LL, 750000000LL, 960},             /* starts before t = 0 */
    {0, 1000000000LL, 0, 1000},                      /* reversed */
    {0, 123456789LL, 123456789LL, 10},               /* all ten samples at one time */
    {0, 0, 1500000000LL, 65536},                     /* the biggest span, a second and a half */
    {0, 2500000000LL, 2500100000LL, 7},              /* seven samples, a tenth of a millisecond */
    {1, 777777777LL, 0, 1},                          /* points */
    {1, -42000000LL, 0, 1},
    {0, 3000000000LL, 3000100000LL, 480},            /* far from the start: the filter must go a long way */
};
#define N_SHAPES ((int)(sizeof SHAPES / sizeof SHAPES[0]))

static int make_queries(Query *queries, const char *const *outlets)
{
    int count = 0, o, s;
    for (o = 0; outlets[o]; o++)
        for (s = 0; s < N_SHAPES; s++) {
            Query *q = &queries[count++];
            q->point = SHAPES[s].point;
            q->outlet = outlets[o];
            q->t0 = SHAPES[s].t0;
            q->t1 = SHAPES[s].t1;
            q->n = SHAPES[s].n;
        }
    return count;
}

/* The hash of one query's floats, or 0 and a status in *status. Safe to call from any thread (it checks nothing: the caller does). */
static uint64_t query_hash(CanopyInstance *instance, const Query *q, int32_t *status, int *clean)
{
    Guarded g = guarded_new(q->n);
    uint64_t hash = 0;
    *status = q->point ? canopy_instance_read_at(instance, q->outlet, q->t0, g.data) : canopy_instance_read_span(instance, q->outlet, q->t0, q->t1, q->n, g.data);
    *clean = guarded_guards_intact(&g) && guarded_unwritten(&g) == 0;
    if (*status == CANOPY_OK) hash = fnv_add(FNV_START, g.data, (size_t)q->n * sizeof(float));
    guarded_free(&g);
    return hash;
}

static uint64_t checked_hash(CanopyInstance *instance, const Query *q)
{
    int32_t status;
    int clean;
    uint64_t hash = query_hash(instance, q, &status, &clean);
    CHECK_INT(status, CANOPY_OK);
    CHECK(clean);
    return hash;
}

/* ---- the files ---- */

static char wav_path[MAX_PATH + 64];

/* 16-bit stereo, 44100 Hz, 16317 frames of two integer formulas (a saw, and a noisy square-ish one): the same bytes in every run. */
static void make_wav(void)
{
    FILE *file;
    uint32_t frames = 16317, data_bytes = frames * 4u, rate = 44100, riff = 36u + data_bytes, fmt = 16, byte_rate = rate * 4u, k;
    uint16_t tag = 1, channels = 2, block = 4, bits = 16;
    DWORD n = GetTempPathA(MAX_PATH, wav_path);
    snprintf(wav_path + n, 64, "canopy_determinism_%lu.wav", (unsigned long)GetCurrentProcessId());
    file = fopen(wav_path, "wb");
    CHECK(file != NULL);
    if (!file) return;
    fwrite("RIFF", 1, 4, file); fwrite(&riff, 4, 1, file); fwrite("WAVEfmt ", 1, 8, file); fwrite(&fmt, 4, 1, file);
    fwrite(&tag, 2, 1, file); fwrite(&channels, 2, 1, file); fwrite(&rate, 4, 1, file); fwrite(&byte_rate, 4, 1, file);
    fwrite(&block, 2, 1, file); fwrite(&bits, 2, 1, file); fwrite("data", 1, 4, file); fwrite(&data_bytes, 4, 1, file);
    for (k = 0; k < frames; k++) {
        int16_t left = (int16_t)((int32_t)((k * 37u) % 65536u) - 32768), right = (int16_t)(((int32_t)((k * k) % 1000u) - 500) * 60);
        fwrite(&left, 2, 1, file);
        fwrite(&right, 2, 1, file);
    }
    fclose(file);
}

/* ---- the graphs ---- */

static void in_node(Rig *rig, int64_t id, const char *name)
{
    rig_node(rig, id, "boundary_inlet");
    CHECK_INT(canopy_graph_set_string(rig->graph, id, "name", name), CANOPY_OK);
}

static void out_node(Rig *rig, int64_t id, const char *name)
{
    rig_node(rig, id, "boundary_outlet");
    CHECK_INT(canopy_graph_set_string(rig->graph, id, "name", name), CANOPY_OK);
}

static void knob(Rig *rig, int64_t id, const char *inlet, float value)
{
    CHECK_INT(canopy_graph_set_knob(rig->graph, id, inlet, value), CANOPY_OK);
}

static void set_filter(Rig *rig, int64_t id, int64_t rate, int64_t seconds, double initial)
{
    CHECK_INT(canopy_graph_set_int(rig->graph, id, "internal_sampling_rate", rate), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, id, "checkpoint_seconds", seconds), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig->graph, id, "initial", initial), CANOPY_OK);
}

static void build_saw(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    out_node(rig, 2, "out");
    rig_connect(rig, 1, "out", 2, "in");
}

static void build_gain_chain(Rig *rig)
{
    in_node(rig, 1, "in");
    rig_node(rig, 2, "test.gain");
    rig_node(rig, 3, "test.gain");
    out_node(rig, 4, "out");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    rig_connect(rig, 3, "out", 4, "in");
    knob(rig, 2, "gain", 0.5f);
    knob(rig, 3, "gain", -0.75f);
}

static void after_gain_chain(Rig *rig)
{
    CHECK_INT(canopy_engine_set_boundary(rig->engine, "in", 0.7f), CANOPY_OK);
}

static void build_sum(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test.jitter");
    rig_node(rig, 3, "test.sum");
    out_node(rig, 4, "out");
    rig_connect(rig, 1, "out", 3, "a");
    rig_connect(rig, 2, "out", 3, "b");
    rig_connect(rig, 3, "out", 4, "in");
}

static void build_shift(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test.shift");
    out_node(rig, 3, "out");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "shift", 1234567), CANOPY_OK);
}

static void build_time(Rig *rig)
{
    rig_node(rig, 1, "test.time");
    out_node(rig, 2, "out");
    out_node(rig, 3, "out2");
    rig_connect(rig, 1, "a", 2, "in");
    rig_connect(rig, 1, "b", 3, "in");
}

static void build_knob(Rig *rig)
{
    rig_node(rig, 1, "test.gain");
    out_node(rig, 2, "out");
    rig_connect(rig, 1, "out", 2, "in");
    knob(rig, 1, "in", 0.3f);                         /* nothing connected: the knobs give the values */
    knob(rig, 1, "gain", -0.6f);
}

static void build_filter_saw(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test_filter");
    out_node(rig, 3, "out");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    set_filter(rig, 2, 8000, 1, 0.25);
    knob(rig, 2, "coef", -0.9995f);                 /* a long memory (the pole is at 0.9995 of the way back): what it was asked before would show */
}

static void build_filter_default(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test_filter");
    out_node(rig, 3, "out");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    knob(rig, 2, "coef", -0.9999f);                   /* the other settings are the defaults: 48000 Hz, a checkpoint every 10 s, starting from 0 */
}

static void build_file(Rig *rig)
{
    rig_node(rig, 1, "file_read");
    out_node(rig, 2, "l");
    out_node(rig, 3, "r");
    rig_connect(rig, 1, "left", 2, "in");
    rig_connect(rig, 1, "right", 3, "in");
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "path", wav_path), CANOPY_OK);
}

static void build_file_filter(Rig *rig)
{
    rig_node(rig, 1, "file_read");
    rig_node(rig, 2, "test_filter");
    out_node(rig, 3, "out");
    rig_connect(rig, 1, "left", 2, "in");
    rig_connect(rig, 2, "out", 3, "in");
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "path", wav_path), CANOPY_OK);
    set_filter(rig, 2, 22050, 1, 0.1);
    knob(rig, 2, "coef", -0.999f);
}

static void build_special(Rig *rig)
{
    in_node(rig, 1, "a");
    in_node(rig, 2, "b");
    in_node(rig, 3, "c");
    out_node(rig, 4, "oa");
    out_node(rig, 5, "ob");
    out_node(rig, 6, "oc");
    rig_connect(rig, 1, "out", 4, "in");
    rig_connect(rig, 2, "out", 5, "in");
    rig_connect(rig, 3, "out", 6, "in");
}

static float float_from_bits(uint32_t bits)
{
    float value;
    memcpy(&value, &bits, sizeof value);
    return value;
}

static void after_special(Rig *rig)                    /* what no formula would give: +infinity, minus zero, and a quiet NaN with a payload */
{
    CHECK_INT(canopy_engine_set_boundary(rig->engine, "a", float_from_bits(0x7F800000u)), CANOPY_OK);
    CHECK_INT(canopy_engine_set_boundary(rig->engine, "b", float_from_bits(0x80000000u)), CANOPY_OK);
    CHECK_INT(canopy_engine_set_boundary(rig->engine, "c", float_from_bits(0x7FC01234u)), CANOPY_OK);
}

static void build_fanout(Rig *rig)
{
    rig_node(rig, 1, "test.saw");
    rig_node(rig, 2, "test.gain");
    rig_node(rig, 3, "test.gain");
    rig_node(rig, 4, "test.sum");
    out_node(rig, 5, "out");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 1, "out", 3, "in");
    rig_connect(rig, 2, "out", 4, "a");
    rig_connect(rig, 3, "out", 4, "b");
    rig_connect(rig, 4, "out", 5, "in");
    knob(rig, 2, "gain", 0.5f);
    knob(rig, 3, "gain", -0.25f);
}

typedef struct {
    const char *name;
    void (*build)(Rig *rig);
    void (*after)(Rig *rig);           /* boundary values, written after the install (or NULL) */
    const char *outlets[4];
    uint64_t golden;                   /* the recorded hash (see the head of this file) */
} Case;

/* The recorded hashes: the FNV-1a of the hashes of every query of the case, in order (CANOPY_RECORD=1 prints this table). */
static const Case CASES[] = {
    {"saw", build_saw, NULL, {"out", NULL}, 0xfd2ded0b2a2c2eb0ULL},
    {"gain chain with a boundary value", build_gain_chain, after_gain_chain, {"out", NULL}, 0xd0cdb875a4e826caULL},
    {"sum of a saw and a jitter", build_sum, NULL, {"out", NULL}, 0x6e73dab458fac8ceULL},
    {"shift looking ahead", build_shift, NULL, {"out", NULL}, 0xb3f2f4d0fbe274c2ULL},
    {"time as a float", build_time, NULL, {"out", "out2", NULL}, 0x6e07b500a0378c2aULL},
    {"knobs only", build_knob, NULL, {"out", NULL}, 0xc94b006ee93f885dULL},
    {"filter of a saw, 8 kHz, checkpoints every second", build_filter_saw, NULL, {"out", NULL}, 0x2fae8f8356b68255ULL},
    {"filter with its defaults", build_filter_default, NULL, {"out", NULL}, 0x84e47ffc028cb3d9ULL},
    {"a 16-bit stereo file at 44.1 kHz", build_file, NULL, {"l", "r", NULL}, 0x47a404c822e9354aULL},
    {"the file through a filter", build_file_filter, NULL, {"out", NULL}, 0xd316fcf787de9082ULL},
    {"infinity, minus zero and a NaN through boundary nodes", build_special, after_special, {"oa", "ob", "oc", NULL}, 0x6a808aa0837f3ca0ULL},
    {"fan-out and a sum", build_fanout, NULL, {"out", NULL}, 0xeb1496d0085c66fdULL},
};
#define N_CASES ((int)(sizeof CASES / sizeof CASES[0]))

static void open_case(Rig *rig, const Case *c)
{
    rig_open(rig);
    c->build(rig);
    rig_install(rig);
    if (c->after) c->after(rig);
}

static uint64_t case_hash(const uint64_t *hashes, int count)
{
    return fnv_add(FNV_START, hashes, (size_t)count * sizeof hashes[0]);
}

/* ---- recorded outputs ---- */

static void test_c_recorded_outputs_of_whole_graphs_are_bit_exact_in_every_build(void)
{
    int i, q, record = getenv("CANOPY_RECORD") != NULL;
    make_wav();
    if (record) printf("\nRECORD table for tests/c/test_determinism.c (paste over the 0x0ULL values, in this order):\n");
    for (i = 0; i < N_CASES; i++) {
        Rig rig;
        Query queries[MAX_QUERIES];
        uint64_t hashes[MAX_QUERIES], hash;
        int count = make_queries(queries, CASES[i].outlets);
        open_case(&rig, &CASES[i]);
        for (q = 0; q < count; q++) hashes[q] = checked_hash(rig.instance, &queries[q]);
        hash = case_hash(hashes, count);
        if (record) printf("RECORD    0x%016llxULL,   /* %s */\n", (unsigned long long)hash, CASES[i].name);
        else if (hash != CASES[i].golden) {
            CHECK(hash == CASES[i].golden);
            printf("    case \"%s\": hash 0x%016llx, recorded 0x%016llx\n", CASES[i].name, (unsigned long long)hash, (unsigned long long)CASES[i].golden);
        }
        rig_close(&rig);
    }
    remove(wav_path);
    CHECK_HEAP();
}

/* ---- the same bits however and by whomever they are asked ---- */

typedef struct {
    CanopyEngine *engine;
    const Query *queries;
    int count, rotate;
    uint64_t *hashes;                  /* out: the hash of each query, in the order of `queries` */
    int bad;
} Asker;

static unsigned __stdcall asker_main(void *argument)
{
    Asker *asker = (Asker *)argument;
    CanopyInstance *instance = canopy_engine_new_instance(asker->engine);
    int step;
    if (!instance) {
        asker->bad = 1;
        return 0;
    }
    for (step = 0; step < asker->count; step++) {
        int q = (step + asker->rotate) % asker->count, clean;
        int32_t status;
        asker->hashes[q] = query_hash(instance, &asker->queries[q], &status, &clean);
        if (status != CANOPY_OK || !clean) asker->bad = 1;
    }
    canopy_instance_free(instance);
    return 0;
}

static void test_c_every_recorded_graph_gives_the_same_bits_asked_again_in_reverse_by_a_cold_instance_and_by_other_threads(void)
{
    int i, q, t;
    make_wav();
    for (i = 0; i < N_CASES; i++) {
        Rig rig;
        Query queries[MAX_QUERIES];
        uint64_t first[MAX_QUERIES], again[MAX_QUERIES], cold[MAX_QUERIES], threads_hashes[THREADS][MAX_QUERIES];
        Asker askers[THREADS];
        HANDLE handles[THREADS];
        CanopyInstance *cold_instance;
        int count = make_queries(queries, CASES[i].outlets);
        open_case(&rig, &CASES[i]);
        for (q = 0; q < count; q++) first[q] = checked_hash(rig.instance, &queries[q]);
        for (q = 0; q < count; q++) again[q] = checked_hash(rig.instance, &queries[q]);                 /* the same instance, asked again */
        cold_instance = canopy_engine_new_instance(rig.engine);
        CHECK(cold_instance != NULL);
        if (cold_instance) {
            for (q = count - 1; q >= 0; q--) cold[q] = checked_hash(cold_instance, &queries[q]);        /* another, cold, in the opposite order */
            canopy_instance_free(cold_instance);
        }
        for (t = 0; t < THREADS; t++) {                                                              /* and three in threads of their own, each in its own order */
            askers[t].engine = rig.engine;
            askers[t].queries = queries;
            askers[t].count = count;
            askers[t].rotate = t * (count / THREADS + 1);
            askers[t].hashes = threads_hashes[t];
            askers[t].bad = 0;
            handles[t] = (HANDLE)_beginthreadex(NULL, 0, asker_main, &askers[t], 0, NULL);
        }
        for (t = 0; t < THREADS; t++) {
            WaitForSingleObject(handles[t], INFINITE);
            CloseHandle(handles[t]);
        }
        for (q = 0; q < count; q++) {
            CHECK(again[q] == first[q]);
            CHECK(cold[q] == first[q]);
            for (t = 0; t < THREADS; t++) CHECK(threads_hashes[t][q] == first[q]);
            if (again[q] != first[q] || cold[q] != first[q])
                printf("    case \"%s\" query %d (%s %s [%lld, %lld) n=%lld): first 0x%016llx, again 0x%016llx, cold 0x%016llx\n", CASES[i].name, q,
                       queries[q].point ? "point" : "span", queries[q].outlet, (long long)queries[q].t0, (long long)queries[q].t1, (long long)queries[q].n,
                       (unsigned long long)first[q], (unsigned long long)again[q], (unsigned long long)cold[q]);
        }
        for (t = 0; t < THREADS; t++) CHECK(!askers[t].bad);
        rig_close(&rig);
    }
    remove(wav_path);
    CHECK_HEAP();
}

/* ---- what the filter has been asked never shows ---- */

typedef struct { uint64_t state; } Rng;

static uint64_t rng_next(Rng *rng)
{
    uint64_t x = rng->state += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

static int64_t rng_between(Rng *rng, int64_t low, int64_t high)       /* low .. high inclusive */
{
    return low + (int64_t)(rng_next(rng) % (uint64_t)(high - low + 1));
}

/* A query at random: a point now and then, a span that may run backwards, start before 0 or collapse onto one time. */
static Query random_query(Rng *rng, const char *outlet, int64_t horizon_ns, int64_t max_n)
{
    Query q;
    int kind = (int)(rng_next(rng) % 10);
    q.outlet = outlet;
    q.point = kind == 0;
    q.t0 = rng_between(rng, -2000000000LL, horizon_ns);
    q.t1 = kind == 1 ? q.t0 : rng_between(rng, -2000000000LL, horizon_ns);
    q.n = q.point ? 1 : rng_between(rng, 1, max_n);
    return q;
}

static void test_c_random_queries_of_a_long_lived_instance_equal_the_answers_of_fresh_instances_for_the_filter_graphs(void)
{
    static const struct { int index; int64_t horizon_ns, max_n; int queries; } PLAN[] = {
        {6, 12000000000LL, 400, 80},             /* filter of a saw at 8 kHz, checkpoints every second */
        {7, 2500000000LL, 300, 25},              /* the defaults: 48 kHz, so a short horizon (every fresh instance starts from the first sample) */
        {9, 1500000000LL, 200, 25},              /* the file through a filter at 22.05 kHz */
    };
    int p, i;
    make_wav();
    for (p = 0; p < (int)(sizeof PLAN / sizeof PLAN[0]); p++) {
        Rig rig;
        Rng rng;
        int diffs = 0;
        open_case(&rig, &CASES[PLAN[p].index]);
        rng.state = 20261006u + (uint64_t)p;
        for (i = 0; i < PLAN[p].queries; i++) {
            Query q = random_query(&rng, CASES[PLAN[p].index].outlets[0], PLAN[p].horizon_ns, PLAN[p].max_n);
            CanopyInstance *fresh = canopy_engine_new_instance(rig.engine);
            uint64_t warm_hash = checked_hash(rig.instance, &q), fresh_hash = fresh ? checked_hash(fresh, &q) : 0;
            CHECK(fresh != NULL);
            if (warm_hash != fresh_hash) {
                diffs++;
                if (diffs <= 3)
                    printf("    case \"%s\": %s [%lld, %lld) n=%lld after %d earlier queries: long-lived 0x%016llx, fresh 0x%016llx\n", CASES[PLAN[p].index].name,
                           q.point ? "point" : "span", (long long)q.t0, (long long)q.t1, (long long)q.n, i, (unsigned long long)warm_hash,
                           (unsigned long long)fresh_hash);
            }
            if (fresh) canopy_instance_free(fresh);
        }
        CHECK_INT(diffs, 0);
        rig_close(&rig);
    }
    remove(wav_path);
    CHECK_HEAP();
}

/* ---- installing again, and changes that cannot matter ---- */

static void test_c_installing_the_same_description_again_or_changing_what_cannot_matter_does_not_change_a_bit(void)
{
    enum { CHANGES = 7 };
    const Case *c = &CASES[6];                 /* the filter of a saw at 8 kHz with checkpoints every second */
    Rig rig;
    Query queries[MAX_QUERIES];
    uint64_t base[MAX_QUERIES];
    int count = make_queries(queries, c->outlets), q, change;
    open_case(&rig, c);
    for (q = 0; q < count; q++) base[q] = checked_hash(rig.instance, &queries[q]);
    for (change = 0; change < CHANGES; change++) {
        CanopyInstance *fresh;
        switch (change) {
        case 0: break;                                                                           /* the same description again */
        case 1: break;                                                                           /* and again */
        case 2: CHECK_INT(canopy_graph_set_int(rig.graph, 2, "checkpoint_seconds", 3), CANOPY_OK); break;          /* checkpoints elsewhere */
        case 3: CHECK_INT(canopy_graph_set_int(rig.graph, 2, "checkpoint_seconds", 3600), CANOPY_OK); break;       /* (a thousand hours: practically none) */
        case 4: CHECK_INT(canopy_graph_set_int(rig.graph, 2, "checkpoint_seconds", 1), CANOPY_OK); break;
        case 5: rig_node(&rig, 50, "test.const"); break;                                         /* a node nothing is connected to */
        case 6: rig_node(&rig, 51, "test.gain"); knob(&rig, 51, "gain", 0.123f); break;
        }
        CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
        for (q = 0; q < count; q++) CHECK(checked_hash(rig.instance, &queries[q]) == base[q]);       /* the instance that had history adopts it and answers the same */
        fresh = canopy_engine_new_instance(rig.engine);
        CHECK(fresh != NULL);
        if (fresh) {
            for (q = count - 1; q >= 0; q--) CHECK(checked_hash(fresh, &queries[q]) == base[q]);     /* so does one that never knew the old graph */
            canopy_instance_free(fresh);
        }
        canopy_engine_collect(rig.engine);
    }
    rig_close(&rig);
    CHECK_HEAP();
}

/* ---- a span is its points ---- */

static void test_c_a_span_is_the_point_query_at_each_of_its_sample_times_for_every_recorded_graph(void)
{
    int i, q;
    long long compared = 0, different = 0;
    make_wav();
    for (i = 0; i < N_CASES; i++) {
        Rig rig;
        Query queries[MAX_QUERIES];
        int count = make_queries(queries, CASES[i].outlets);
        open_case(&rig, &CASES[i]);
        for (q = 0; q < count; q++) {
            Guarded g;
            int64_t k;
            if (queries[q].point || queries[q].n > 1000) continue;
            g = guarded_new(queries[q].n);
            CHECK_INT(canopy_instance_read_span(rig.instance, queries[q].outlet, queries[q].t0, queries[q].t1, queries[q].n, g.data), CANOPY_OK);
            for (k = 0; k < queries[q].n; k++) {
                int64_t t = 0;
                float point = 0.0f;
                CHECK_INT(canopy_sample_time(queries[q].t0, queries[q].t1, queries[q].n, k, &t), CANOPY_OK);
                CHECK_INT(canopy_instance_read_at(rig.instance, queries[q].outlet, t, &point), CANOPY_OK);
                compared++;
                if (float_bits(point) != float_bits(g.data[k])) {
                    different++;
                    if (different <= 3)
                        printf("    case \"%s\" %s: sample %lld of [%lld, %lld) n=%lld is %.9g in the span and %.9g as a point at %lld ns\n", CASES[i].name,
                               queries[q].outlet, (long long)k, (long long)queries[q].t0, (long long)queries[q].t1, (long long)queries[q].n,
                               (double)g.data[k], (double)point, (long long)t);
                }
            }
            guarded_free(&g);
        }
        rig_close(&rig);
    }
    remove(wav_path);
    CHECK(compared > 10000);
    CHECK_INT(different, 0);
    CHECK_HEAP();
}

/* ---- the recorded outputs are right as well as stable ---- */

/* The answer a case must give by a formula that is written here and not taken from the library (the graphs of pointwise test nodes; the filters and the
   file are checked against independent models in tests/python/test_filter.py and test_fileread.py). 0 if the case has no formula. */
static int expected_bits(int index, const char *outlet, int64_t t, uint32_t *bits)
{
    float value;
    switch (index) {
    case 0: value = support_saw(t); break;                                                       /* saw */
    case 1: value = (0.7f * 0.5f) * -0.75f; break;                                               /* the boundary value through two gains */
    case 2: value = support_saw(t) + support_jitter(t); break;                                   /* sum */
    case 3: value = support_saw(t + 1234567); break;                                             /* shift */
    case 4: value = strcmp(outlet, "out") == 0 ? (float)t : 2.0f * (float)t; break;              /* time */
    case 5: value = 0.3f * -0.6f; break;                                                         /* knobs only: in * gain */
    case 11: {                                                                                   /* fan-out and a sum */
        float s = support_saw(t);
        float half = s * 0.5f, quarter = s * -0.25f;
        value = half + quarter;
        break;
    }
    case 10:                                                                                     /* special values: exactly the bits written */
        *bits = strcmp(outlet, "oa") == 0 ? 0x7F800000u : strcmp(outlet, "ob") == 0 ? 0x80000000u : 0x7FC01234u;
        return 1;
    default:
        return 0;
    }
    *bits = float_bits(value);
    return 1;
}

static void test_c_the_recorded_graphs_answer_what_their_formulas_say_and_none_of_them_is_silent(void)
{
    int i, q, formulas = 0;
    make_wav();
    for (i = 0; i < N_CASES; i++) {
        Rig rig;
        Query queries[MAX_QUERIES];
        int count = make_queries(queries, CASES[i].outlets), any_nonzero = 0;
        open_case(&rig, &CASES[i]);
        for (q = 0; q < count; q++) {
            const Query *query = &queries[q];
            Guarded g = guarded_new(query->n);
            int64_t s;
            int32_t status = query->point ? canopy_instance_read_at(rig.instance, query->outlet, query->t0, g.data)
                                          : canopy_instance_read_span(rig.instance, query->outlet, query->t0, query->t1, query->n, g.data);
            CHECK_INT(status, CANOPY_OK);
            for (s = 0; s < query->n; s++) {
                int64_t t = query->t0;
                uint32_t bits = 0;
                if (!query->point) CHECK_INT(canopy_sample_time(query->t0, query->t1, query->n, s, &t), CANOPY_OK);
                if (float_bits(g.data[s]) != 0u) any_nonzero = 1;
                if (expected_bits(i, query->outlet, t, &bits)) {
                    formulas++;
                    if (bits != float_bits(g.data[s])) {
                        CHECK(bits == float_bits(g.data[s]));
                        printf("    case \"%s\" %s: sample %lld of [%lld, %lld) n=%lld (time %lld) is 0x%08x, the formula says 0x%08x\n", CASES[i].name, query->outlet,
                               (long long)s, (long long)query->t0, (long long)query->t1, (long long)query->n, (long long)t, float_bits(g.data[s]), bits);
                        break;
                    }
                }
            }
            guarded_free(&g);
        }
        CHECK(any_nonzero);                                       /* (a recording of silence, say of a file that did not load, would pin nothing) */
        rig_close(&rig);
    }
    remove(wav_path);
    CHECK(formulas > 100000);
    CHECK_HEAP();
}

void register_test_determinism(void)
{
    RUN(test_c_recorded_outputs_of_whole_graphs_are_bit_exact_in_every_build);
    RUN(test_c_the_recorded_graphs_answer_what_their_formulas_say_and_none_of_them_is_silent);
    RUN(test_c_every_recorded_graph_gives_the_same_bits_asked_again_in_reverse_by_a_cold_instance_and_by_other_threads);
    RUN(test_c_random_queries_of_a_long_lived_instance_equal_the_answers_of_fresh_instances_for_the_filter_graphs);
    RUN(test_c_installing_the_same_description_again_or_changing_what_cannot_matter_does_not_change_a_bit);
    RUN(test_c_a_span_is_the_point_query_at_each_of_its_sample_times_for_every_recorded_graph);
}
