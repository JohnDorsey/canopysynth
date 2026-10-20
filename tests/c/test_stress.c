/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The multi-thread stress (plan step 13): everything a host and an editor do at once, one engine, with every answer checked.

   Threads (all at once, for a few seconds in the test suite and as long as asked in tests/stress/stress_main.c):
     installer   compiles and installs a new graph every few milliseconds ("compile-and-swap"), now and then a graph that cannot be compiled (which must change
                 nothing), presses "open" on the file node after replacing its file, and collects.
     writers     four threads, one per boundary inlet, each writing a value that follows a known sequence as fast as it can.
     knob        writes the live knob of one gain node, and a knob of the preview.
     readers     each with an instance of its own, ask for spans (1 to 65536 samples, forward, reversed, empty, negative, enormous) and points through boundary
                 outlets; the last reader sleeps between queries on purpose, so that it adopts many graphs at once.
     lifecycle   makes an instance, asks it a few questions and frees it, over and over (the engine's lock taken exclusively, packages made and thrown away).
     info        reads the listing of the boundary nodes, node messages, the knob, the preview's state and warning, while all that goes on.
     ui          presses the preview node's Play and Pause, moves its time and switches its device (miniaudio's null backend, an audio thread of its own).
   Every graph is a function of its serial number (`spec_for`): which boundary inlet feeds which outlet, how many gains are in a chain (so that the scratch arena
   changes size), constants, whether the preview node is there. Values are made so that float32 arithmetic is exact (gains that are powers of two, whole numbers
   below 2^24), so what a query answers can be worked out exactly: a reader notes, without any lock, the range of graph versions and of write sequence numbers an
   answer may have come from (the installer and the writers publish counters before and after what they do), and the answer must fit one of them. The filter
   (not real-time safe, with checkpoints) must answer bit for bit what a quiet engine answered before the stress started, whatever else goes on and whichever
   checkpoint interval the graph of the moment sets. A span of one constant source must be constant (one file, one boundary value, never a mixture). The
   listing of the boundary nodes must always be complete and in order. At the end every thread stops, every instance is freed, the engine is freed and every
   allocation must have been returned. A watchdog stops the program with a message if nothing at all moves for 20 seconds. */
#include <math.h>
#include <process.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "support.h"
#include "stress.h"

#define WRITERS 4                     /* boundary inlets b0..b3, node IDs 10..13 */
#define OUTLETS 7                     /* boundary outlets o0..o6, node IDs 20..26 */
#define MAX_VERSIONS 256              /* the most graph versions an answer may be checked against (a wider range is counted as unchecked) */
#define VALUE_PERIOD 1048576LL        /* the writers' values go 1, 2, ... 2^20 and round again: whole numbers, exact with a gain of a power of two */
#define FILTER_SHAPES 6
#define PROBLEMS_SHOWN 12

/* ---- the graph of a version ---- */

/* A version of the graph. What an answer can be depends on three kinds of thing that behave differently while a graph is installed (design section 5,
   canopy_install.c): the wiring and the settings are in the compiled graph, which an instance adopts at the start of its next query, so a query sees one
   whole version of them; the knob positions are in the engine, and an install writes the new ones BEFORE it publishes the graph, so a query of an instance
   that still runs the old graph may read the knob of the new one (and, for a chain of nodes, the knob of each node of a different version); the boundary
   values are written by the writer threads at any time. So the gain of o0, whose knob changes with every version, is checked as "wiring of one version in
   the window, knob of one version in the window", and the gains of the chain that feeds o2 are made properties of their node's ID (a node with ID
   1000 + 10 * i + k always has the knob KNOBS[k] in every version it is in), which gives a chain whose answer is exact. */
typedef struct {
    int p0, p1, p2;                   /* which of b0..b2 feeds o0, o1 and o2 */
    int depth;                        /* the gains in the chain that feeds o2 (1 to 4) */
    int chain_k[4];                   /* the chain's gain i is KNOBS[chain_k[i]] */
    int g0_k, k70_k;                  /* the knob positions (indexes into KNOBS) the version sets for o0's gain and for the live knob of o3's gain */
    int c1, c6;                       /* whole constants */
    int preview, filter_seconds, center_from_filter, other_device;
} Spec;

static const float KNOBS[5] = {1.0f, 0.5f, 0.25f, -0.5f, -1.0f};

static uint64_t mix64(uint64_t x)
{
    x += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

static Spec spec_for(long long serial)
{
    uint64_t h = mix64((uint64_t)serial * 7919u + 13u), h2 = mix64(h);
    Spec s;
    int i;
    s.p0 = (int)(h % 3);
    s.p1 = (int)((h >> 8) % 3);
    s.p2 = (int)((h >> 16) % 3);
    s.depth = 1 + (int)((h >> 24) % 4);
    s.g0_k = (int)((h >> 28) % 5);
    for (i = 0; i < 4; i++) s.chain_k[i] = (int)((h2 >> (4 * i)) % 5);
    s.k70_k = (int)((h >> 32) % 5);
    s.c1 = (int)((h >> 36) % 100);
    s.c6 = (int)((h2 >> 20) % 100);
    s.preview = serial == 1 || (h >> 44) % 5 != 0;
    s.filter_seconds = 1 + (int)((h >> 48) % 2);
    s.center_from_filter = (int)((h >> 52) & 1);
    s.other_device = (int)((h2 >> 40) % 10 == 0);
    return s;
}

/* ---- the shared state ---- */

typedef struct {
    CanopyEngine *engine;
    CanopyRegistry *registry;
    StressOptions options;
    atomic_int stop;
    atomic_llong installing_serial, installed_serial;                /* published by the installer, read by the readers without any lock */
    atomic_llong intent_seq[WRITERS], done_seq[WRITERS];             /* published by each writer before and after a write */
    atomic_llong progress;                                           /* bumped by every thread's loop: the watchdog's heartbeat */
    atomic_llong problems;
    atomic_llong queries, span_queries, point_queries, unchecked, installs, bad_installs, opens, collects, boundary_writes, knob_writes;
    atomic_llong instance_cycles, info_calls, preview_actions, playing_seen, file_a_seen, file_b_seen, max_spread;
    atomic_llong histogram[64], small_max_ns;
    CRITICAL_SECTION report_lock;
    char file_path[MAX_PATH + 64];
    int64_t filter_t0[FILTER_SHAPES], filter_t1[FILTER_SHAPES], filter_n[FILTER_SHAPES];
    float *filter_reference[FILTER_SHAPES];
    LARGE_INTEGER frequency;
} Stress;

static Stress S;

static void problem(const char *format, ...)
{
    va_list arguments;
    long long number = atomic_fetch_add(&S.problems, 1) + 1;
    if (number <= PROBLEMS_SHOWN) {
        EnterCriticalSection(&S.report_lock);
        printf("    stress problem %lld: ", number);
        va_start(arguments, format);
        vprintf(format, arguments);
        va_end(arguments);
        printf("\n");
        fflush(stdout);
        LeaveCriticalSection(&S.report_lock);
    }
    if (number >= PROBLEMS_SHOWN) atomic_store(&S.stop, 1);
}

static void beat(void)
{
    atomic_fetch_add(&S.progress, 1);
}

typedef struct { uint64_t state; } Random;

static uint64_t draw(Random *r)
{
    r->state += 0x9E3779B97F4A7C15ULL;
    return mix64(r->state);
}

static uint32_t draw_below(Random *r, uint32_t n)
{
    return (uint32_t)((draw(r) >> 33) % n);
}

/* ---- the values the writers write ---- */

static double value_of(long long sequence)
{
    return sequence == 0 ? 0.0 : (double)((sequence - 1) % VALUE_PERIOD + 1);
}

/* Whether the whole number `c` is the value of a write whose sequence number lies in [lo, hi]. */
static int sequence_possible(double c, long long lo, long long hi)
{
    long long target, base, delta;
    if (c == 0.0) return lo <= 0;
    if (c < 1.0 || c > (double)VALUE_PERIOD) return 0;
    target = (long long)c - 1;
    base = lo > 1 ? lo : 1;
    delta = (((target - (base - 1)) % VALUE_PERIOD) + VALUE_PERIOD) % VALUE_PERIOD;
    return base + delta <= hi;
}

typedef struct { int writer; double scale, offset; } Affine;

/* What outlets o1 and o2 answer in a version (o0's knob is not a property of the version alone: see Spec): scale * (the value of a write of the writer) + offset. */
static Affine affine_for(int outlet, const Spec *s)
{
    Affine a;
    int i;
    a.offset = 0.0;
    if (outlet == 1) {
        a.writer = s->p1;
        a.scale = 1.0;
        a.offset = s->c1;
    } else {
        a.writer = s->p2;
        a.scale = 1.0;
        for (i = 0; i < s->depth; i++) a.scale *= (double)KNOBS[s->chain_k[i]];
    }
    return a;
}

static int affine_possible(double y, const Affine *a, long long lo, long long hi)
{
    double c = (y - a->offset) / a->scale;
    return c == floor(c) && sequence_possible(c, lo, hi);
}

/* ---- the graph of a version ---- */

static void add_node(CanopyGraph *g, int64_t id, const char *type)
{
    if (canopy_graph_add_node(g, id, type) != CANOPY_OK) problem("the graph description ran out of memory");
}

static void wire(CanopyGraph *g, int64_t from, const char *outlet, int64_t to, const char *inlet)
{
    if (canopy_graph_connect(g, from, outlet, to, inlet) != CANOPY_OK) problem("a connection could not be described");
}

static void knob_of(CanopyGraph *g, int64_t node, const char *inlet, float value)
{
    if (canopy_graph_set_knob(g, node, inlet, value) != CANOPY_OK) problem("a knob could not be described");
}

static CanopyGraph *build_graph(long long serial, int bad)
{
    CanopyGraph *g = canopy_graph_new();
    Spec s = spec_for(serial);
    char name[4] = {0, 0, 0, 0};
    int i;
    if (!g) {
        problem("no memory for a graph description");
        return NULL;
    }
    for (i = 0; i < WRITERS; i++) {
        name[0] = 'b';
        name[1] = (char)('0' + i);
        add_node(g, 10 + i, "boundary_inlet");
        canopy_graph_set_string(g, 10 + i, "name", name);
    }
    for (i = 0; i < OUTLETS; i++) {
        name[0] = 'o';
        name[1] = (char)('0' + i);
        add_node(g, 20 + i, "boundary_outlet");
        canopy_graph_set_string(g, 20 + i, "name", name);
    }
    add_node(g, 50, "test.gain");                                           /* o0 = g0 * b[p0] */
    knob_of(g, 50, "gain", KNOBS[s.g0_k]);
    wire(g, 10 + s.p0, "out", 50, "in");
    wire(g, 50, "out", 20, "in");
    add_node(g, 51, "test.sum");                                            /* o1 = b[p1] + c1 */
    add_node(g, 52, "test.const");
    canopy_graph_set_float(g, 52, "value", (double)s.c1);
    wire(g, 10 + s.p1, "out", 51, "a");
    wire(g, 52, "out", 51, "b");
    wire(g, 51, "out", 21, "in");
    for (i = 0; i < s.depth; i++) {                                    /* o2 = the product of the chain's gains * b[p2]: the scratch arena grows and shrinks */
        int64_t id = 1000 + 10 * i + s.chain_k[i], before = 1000 + 10 * (i - 1) + (i > 0 ? s.chain_k[i - 1] : 0);
        add_node(g, id, "test.gain");
        knob_of(g, id, "gain", KNOBS[s.chain_k[i]]);                    /* (the ID tells the knob: it is the same in every version that has the node) */
        wire(g, i == 0 ? 10 + s.p2 : before, "out", id, "in");
    }
    wire(g, 1000 + 10 * (s.depth - 1) + s.chain_k[s.depth - 1], "out", 22, "in");
    add_node(g, 70, "test.gain");                                           /* o3 = b3 * (the live knob) */
    knob_of(g, 70, "gain", KNOBS[s.k70_k]);
    wire(g, 13, "out", 70, "in");
    wire(g, 70, "out", 23, "in");
    add_node(g, 80, "file_read");                                           /* o4 = the file's left channel */
    canopy_graph_set_string(g, 80, "path", S.file_path);
    wire(g, 80, "left", 24, "in");
    add_node(g, 90, "test.saw");                                            /* o5 = the filter of the saw: the same in every version, whatever the checkpoint interval */
    add_node(g, 91, "test_filter");
    canopy_graph_set_int(g, 91, "internal_sampling_rate", 8000);
    canopy_graph_set_int(g, 91, "checkpoint_seconds", s.filter_seconds);
    canopy_graph_set_float(g, 91, "initial", 0.0);
    knob_of(g, 91, "coef", 0.0f);
    wire(g, 90, "out", 91, "in");
    wire(g, 91, "out", 25, "in");
    add_node(g, 100, "test.saw");                                           /* o6 = a saw plus c6, sample by sample */
    add_node(g, 101, "test.sum");
    add_node(g, 102, "test.const");
    canopy_graph_set_float(g, 102, "value", (double)s.c6);
    wire(g, 100, "out", 101, "a");
    wire(g, 102, "out", 101, "b");
    wire(g, 101, "out", 26, "in");
    if (s.preview) {
        add_node(g, 120, "realtime_preview");
        canopy_graph_set_string(g, 120, "device", s.other_device ? "NULL Playback Device" : "(system default)");
        wire(g, 50, "out", 120, "left");
        wire(g, 101, "out", 120, "right");
        if (s.center_from_filter) wire(g, 91, "out", 120, "center");
    }
    if (bad) add_node(g, 999, "no_such_node_type");                         /* a graph that cannot be compiled */
    return g;
}

/* ---- the file the file node reads: constant 0.25 (A) or 0.75 (B), one second at 8000 Hz ---- */

static void write_constant_file(const char *path, float value)
{
    FILE *file = fopen(path, "wb");
    uint32_t frames = 8000, data_bytes = frames * 8u, rate = 8000, riff = 36u + data_bytes, fmt = 16, byte_rate = rate * 8u, i;
    uint16_t tag = 3, channels = 2, block = 8, bits = 32;
    if (!file) {
        problem("the file could not be written");
        return;
    }
    fwrite("RIFF", 1, 4, file); fwrite(&riff, 4, 1, file); fwrite("WAVEfmt ", 1, 8, file); fwrite(&fmt, 4, 1, file);
    fwrite(&tag, 2, 1, file); fwrite(&channels, 2, 1, file); fwrite(&rate, 4, 1, file); fwrite(&byte_rate, 4, 1, file);
    fwrite(&block, 2, 1, file); fwrite(&bits, 2, 1, file); fwrite("data", 1, 4, file); fwrite(&data_bytes, 4, 1, file);
    for (i = 0; i < frames * 2; i++) fwrite(&value, 4, 1, file);
    fclose(file);
}

/* ---- one query, and what its answer must be ---- */

typedef struct {
    Random rng;
    int index;
    CanopyInstance *instance;
} Worker;

static const int64_t TIMES_ANY[][2] = {{0, 1000000000LL}, {-500000000LL, 500000000LL}, {3000000000LL, 0}, {123456789LL, 123456789LL},
                                       {4000000000000000000LL, 4000000000100000000LL}, {-4000000000100000000LL, -4000000000000000000LL}, {0, 1000000000000LL}};
static const int64_t TIMES_FILE[][2] = {{10000000LL, 900000000LL}, {900000000LL, 10000000LL}, {500000000LL, 500000000LL}, {200000000LL, 400000000LL}};
static const int64_t COUNTS[] = {1, 2, 7, 64, 100, 960, 4096, 65536};

static void count_latency(long long ns)
{
    int bucket = 0;
    long long previous;
    unsigned long long v = (unsigned long long)ns + 1;
    while (v > 1) {
        v >>= 1;
        bucket++;
    }
    atomic_fetch_add(&S.histogram[bucket], 1);
    previous = atomic_load(&S.small_max_ns);
    while (ns > previous && !atomic_compare_exchange_weak(&S.small_max_ns, &previous, ns)) {}
}

static void note_max(atomic_llong *where, long long value)
{
    long long previous = atomic_load(where);
    while (value > previous && !atomic_compare_exchange_weak(where, &previous, value)) {}
}

/* One checked query through `worker->instance`. */
static void do_query(Worker *w)
{
    int outlet = (int)draw_below(&w->rng, OUTLETS), point = draw_below(&w->rng, 5) == 0, i, shape = 0;
    int64_t t0, t1, n;
    long long vlo, vhi, lo[WRITERS], hi[WRITERS];
    char name[4] = {'o', (char)('0' + outlet), 0, 0};
    Guarded g;
    int32_t status;
    LARGE_INTEGER started, finished;
    long long ns;
    if (outlet == 5) {                                                  /* the filter: one of the shapes whose answer was worked out in advance */
        shape = (int)draw_below(&w->rng, FILTER_SHAPES);
        t0 = S.filter_t0[shape]; t1 = S.filter_t1[shape]; n = S.filter_n[shape];
        point = 0;
    } else {
        uint32_t k = draw_below(&w->rng, 64);
        const int64_t (*pool)[2] = outlet == 4 ? TIMES_FILE : TIMES_ANY;
        int pool_size = outlet == 4 ? (int)(sizeof TIMES_FILE / sizeof TIMES_FILE[0]) : (int)(sizeof TIMES_ANY / sizeof TIMES_ANY[0]);
        int pick = (int)draw_below(&w->rng, (uint32_t)pool_size);
        t0 = pool[pick][0]; t1 = pool[pick][1];
        n = point ? 1 : (k == 0 ? 65536 : COUNTS[draw_below(&w->rng, 7)]);          /* 65536 is rare: it costs the most */
    }
    g = guarded_new(n);
    vlo = atomic_load(&S.installed_serial);                              /* what the answer may have come from: counters read before the query... */
    for (i = 0; i < WRITERS; i++) lo[i] = atomic_load(&S.done_seq[i]);
    QueryPerformanceCounter(&started);
    status = point ? canopy_instance_read_at(w->instance, name, t0, g.data) : canopy_instance_read_span(w->instance, name, t0, t1, n, g.data);
    QueryPerformanceCounter(&finished);
    vhi = atomic_load(&S.installing_serial);                             /* ...and after it */
    for (i = 0; i < WRITERS; i++) hi[i] = atomic_load(&S.intent_seq[i]);
    ns = (finished.QuadPart - started.QuadPart) * 1000000000LL / S.frequency.QuadPart;
    if (n <= 64 && outlet != 5) count_latency(ns);                       /* (the filter is not realtime safe: it recomputes from a checkpoint, which takes as long as it takes) */
    atomic_fetch_add(&S.queries, 1);
    atomic_fetch_add(point ? &S.point_queries : &S.span_queries, 1);
    note_max(&S.max_spread, vhi - vlo + 1);
    if (status != CANOPY_OK) {
        problem("%s of %s [%lld, %lld) n=%lld: status %d", point ? "a point query" : "a span query", name, (long long)t0, (long long)t1, (long long)n, status);
    } else if (!guarded_guards_intact(&g) || guarded_unwritten(&g) != 0) {
        problem("%s n=%lld: the buffer was overrun or not filled", name, (long long)n);
    } else {
        const float *y = g.data;
        int ok = 1;
        if (outlet == 5) {                                               /* bit for bit what the quiet engine answered */
            ok = memcmp(y, S.filter_reference[shape], (size_t)n * sizeof(float)) == 0;
        } else {
            /* A span made by a node with a span handler reads its one source once (one file, one boundary value, one knob) and must be constant: never a mixture.
               o1 is made by a node with a point handler only (test.sum): the engine asks it for each sample in turn and it reads its source each time, so a writer
               running meanwhile may legitimately change the value between two samples (then each sample must still be a value some write in the window made). */
            for (i = 1; i < n && outlet != 6 && outlet != 1; i++)
                if (float_bits(y[i]) != float_bits(y[0])) {
                    ok = 0;
                    break;
                }
            if (ok && outlet <= 3) {
                int possible = 0;
                if (outlet == 3) {
                    int k2;
                    for (k2 = 0; k2 < 5 && !possible; k2++) {
                        Affine a;
                        a.writer = 3; a.scale = KNOBS[k2]; a.offset = 0.0;
                        possible = affine_possible((double)y[0], &a, lo[3], hi[3]);
                    }
                } else if (vhi - vlo + 1 > MAX_VERSIONS) {
                    atomic_fetch_add(&S.unchecked, 1);
                    possible = 1;
                } else if (outlet == 0) {                                /* the wiring of one version of the window, the knob of one version of the window */
                    int writer_ok[3] = {0, 0, 0}, scale_ok[5] = {0, 0, 0, 0, 0}, wr, k2;
                    long long v;
                    for (v = vlo; v <= vhi; v++) {
                        Spec s = spec_for(v);
                        writer_ok[s.p0] = 1;
                        scale_ok[s.g0_k] = 1;
                    }
                    for (wr = 0; wr < 3 && !possible; wr++)
                        for (k2 = 0; k2 < 5 && !possible; k2++) {
                            Affine a;
                            a.writer = wr; a.scale = KNOBS[k2]; a.offset = 0.0;
                            possible = writer_ok[wr] && scale_ok[k2] && affine_possible((double)y[0], &a, lo[wr], hi[wr]);
                        }
                } else {
                    long long v;
                    for (v = vlo; v <= vhi && !possible; v++) {
                        Spec s = spec_for(v);
                        Affine a = affine_for(outlet, &s);
                        int all = 1;
                        int64_t count = outlet == 1 ? n : 1;                 /* (the other outlets are constant: one sample says it all) */
                        for (i = 0; i < count && all; i++) all = affine_possible((double)y[i], &a, lo[a.writer], hi[a.writer]);
                        possible = all;                                      /* every sample from the one version the instance ran during the query */
                    }
                }
                ok = possible;
            } else if (ok && outlet == 4) {
                if (y[0] == 0.25f) atomic_fetch_add(&S.file_a_seen, 1);
                else if (y[0] == 0.75f) atomic_fetch_add(&S.file_b_seen, 1);
                else ok = 0;
            } else if (ok && outlet == 6) {
                if (vhi - vlo + 1 > MAX_VERSIONS) {
                    atomic_fetch_add(&S.unchecked, 1);
                } else {
                    long long v;
                    int matched = 0;
                    for (v = vlo; v <= vhi && !matched; v++) {
                        Spec s = spec_for(v);
                        int all = 1;
                        for (i = 0; i < n && all; i++) {
                            int64_t t = 0;
                            (void)canopy_sample_time(t0, t1, n, i, &t);
                            all = float_bits(y[i]) == float_bits(support_saw(t) + (float)s.c6);
                        }
                        matched = all;
                    }
                    ok = matched;
                }
            }
        }
        if (!ok) problem("%s %s [%lld, %lld) n=%lld: the answer (first sample %.9g, last %.9g) is not what any graph version from %lld to %lld can give with the writes in range (or a span that should be constant is not)",
                         point ? "point query of" : "span query of", name, (long long)t0, (long long)t1, (long long)n, (double)y[0], (double)y[n - 1], vlo, vhi);
    }
    guarded_free(&g);
    beat();
}

/* ---- the threads ---- */

static unsigned __stdcall reader_main(void *argument)
{
    Worker w;
    int slow;
    w.index = (int)(intptr_t)argument;
    w.rng.state = S.options.seed * 1000003u + (uint64_t)w.index * 7777u + 1u;
    slow = w.index == S.options.readers - 1 && S.options.readers > 1;           /* the last reader sleeps: it adopts many graphs at once */
    w.instance = canopy_engine_new_instance(S.engine);
    if (!w.instance) {
        problem("a reader could not make its instance");
        return 0;
    }
    while (!atomic_load(&S.stop)) {
        do_query(&w);
        if (slow) Sleep(60 + draw_below(&w.rng, 120));
    }
    canopy_instance_free(w.instance);
    return 0;
}

static unsigned __stdcall lifecycle_main(void *argument)
{
    Worker w;
    (void)argument;
    w.index = 99;
    w.rng.state = S.options.seed * 1000003u + 99u;
    while (!atomic_load(&S.stop)) {
        int k, queries = 1 + (int)draw_below(&w.rng, 4);
        w.instance = canopy_engine_new_instance(S.engine);
        if (!w.instance) {
            problem("the lifecycle thread could not make an instance");
            break;
        }
        for (k = 0; k < queries; k++) do_query(&w);
        canopy_instance_free(w.instance);
        atomic_fetch_add(&S.instance_cycles, 1);
        Sleep(draw_below(&w.rng, 3));
    }
    return 0;
}

static unsigned __stdcall writer_main(void *argument)
{
    int index = (int)(intptr_t)argument, spin;
    char name[4] = {'b', (char)('0' + index), 0, 0};
    long long sequence = 0;
    while (!atomic_load(&S.stop)) {
        int32_t status;
        sequence++;
        atomic_store(&S.intent_seq[index], sequence);
        status = canopy_engine_set_boundary(S.engine, name, (float)value_of(sequence));
        if (status != CANOPY_OK) problem("writing %s gave status %d", name, status);
        atomic_store(&S.done_seq[index], sequence);
        atomic_fetch_add(&S.boundary_writes, 1);
        for (spin = 0; spin < 300; spin++) YieldProcessor();
        if ((sequence & 63) == 0) {
            beat();
            Sleep(0);
        }
    }
    return 0;
}

static unsigned __stdcall knob_main(void *argument)
{
    Random rng;
    (void)argument;
    rng.state = S.options.seed * 1000003u + 55u;
    while (!atomic_load(&S.stop)) {
        int32_t status = canopy_engine_set_knob(S.engine, 70, 1, KNOBS[draw_below(&rng, 5)]);         /* the live knob of o3's gain: always there */
        if (status != CANOPY_OK) problem("the live knob gave status %d", status);
        status = canopy_engine_set_knob(S.engine, 120, 2, (float)draw_below(&rng, 3) * 0.5f - 0.5f);   /* the preview's center knob: there in most versions */
        if (status != CANOPY_OK && status != CANOPY_ERR_NODE && status != CANOPY_ERR_ARGUMENT) problem("the preview's knob gave status %d", status);
        atomic_fetch_add(&S.knob_writes, 2);
        beat();
        Sleep(draw_below(&rng, 2));
    }
    return 0;
}

static unsigned __stdcall info_main(void *argument)
{
    static const char *NAMES[11] = {"b0", "b1", "b2", "b3", "o0", "o1", "o2", "o3", "o4", "o5", "o6"};
    long long last_serial = 0;
    (void)argument;
    while (!atomic_load(&S.stop)) {
        int32_t i, count = canopy_engine_boundary_count(S.engine), playing = 0, length = 0;
        int64_t time_ns = 0;
        char text[300];
        long long serial;
        float value = 9.0f;
        uint64_t generation = 0;
        if (count != 11) problem("the listing of the boundary nodes has %d entries, not 11", count);
        for (i = 0; i < 11 && i < count; i++) {
            char name[16] = "";
            int32_t kind = -1, status;
            int64_t id = -1;
            length = 0;
            status = canopy_engine_boundary_at(S.engine, i, name, sizeof name, &length, &kind, &id);
            if (status != CANOPY_OK || strcmp(name, NAMES[i]) != 0 || length != 2 || kind != (i < 4 ? CANOPY_BOUNDARY_INLET : CANOPY_BOUNDARY_OUTLET) ||
                id != (i < 4 ? 10 + i : 20 + (i - 4)))
                problem("boundary entry %d is \"%s\" (kind %d, node %lld, status %d), expected \"%s\"", i, name, kind, (long long)id, status, NAMES[i]);
        }
        serial = canopy_engine_graph_serial(S.engine);
        if (serial < last_serial) problem("the serial of the installed graph went back from %lld to %lld", last_serial, serial);
        last_serial = serial;
        i = canopy_engine_node_count(S.engine);
        if (i < 22 || i > 26) problem("the installed graph has %d nodes (a version has 22 to 26)", i);        /* 21 + the chain (1 to 4) + the preview (0 or 1) */
        if (canopy_engine_node_message(S.engine, 80, text, sizeof text, &length) != CANOPY_OK || length != 0) problem("the file node says something: \"%s\"", text);
        if (canopy_engine_get_knob(S.engine, 70, 1, &value, &generation) != CANOPY_OK) problem("the live knob could not be read");
        else if (value != 1.0f && value != 0.5f && value != 0.25f && value != -0.5f && value != -1.0f) problem("the live knob holds %g", (double)value);
        i = canopy_preview_state(S.engine, 120, &playing, &time_ns);
        if (i != CANOPY_OK && i != CANOPY_ERR_NODE) problem("the preview's state gave status %d", i);
        if (i == CANOPY_OK && playing) atomic_fetch_add(&S.playing_seen, 1);
        i = canopy_preview_warning(S.engine, 120, text, sizeof text, &length);
        if (i != CANOPY_OK && i != CANOPY_ERR_NODE) problem("the preview's warning gave status %d", i);
        atomic_fetch_add(&S.info_calls, 1);
        beat();
        Sleep(1);
    }
    return 0;
}

static unsigned __stdcall ui_main(void *argument)
{
    Random rng;
    (void)argument;
    rng.state = S.options.seed * 1000003u + 77u;
    while (!atomic_load(&S.stop)) {
        uint32_t what = draw_below(&rng, 20);
        int32_t status;
        if (what < 8) status = canopy_engine_action(S.engine, 120, "play");
        else if (what < 13) status = canopy_engine_action(S.engine, 120, "pause");
        else if (what < 17) status = canopy_preview_set_time(S.engine, 120, (int64_t)draw_below(&rng, 20000) * 1000000LL - 2000000000LL);
        else status = canopy_engine_action(S.engine, 120, "device");
        if (status != CANOPY_OK && status != CANOPY_ERR_NODE) problem("a button of the preview gave status %d", status);
        atomic_fetch_add(&S.preview_actions, 1);
        beat();
        Sleep(2 + draw_below(&rng, 30));
    }
    return 0;
}

static unsigned __stdcall installer_main(void *argument)
{
    Random rng;
    long long serial = 1, installed;
    int swap = 0;
    (void)argument;
    rng.state = S.options.seed * 1000003u + 11u;
    while (!atomic_load(&S.stop)) {
        CanopyGraph *g;
        int32_t status;
        serial++;
        if (serial % 13 == 7) {                                          /* a graph that cannot be compiled: nothing may change */
            g = build_graph(serial, 1);
            status = g ? canopy_engine_set_graph(S.engine, g) : CANOPY_ERR_MEMORY;
            if (status != CANOPY_ERR_GRAPH) problem("a graph with an unknown node type gave status %d, not %d", status, CANOPY_ERR_GRAPH);
            if (canopy_engine_graph_serial(S.engine) != atomic_load(&S.installed_serial)) problem("a graph that could not be compiled changed the serial");
            canopy_graph_free(g);
            atomic_fetch_add(&S.bad_installs, 1);
        }
        g = build_graph(serial, 0);
        atomic_store(&S.installing_serial, serial);
        status = canopy_engine_set_graph(S.engine, g);
        if (status != CANOPY_OK) {
            problem("installing graph %lld gave status %d: %s", serial, status, canopy_engine_last_error(S.engine));
            canopy_graph_free(g);
            break;
        }
        installed = canopy_engine_graph_serial(S.engine);
        if (installed != serial) problem("the serial of graph %lld is %lld", serial, installed);
        atomic_store(&S.installed_serial, serial);
        canopy_graph_free(g);
        atomic_fetch_add(&S.installs, 1);
        if (serial % 5 == 0) {                                           /* the file is replaced, and read again when "open" is pressed */
            swap++;
            write_constant_file(S.file_path, swap % 2 ? 0.75f : 0.25f);
            status = canopy_engine_action(S.engine, 80, "open");
            if (status != CANOPY_OK) problem("opening the file gave status %d", status);
            atomic_fetch_add(&S.opens, 1);
        }
        if (draw_below(&rng, 2) == 0) {
            canopy_engine_collect(S.engine);
            atomic_fetch_add(&S.collects, 1);
        }
        beat();
        Sleep(draw_below(&rng, 4));
    }
    return 0;
}

/* ---- the references of the filter, worked out by a quiet engine before anything starts ---- */

static int make_filter_references(void)
{
    static const int64_t SHAPES_T[FILTER_SHAPES][3] = {{0, 1000000000LL, 64}, {0, 3000000000LL, 1000}, {500000000LL, 2000000000LL, 33},
                                                       {2500000000LL, 0, 200}, {-1000000000LL, 1000000000LL, 100}, {1000000000LL, 1000000000LL, 10}};
    CanopyEngine *engine = canopy_engine_new(S.registry);
    CanopyGraph *g = canopy_graph_new();
    CanopyInstance *instance;
    int i, ok = 1;
    if (!engine || !g) return 0;
    canopy_graph_add_node(g, 3, "boundary_outlet");
    canopy_graph_set_string(g, 3, "name", "o5");
    canopy_graph_add_node(g, 90, "test.saw");
    canopy_graph_add_node(g, 91, "test_filter");
    canopy_graph_set_int(g, 91, "internal_sampling_rate", 8000);
    canopy_graph_set_int(g, 91, "checkpoint_seconds", 1);
    canopy_graph_set_float(g, 91, "initial", 0.0);
    canopy_graph_set_knob(g, 91, "coef", 0.0f);
    canopy_graph_connect(g, 90, "out", 91, "in");
    canopy_graph_connect(g, 91, "out", 3, "in");
    ok = canopy_engine_set_graph(engine, g) == CANOPY_OK;
    instance = ok ? canopy_engine_new_instance(engine) : NULL;
    for (i = 0; i < FILTER_SHAPES && instance; i++) {
        S.filter_t0[i] = SHAPES_T[i][0]; S.filter_t1[i] = SHAPES_T[i][1]; S.filter_n[i] = SHAPES_T[i][2];
        S.filter_reference[i] = (float *)calloc((size_t)S.filter_n[i], sizeof(float));
        if (!S.filter_reference[i] || canopy_instance_read_span(instance, "o5", S.filter_t0[i], S.filter_t1[i], S.filter_n[i], S.filter_reference[i]) != CANOPY_OK) ok = 0;
    }
    if (instance) canopy_instance_free(instance);
    canopy_graph_free(g);
    canopy_engine_free(engine);
    return ok && instance != NULL;
}

/* ---- the run ---- */

static long long percentile_ns(double fraction)
{
    long long total = 0, running = 0;
    int b;
    for (b = 0; b < 64; b++) total += atomic_load(&S.histogram[b]);
    if (total == 0) return 0;
    for (b = 0; b < 64; b++) {
        running += atomic_load(&S.histogram[b]);
        if ((double)running >= fraction * (double)total) return b >= 62 ? INT64_MAX : (1LL << (b + 1));
    }
    return 0;
}

int stress_run(const StressOptions *options, StressResult *result)
{
    HANDLE threads[64];
    int count = 0, i, readers = options->readers < 1 ? 1 : (options->readers > 24 ? 24 : options->readers);
    long long live_before = canopy_alloc_live(), progress_seen = -1, stalled_ms = 0;
    DWORD started, now;
    int32_t status;
    CanopyGraph *first;
    StressResult none;
    if (!result) result = &none;
    memset(&S, 0, sizeof S);
    memset(result, 0, sizeof *result);
    S.options = *options;
    S.options.readers = readers;
    InitializeCriticalSection(&S.report_lock);
    QueryPerformanceFrequency(&S.frequency);
    {
        DWORD n = GetTempPathA(MAX_PATH, S.file_path);
        snprintf(S.file_path + n, 64, "canopy_stress_%lu.wav", (unsigned long)GetCurrentProcessId());
    }
    write_constant_file(S.file_path, 0.25f);
    S.registry = support_registry();
    S.engine = S.registry ? canopy_engine_new(S.registry) : NULL;
    if (!S.engine || !make_filter_references()) {
        printf("    stress: the engine or the filter's references could not be made\n");
        return 0;
    }
    canopy_engine_set_audio_backend(S.engine, CANOPY_AUDIO_NULL);
    first = build_graph(1, 0);
    status = first ? canopy_engine_set_graph(S.engine, first) : CANOPY_ERR_MEMORY;
    canopy_graph_free(first);
    if (status != CANOPY_OK) {
        printf("    stress: the first graph gave status %d: %s\n", status, canopy_engine_last_error(S.engine));
        return 0;
    }
    atomic_store(&S.installing_serial, 1);
    atomic_store(&S.installed_serial, 1);
    started = GetTickCount();
    for (i = 0; i < WRITERS; i++) threads[count++] = (HANDLE)_beginthreadex(NULL, 0, writer_main, (void *)(intptr_t)i, 0, NULL);
    for (i = 0; i < readers; i++) threads[count++] = (HANDLE)_beginthreadex(NULL, 0, reader_main, (void *)(intptr_t)i, 0, NULL);
    threads[count++] = (HANDLE)_beginthreadex(NULL, 0, lifecycle_main, NULL, 0, NULL);
    threads[count++] = (HANDLE)_beginthreadex(NULL, 0, info_main, NULL, 0, NULL);
    threads[count++] = (HANDLE)_beginthreadex(NULL, 0, knob_main, NULL, 0, NULL);
    if (options->preview) threads[count++] = (HANDLE)_beginthreadex(NULL, 0, ui_main, NULL, 0, NULL);
    threads[count++] = (HANDLE)_beginthreadex(NULL, 0, installer_main, NULL, 0, NULL);
    for (;;) {                                                           /* the watchdog, and the clock */
        long long seen;
        Sleep(100);
        now = GetTickCount();
        seen = atomic_load(&S.progress);
        if (seen != progress_seen) {
            progress_seen = seen;
            stalled_ms = 0;
        } else {
            stalled_ms += 100;
            if (stalled_ms >= 20000) {
                printf("    stress: NOTHING MOVED FOR 20 SECONDS: a deadlock or a stall (installed graph %lld, installing %lld); the program is stopped\n",
                       (long long)atomic_load(&S.installed_serial), (long long)atomic_load(&S.installing_serial));
                fflush(stdout);
                ExitProcess(3);
            }
        }
        if (atomic_load(&S.stop) || (double)(now - started) / 1000.0 >= options->seconds) break;
    }
    atomic_store(&S.stop, 1);
    for (i = 0; i < count; i++) {
        WaitForSingleObject(threads[i], INFINITE);
        CloseHandle(threads[i]);
    }
    canopy_engine_collect(S.engine);
    if (canopy_engine_free(S.engine) != CANOPY_OK) problem("the engine could not be freed: an instance is still alive");
    canopy_registry_free(S.registry);
    for (i = 0; i < FILTER_SHAPES; i++) free(S.filter_reference[i]);
    remove(S.file_path);
    if (canopy_alloc_live() != live_before) problem("%lld blocks were allocated and not freed", (long long)(canopy_alloc_live() - live_before));
    result->queries = atomic_load(&S.queries); result->span_queries = atomic_load(&S.span_queries); result->point_queries = atomic_load(&S.point_queries);
    result->unchecked = atomic_load(&S.unchecked); result->installs = atomic_load(&S.installs); result->bad_installs = atomic_load(&S.bad_installs);
    result->opens = atomic_load(&S.opens); result->collects = atomic_load(&S.collects); result->boundary_writes = atomic_load(&S.boundary_writes);
    result->knob_writes = atomic_load(&S.knob_writes); result->instance_cycles = atomic_load(&S.instance_cycles); result->info_calls = atomic_load(&S.info_calls);
    result->preview_actions = atomic_load(&S.preview_actions); result->playing_seen = atomic_load(&S.playing_seen);
    result->file_a_seen = atomic_load(&S.file_a_seen); result->file_b_seen = atomic_load(&S.file_b_seen);
    result->max_spread_versions = atomic_load(&S.max_spread); result->small_query_ns_max = atomic_load(&S.small_max_ns);
    result->small_query_ns_p999 = percentile_ns(0.999); result->small_query_ns_p9999 = percentile_ns(0.9999);
    result->problems = atomic_load(&S.problems);
    DeleteCriticalSection(&S.report_lock);
    if (options->verbose || result->problems) {
        printf("stress: %.1f s, %d readers: %lld queries (%lld spans, %lld points; %lld too uncertain to check), %lld installs (+%lld refused), %lld opens, "
               "%lld collects, %lld boundary writes, %lld knob writes, %lld instances made and freed, %lld info calls, %lld preview actions "
               "(the preview was found playing %lld times)\n",
               (double)(GetTickCount() - started) / 1000.0, readers, result->queries, result->span_queries, result->point_queries, result->unchecked,
               result->installs, result->bad_installs, result->opens, result->collects, result->boundary_writes, result->knob_writes, result->instance_cycles,
               result->info_calls, result->preview_actions, result->playing_seen);
        printf("stress: the widest range of graph versions one answer could come from: %lld; file spans: %lld of the first file, %lld of the second; "
               "queries of 64 samples or fewer: slowest %.3f ms, 99.9%% within %.3f ms, 99.99%% within %.3f ms; problems: %lld\n",
               result->max_spread_versions, result->file_a_seen, result->file_b_seen, (double)result->small_query_ns_max / 1e6,
               (double)result->small_query_ns_p999 / 1e6, (double)result->small_query_ns_p9999 / 1e6, result->problems);
        fflush(stdout);
    }
    return result->problems == 0;
}

/* ---- as a test ---- */

static void test_c_a_short_stress_of_every_kind_of_call_at_once_finds_no_wrong_answer_stall_or_leak(void)
{
    StressOptions options;
    StressResult result;
    options.seconds = 2.5;
    options.seed = 20261006;
    options.readers = 4;
    options.preview = 1;
    options.verbose = 0;
    CHECK(stress_run(&options, &result));
    CHECK_INT(result.problems, 0);
    CHECK(result.queries > 100 && result.installs > 5 && result.boundary_writes > 100 && result.instance_cycles > 0);      /* (it ran; a slow build does less) */
    CHECK(result.file_a_seen + result.file_b_seen > 0);
    CHECK(result.playing_seen > 0);                        /* the audio thread of the preview really ran during it */
    CHECK_HEAP();
}

void register_test_stress(void)
{
    RUN(test_c_a_short_stress_of_every_kind_of_call_at_once_finds_no_wrong_answer_stall_or_leak);
}
