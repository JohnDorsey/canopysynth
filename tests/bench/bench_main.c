/* The timing measurements of plan step 13 (what the engine costs: queries, threads, installs, writes during installs, the preview's callbacks, files, deep chains,
   the real audio device). Built by `build.ps1 -Bench` as build\bench.exe, with the optimiser (/O2), from the library sources, tests\c\support.c (the test node
   types: gain, sum, const, saw, and the hidden filter) and this file; `dev/measure.py` runs it and the Python-level measurements and prints the report.
     bench.exe queries              what one query costs: point and span, boundary values, chains of gains, pointwise nodes, a file, the filter
     bench.exe scaling              queries per second for 1 to 12 threads, each with an instance of its own
     bench.exe installs             what installing a graph costs (1 to 10000 trios of nodes), what an instance pays to adopt it, memory per node and per instance
     bench.exe stalls               how long a boundary write, a knob write and a query take while another thread installs a 3000-node graph over and over
     bench.exe preview              how regularly the preview's audio callbacks come (null backend), alone and while graphs are installed
     bench.exe file MEGABYTES       what loading a WAV file of that size costs in time and memory, and what a query of it costs afterwards
     bench.exe chain DEPTH main|worker|preview    one chain of DEPTH gains asked from the main thread, a worker thread or the preview's audio thread (run it in a
                                                  process of its own: a stack overflow ends the process)
     bench.exe device --real-device the preview on the machine's real audio device, playing silence: how long the buttons take and what the writes of a
                                    host see meanwhile (the D1 question of the plan)
   The numbers are for the machine and the build they were taken on: they say how the cost grows, and what a host can expect. */
#define PSAPI_VERSION 2
#include <math.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <psapi.h>
#include "../c/support.h"

/* what the C tests' harness defines and support.c uses */
int ctest_passed = 0, ctest_failed = 0, ctest_current_failed = 0;
const char *ctest_current_name = "(bench)";
int ctest_selected(const char *name) { (void)name; return 1; }
int ctest_heap_ok(void) { return 1; }

#define WRITE_US(x) ((x) / 1000.0)

static LARGE_INTEGER frequency;

static double now_ns(void)
{
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart * 1e9 / (double)frequency.QuadPart;
}

static void die(const char *what, int64_t status)
{
    printf("FAILED: %s (status %lld)\n", what, (long long)status);
    fflush(stdout);
    exit(2);
}

static double private_megabytes(void)
{
    PROCESS_MEMORY_COUNTERS_EX counters;
    counters.cb = sizeof counters;
    GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS *)&counters, sizeof counters);
    return (double)counters.PrivateUsage / (1024.0 * 1024.0);
}

/* ---- a histogram of durations in nanoseconds: 8 buckets to the octave ---- */

typedef struct { long long bucket[64 * 8]; long long count; double max, sum; } Hist;

static void hist_add(Hist *h, double ns)
{
    unsigned long long v = ns < 1.0 ? 1ULL : (unsigned long long)ns;
    int octave = 0, fraction;
    while ((v >> octave) > 1) octave++;
    fraction = octave >= 3 ? (int)((v >> (octave - 3)) & 7u) : (int)((v << (3 - octave)) & 7u);
    h->bucket[octave * 8 + fraction]++;
    h->count++;
    h->sum += ns;
    if (ns > h->max) h->max = ns;
}

static double hist_percentile(const Hist *h, double fraction)       /* the upper edge of the bucket the percentile falls in */
{
    long long running = 0;
    int i;
    for (i = 0; i < 64 * 8; i++) {
        running += h->bucket[i];
        if ((double)running >= fraction * (double)h->count) {
            int octave = i / 8, f = i % 8;
            return (double)(1ULL << octave) * (1.0 + (double)(f + 1) / 8.0);
        }
    }
    return h->max;
}

static void hist_print(const char *label, const Hist *h)
{
    printf("  %-34s %9lld calls  mean %8.2f us  p50 %8.2f  p99 %8.2f  p99.9 %8.2f  max %9.2f us\n", label, h->count, WRITE_US(h->sum / (double)(h->count ? h->count : 1)),
           WRITE_US(hist_percentile(h, 0.5)), WRITE_US(hist_percentile(h, 0.99)), WRITE_US(hist_percentile(h, 0.999)), WRITE_US(h->max));
}

/* ---- an engine to measure ---- */

typedef struct {
    CanopyRegistry *registry;
    CanopyEngine *engine;
    CanopyInstance *instance;
} Env;

static void env_open(Env *env, int backend)
{
    env->registry = support_registry();
    env->engine = env->registry ? canopy_engine_new(env->registry) : NULL;
    env->instance = NULL;
    if (!env->engine) die("the engine could not be made", 0);
    canopy_engine_set_audio_backend(env->engine, backend);
}

static void env_install(Env *env, CanopyGraph *graph)
{
    int32_t status = canopy_engine_set_graph(env->engine, graph);
    if (status != CANOPY_OK) die(canopy_engine_last_error(env->engine), status);
    canopy_graph_free(graph);
}

static void env_instance(Env *env)
{
    env->instance = canopy_engine_new_instance(env->engine);
    if (!env->instance) die("no instance", 0);
}

static void env_close(Env *env)
{
    if (env->instance) canopy_instance_free(env->instance);
    canopy_engine_free(env->engine);
    canopy_registry_free(env->registry);
}

static void node(CanopyGraph *g, int64_t id, const char *type)
{
    int32_t status = canopy_graph_add_node(g, id, type);
    if (status != CANOPY_OK) die(type, status);
}

static void wire(CanopyGraph *g, int64_t from, const char *outlet, int64_t to, const char *inlet)
{
    int32_t status = canopy_graph_connect(g, from, outlet, to, inlet);
    if (status != CANOPY_OK) die("connect", status);
}

static void name(CanopyGraph *g, int64_t id, const char *text)
{
    canopy_graph_set_string(g, id, "name", text);
}

static CanopyGraph *boundary_graph(void)                  /* inlet "x" -> outlet "y" */
{
    CanopyGraph *g = canopy_graph_new();
    node(g, 1, "boundary_inlet"); node(g, 2, "boundary_outlet");
    name(g, 1, "x"); name(g, 2, "y");
    wire(g, 1, "out", 2, "in");
    return g;
}

static CanopyGraph *chain_graph(int depth)                /* inlet "x" -> `depth` gains -> outlet "y" */
{
    CanopyGraph *g = canopy_graph_new();
    int i;
    node(g, 1, "boundary_inlet"); name(g, 1, "x");
    for (i = 0; i < depth; i++) {
        node(g, 2 + i, "test.gain");
        canopy_graph_set_knob(g, 2 + i, "gain", 0.5f);
        wire(g, i == 0 ? 1 : 1 + i, "out", 2 + i, "in");
    }
    node(g, 2 + depth, "boundary_outlet"); name(g, 2 + depth, "y");
    wire(g, 1 + depth, "out", 2 + depth, "in");
    return g;
}

static CanopyGraph *pointwise_graph(void)                 /* saw + const -> sum -> "y" (nodes with a point handler only) */
{
    CanopyGraph *g = canopy_graph_new();
    node(g, 1, "test.saw"); node(g, 2, "test.const"); node(g, 3, "test.sum"); node(g, 4, "boundary_outlet");
    canopy_graph_set_float(g, 2, "value", 0.25);
    name(g, 4, "y");
    wire(g, 1, "out", 3, "a"); wire(g, 2, "out", 3, "b"); wire(g, 3, "out", 4, "in");
    return g;
}

static CanopyGraph *file_graph(const char *path)          /* file -> "y" (left) */
{
    CanopyGraph *g = canopy_graph_new();
    node(g, 1, "file_read"); node(g, 2, "boundary_outlet");
    canopy_graph_set_string(g, 1, "path", path);
    name(g, 2, "y");
    wire(g, 1, "left", 2, "in");
    return g;
}

static CanopyGraph *filter_graph(void)                    /* saw -> test_filter (48 kHz, a checkpoint every 10 s) -> "y" */
{
    CanopyGraph *g = canopy_graph_new();
    node(g, 1, "test.saw"); node(g, 2, "test_filter"); node(g, 3, "boundary_outlet");
    canopy_graph_set_knob(g, 2, "coef", -0.9f);
    name(g, 3, "y");
    wire(g, 1, "out", 2, "in"); wire(g, 2, "out", 3, "in");
    return g;
}

static CanopyGraph *wide_graph_from(CanopyGraph *g, int64_t first_id, int trios, int variant)    /* `trios` times: inlet -> gain -> outlet (3 nodes each); the variant changes the gains */
{
    char text[32];
    int i;
    if (!g) g = canopy_graph_new();
    for (i = 0; i < trios; i++) {
        int64_t base = first_id + 3 * (int64_t)i;
        node(g, base, "boundary_inlet"); node(g, base + 1, "test.gain"); node(g, base + 2, "boundary_outlet");
        snprintf(text, sizeof text, "i%d", i); name(g, base, text);
        snprintf(text, sizeof text, "o%d", i); name(g, base + 2, text);
        canopy_graph_set_knob(g, base + 1, "gain", variant ? 0.25f : 0.5f);
        wire(g, base, "out", base + 1, "in"); wire(g, base + 1, "out", base + 2, "in");
    }
    return g;
}

static CanopyGraph *wide_graph(int trios, int variant)
{
    return wide_graph_from(NULL, 1, trios, variant);
}

/* a chain of 8 gains feeding a preview node (900), and `trios` trios beside them (their IDs start at 100000, so the nodes of the chain and the preview keep theirs) */
static CanopyGraph *preview_graph(int trios, int variant)
{
    CanopyGraph *g = chain_graph(8);
    node(g, 900, "realtime_preview");
    wire(g, 9, "out", 900, "left"); wire(g, 6, "out", 900, "right");
    canopy_graph_set_knob(g, 5, "gain", variant ? 0.75f : 0.5f);            /* (one knob of the chain changes too) */
    return wide_graph_from(g, 100000, trios, variant);
}

/* a 16-bit stereo 44.1 kHz file of about `megabytes` MB of a deterministic pattern */
static void write_big_wav(const char *path, double megabytes)
{
    FILE *file = fopen(path, "wb");
    uint32_t frames = (uint32_t)(megabytes * 1024.0 * 1024.0 / 4.0), data_bytes = frames * 4u, rate = 44100, riff = 36u + data_bytes, fmt = 16, byte_rate = rate * 4u;
    uint16_t tag = 1, channels = 2, block = 4, bits = 16;
    int16_t chunk[2 * 4096];
    uint32_t done = 0;
    if (!file) die("the file could not be written", 0);
    fwrite("RIFF", 1, 4, file); fwrite(&riff, 4, 1, file); fwrite("WAVEfmt ", 1, 8, file); fwrite(&fmt, 4, 1, file);
    fwrite(&tag, 2, 1, file); fwrite(&channels, 2, 1, file); fwrite(&rate, 4, 1, file); fwrite(&byte_rate, 4, 1, file);
    fwrite(&block, 2, 1, file); fwrite(&bits, 2, 1, file); fwrite("data", 1, 4, file); fwrite(&data_bytes, 4, 1, file);
    while (done < frames) {
        uint32_t n = frames - done < 4096 ? frames - done : 4096, k;
        for (k = 0; k < n; k++) {
            chunk[2 * k] = (int16_t)((int32_t)(((done + k) * 37u) % 65536u) - 32768);
            chunk[2 * k + 1] = (int16_t)(((done + k) * 91u) % 65536u);
        }
        fwrite(chunk, 4, n, file);
        done += n;
    }
    fclose(file);
}

static const char *temp_path(const char *stem)
{
    static char path[MAX_PATH + 64];
    DWORD n = GetTempPathA(MAX_PATH, path);
    snprintf(path + n, 64, "%s_%lu.wav", stem, (unsigned long)GetCurrentProcessId());
    return path;
}

/* ---- the cost of one query ---- */

typedef struct {
    CanopyInstance *instance;
    const char *outlet;
    int point;
    int64_t t0, t1, n, advance;        /* a span [t0, t1) of n samples; after each call it moves on by `advance` ns (playback: the next block) */
    float *out;
} QueryJob;

static void run_query(QueryJob *job)
{
    int32_t status = job->point ? canopy_instance_read_at(job->instance, job->outlet, job->t0, job->out)
                                : canopy_instance_read_span(job->instance, job->outlet, job->t0, job->t1, job->n, job->out);
    if (status != CANOPY_OK) die("a query failed", status);
    job->t0 += job->advance;
    job->t1 += job->advance;
}

/* ns per call of `job`, over at least `seconds` of running after a short warm-up */
static double time_job(QueryJob *job, double seconds)
{
    double start, end, deadline;
    long long calls = 0;
    int i;
    for (i = 0; i < 20; i++) run_query(job);
    start = now_ns();
    deadline = start + seconds * 1e9;
    do {
        for (i = 0; i < 50; i++) run_query(job);
        calls += 50;
        end = now_ns();
    } while (end < deadline);
    return (end - start) / (double)calls;
}

static void report_query(const char *label, QueryJob *job, double seconds)
{
    double ns = time_job(job, seconds);
    if (job->point) printf("  %-44s point          %10.1f ns/call\n", label, ns);
    else printf("  %-44s n=%-6lld %10.1f ns/call %8.2f ns/sample   %7.3f%% of the time n samples last at 48 kHz\n", label, (long long)job->n, ns, ns / (double)job->n,
                100.0 * ns / ((double)job->n * 1e9 / 48000.0));
}

static void measure_queries(void)
{
    static float out[65536];
    static const int64_t NS[] = {1, 64, 480, 4800, 65536};
    Env env;
    QueryJob job;
    int i, d;
    printf("QUERIES (one thread, one instance, the optimised build)\n");
    memset(&job, 0, sizeof job);
    job.out = out;
    env_open(&env, CANOPY_AUDIO_NULL);
    env_install(&env, boundary_graph());
    env_instance(&env);
    job.instance = env.instance;
    job.outlet = "y";
    job.point = 1;
    report_query("a boundary value read through an outlet", &job, 0.4);
    job.point = 0;
    for (i = 0; i < 5; i++) {
        job.n = NS[i]; job.t0 = 0; job.t1 = NS[i] * 20833LL; job.advance = job.t1 - job.t0;
        report_query("a boundary value, span", &job, 0.3);
    }
    env_close(&env);
    for (d = 0; d < 3; d++) {
        static const int DEPTHS[] = {1, 8, 64};
        char label[80];
        env_open(&env, CANOPY_AUDIO_NULL);
        env_install(&env, chain_graph(DEPTHS[d]));
        env_instance(&env);
        job.instance = env.instance;
        job.point = 1;
        snprintf(label, sizeof label, "a chain of %d gains (point)", DEPTHS[d]);
        report_query(label, &job, 0.3);
        job.point = 0;
        for (i = 1; i < 5; i++) {
            job.n = NS[i]; job.t0 = 0; job.t1 = NS[i] * 20833LL; job.advance = job.t1 - job.t0;
            snprintf(label, sizeof label, "a chain of %d gains (span handlers)", DEPTHS[d]);
            report_query(label, &job, 0.3);
        }
        env_close(&env);
    }
    env_open(&env, CANOPY_AUDIO_NULL);
    env_install(&env, pointwise_graph());
    env_instance(&env);
    job.instance = env.instance;
    for (i = 2; i < 5; i++) {
        job.n = NS[i]; job.t0 = 0; job.t1 = NS[i] * 20833LL; job.advance = job.t1 - job.t0;
        report_query("saw + const -> sum (point handlers only)", &job, 0.3);
    }
    env_close(&env);
    {
        const char *path = temp_path("canopy_bench_query");
        static const struct { int64_t n, t1; const char *what; } SHAPES[] = {
            {480, 10000000LL, "a file, 480 samples over 10 ms (same density)"}, {480, 40000000LL, "a file, 480 samples over 40 ms (4x sparser)"},
            {480, 2500000LL, "a file, 480 samples over 2.5 ms (4x denser)"}, {65536, 1500000000LL, "a file, the biggest span, 1.5 s"}};
        write_big_wav(path, 4.0);                                                                   /* about 24 seconds at 44.1 kHz */
        env_open(&env, CANOPY_AUDIO_NULL);
        env_install(&env, file_graph(path));
        env_instance(&env);
        job.instance = env.instance;
        for (i = 0; i < 4; i++) {
            job.n = SHAPES[i].n; job.t0 = 0; job.t1 = SHAPES[i].t1; job.advance = job.t1;
            report_query(SHAPES[i].what, &job, 0.3);
        }
        env_close(&env);
        remove(path);
    }
    env_open(&env, CANOPY_AUDIO_NULL);
    env_install(&env, filter_graph());
    env_instance(&env);
    job.instance = env.instance;
    for (i = 2; i < 4; i++) {                                                                       /* the hidden filter, playing on: each block follows the last */
        job.n = NS[i]; job.t0 = 0; job.t1 = NS[i] * 20833LL; job.advance = job.t1 - job.t0;
        report_query("the test filter, playing on (cursor)", &job, 0.3);
    }
    {
        double started, ns;
        float one;
        started = now_ns();
        if (canopy_instance_read_at(env.instance, "y", 2000000000LL, &one) != CANOPY_OK) die("filter", 0);
        ns = now_ns() - started;
        printf("  %-44s point          %10.1f ms (2 s of 48 kHz samples from the start: the filter keeps no more than its checkpoints)\n", "the test filter, a cold read at t = 2 s", ns / 1e6);
    }
    env_close(&env);
}

/* ---- threads ---- */

typedef struct {
    CanopyEngine *engine;
    const char *outlet;
    int64_t n;
    double seconds;
    volatile LONG *go;
    int pin_to;                       /* the logical processor to run on (-1: wherever Windows puts it) */
    long long calls;
    double elapsed_ns;
} ScalingJob;

/* one job to a cache line pair, so that the counters of two threads never share a line */
typedef struct { ScalingJob job; char pad[128]; } PaddedJob;

static unsigned __stdcall scaling_main(void *argument)
{
    ScalingJob *job = (ScalingJob *)argument;
    CanopyInstance *instance;
    float *out;
    if (job->pin_to >= 0) SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)1 << job->pin_to);
    instance = canopy_engine_new_instance(job->engine);
    out = (float *)_aligned_malloc(((size_t)job->n * sizeof(float) + 127) & ~(size_t)127, 128);
    QueryJob q;
    double start, deadline;
    int i;
    memset(&q, 0, sizeof q);
    q.instance = instance; q.outlet = job->outlet; q.n = job->n; q.t1 = job->n * 20833LL; q.advance = q.t1; q.out = out;
    while (!*job->go) YieldProcessor();
    start = now_ns();
    deadline = start + job->seconds * 1e9;
    do {
        for (i = 0; i < 20; i++) run_query(&q);
        job->calls += 20;
    } while (now_ns() < deadline);
    job->elapsed_ns = now_ns() - start;
    _aligned_free(out);
    canopy_instance_free(instance);
    return 0;
}

static int scaling_pinned_too;                            /* `bench scaling --pinned` also runs each thread on a core of its own */

static void measure_scaling(void)
{
    static const int THREADS[] = {1, 2, 4, 6, 8, 12};
    static const struct { const char *what; int depth; int64_t n; } CASES[] = {{"a chain of 8 gains, 480 samples", 8, 480}, {"a chain of 8 gains, 4800 samples", 8, 4800}};
    int c, t, k, pin;
    printf("SCALING (spans per second in all threads together, each thread with an instance of its own; this machine has %d logical processors; \"pinned\": thread k runs on "
           "logical processor 2k, which on this machine is a core of its own, \"free\": wherever Windows puts it)\n", (int)GetActiveProcessorCount(ALL_PROCESSOR_GROUPS));
    for (pin = 0; pin < (scaling_pinned_too ? 2 : 1); pin++)
    for (c = 0; c < 2; c++) {
        double single = 0.0;
        for (t = 0; t < 6; t++) {
            Env env;
            PaddedJob padded[12];
            ScalingJob *jobs = NULL;
            ScalingJob *list[12];
            HANDLE handles[12];
            volatile LONG go = 0;
            double total = 0.0;
            env_open(&env, CANOPY_AUDIO_NULL);
            env_install(&env, chain_graph(CASES[c].depth));
            (void)jobs;
            for (k = 0; k < THREADS[t]; k++) {
                list[k] = &padded[k].job;
                memset(&padded[k], 0, sizeof padded[k]);
                list[k]->engine = env.engine; list[k]->outlet = "y"; list[k]->n = CASES[c].n; list[k]->seconds = 1.0; list[k]->go = &go;
                list[k]->pin_to = pin ? 2 * k : -1;
                handles[k] = (HANDLE)_beginthreadex(NULL, 0, scaling_main, list[k], 0, NULL);
            }
            Sleep(100);
            go = 1;
            WaitForMultipleObjects((DWORD)THREADS[t], handles, TRUE, INFINITE);
            for (k = 0; k < THREADS[t]; k++) {
                total += (double)list[k]->calls / (list[k]->elapsed_ns / 1e9);
                CloseHandle(handles[k]);
            }
            if (t == 0) single = total;
            printf("  %-34s %-6s %2d threads %12.0f spans/s  = %5.2fx one thread  (%3.0f%% of linear)\n", CASES[c].what, pin ? "pinned" : "free", THREADS[t], total,
                   total / single, 100.0 * total / (single * THREADS[t]));
            env_close(&env);
        }
    }
}

/* ---- installing ---- */

/* what an instance holds: the scratch arena the compile sized for the deepest chain, and the table of node states */
static void measure_instance_memory(void)
{
    static const int DEPTHS[] = {1, 8, 64, 512};
    int d, i;
    printf("INSTANCE MEMORY (a chain of N gains: the floats of the scratch arena the instance gets, canopy_instance_arena_floats, and what 16 instances add to the process)\n");
    for (d = 0; d < 4; d++) {
        Env env;
        CanopyInstance *instances[16];
        double before, after;
        long long blocks;
        env_open(&env, CANOPY_AUDIO_NULL);
        env_install(&env, chain_graph(DEPTHS[d]));
        before = private_megabytes();
        blocks = canopy_alloc_live();
        for (i = 0; i < 16; i++) instances[i] = canopy_engine_new_instance(env.engine);
        after = private_megabytes();
        printf("  chain of %3d gains: arena %10lld floats = %7.2f MB per instance; 16 instances added %7.2f MB to the process (%.2f MB each) and %lld blocks\n", DEPTHS[d],
               (long long)canopy_instance_arena_floats(instances[0]), (double)canopy_instance_arena_floats(instances[0]) * 4.0 / (1024.0 * 1024.0), after - before,
               (after - before) / 16.0, canopy_alloc_live() - blocks);
        for (i = 0; i < 16; i++) canopy_instance_free(instances[i]);
        env_close(&env);
    }
}

static void measure_installs(void)
{
    static const int TRIOS[] = {1, 10, 100, 1000, 10000};
    int s, i;
    printf("INSTALLS (a graph of N trios: boundary inlet -> gain -> boundary outlet = 3N nodes)\n");
    for (s = 0; s < 5; s++) {
        Env env;
        double t, describe_ns, install_ns, again_ns, adopt_ns, memory_before, memory_graph, memory_instances;
        long long blocks_before, blocks_graph, blocks_instance;
        CanopyGraph *g;
        CanopyInstance *instances[8];
        float one;
        double adopt_each[8];
        env_open(&env, CANOPY_AUDIO_NULL);
        memory_before = private_megabytes();
        blocks_before = canopy_alloc_live();
        t = now_ns();
        g = wide_graph(TRIOS[s], 0);
        describe_ns = now_ns() - t;
        t = now_ns();
        if (canopy_engine_set_graph(env.engine, g) != CANOPY_OK) die("install", 0);
        install_ns = now_ns() - t;
        memory_graph = private_megabytes();
        blocks_graph = canopy_alloc_live();
        for (i = 0; i < 8; i++) {
            instances[i] = canopy_engine_new_instance(env.engine);
            if (!instances[i]) die("instance", 0);
            if (i == 0) blocks_instance = canopy_alloc_live() - blocks_graph;
        }
        memory_instances = private_megabytes();
        (void)blocks_instance;
        for (i = 0; i < 8; i++) canopy_instance_read_at(instances[i], "o0", 0, &one);              /* (each has run a query before the swap) */
        canopy_graph_free(g);
        g = wide_graph(TRIOS[s], 1);                                                                 /* new knob positions: an install that changes every knob */
        t = now_ns();
        if (canopy_engine_set_graph(env.engine, g) != CANOPY_OK) die("install again", 0);
        again_ns = now_ns() - t;
        for (i = 0; i < 8; i++) {                                                                    /* what an instance pays to take it up: its next query */
            t = now_ns();
            canopy_instance_read_at(instances[i], "o0", 0, &one);
            adopt_each[i] = now_ns() - t;
        }
        adopt_ns = 0.0;
        for (i = 0; i < 8; i++) adopt_ns += adopt_each[i] / 8.0;
        t = now_ns();
        canopy_engine_collect(env.engine);
        printf("  %6d nodes: describe %9.2f ms, first install %9.2f ms, install again (all knobs moved, 8 instances) %9.2f ms, adoption by an instance %9.3f ms, collect %8.3f ms\n",
               3 * TRIOS[s], describe_ns / 1e6, install_ns / 1e6, again_ns / 1e6, adopt_ns / 1e6, (now_ns() - t) / 1e6);
        printf("               memory: graph %7.2f MB (%lld blocks), 8 instances %7.2f MB (%lld blocks: %.1f MB and %lld blocks each)\n", memory_graph - memory_before,
               blocks_graph - blocks_before, memory_instances - memory_graph, canopy_alloc_live() - blocks_graph, (memory_instances - memory_graph) / 8.0,
               (canopy_alloc_live() - blocks_graph) / 8);
        canopy_graph_free(g);
        for (i = 0; i < 8; i++) canopy_instance_free(instances[i]);
        env_close(&env);
    }
    measure_instance_memory();
}

typedef struct {
    CanopyEngine *engine;
    volatile LONG *stop;
    int trios;
    int with_preview;                 /* 1: install preview_graph (the chain and the preview node stay), 0: wide_graph */
    long long installs;
    Hist install_time;
} InstallerJob;

static unsigned __stdcall installer_main(void *argument)
{
    InstallerJob *job = (InstallerJob *)argument;
    int variant = 0;
    while (!*job->stop) {
        CanopyGraph *g;
        double start;
        variant ^= 1;
        g = job->with_preview ? preview_graph(job->trios, variant) : wide_graph(job->trios, variant);
        start = now_ns();
        if (canopy_engine_set_graph(job->engine, g) != CANOPY_OK) die("installer", 0);
        hist_add(&job->install_time, now_ns() - start);
        canopy_graph_free(g);
        job->installs++;
        canopy_engine_collect(job->engine);
    }
    return 0;
}

typedef struct {
    CanopyEngine *engine;
    volatile LONG *stop;
    int kind;                         /* 0: boundary writes, 1: knob writes, 2: queries of a gain through an outlet */
    Hist hist;
} StallJob;

static unsigned __stdcall stall_main(void *argument)
{
    StallJob *job = (StallJob *)argument;
    CanopyInstance *instance = job->kind == 2 ? canopy_engine_new_instance(job->engine) : NULL;
    float out[480];
    double value = 0.0;
    while (!*job->stop) {
        double start = now_ns();
        int32_t status;
        value += 1.0;
        if (job->kind == 0) status = canopy_engine_set_boundary(job->engine, "i0", (float)value);
        else if (job->kind == 1) status = canopy_engine_set_knob(job->engine, 2, 1, ((int)value & 1) ? 0.5f : 0.25f);
        else status = canopy_instance_read_span(instance, "o1", 0, 10000000LL, 480, out);
        hist_add(&job->hist, now_ns() - start);
        if (status != CANOPY_OK) die("a call during the installs failed", status);
        if (job->kind != 2) Sleep(0);
    }
    if (instance) canopy_instance_free(instance);
    return 0;
}

static void measure_stalls(void)
{
    static const char *WHAT[] = {"boundary write", "knob write", "span query of 480 (through a gain)"};
    int phase, k;
    printf("STALLS (calls made while another thread installs a 3000-node graph (1000 trios) again and again; the first block is the same calls with no installing)\n");
    for (phase = 0; phase < 2; phase++) {
        Env env;
        volatile LONG stop = 0;
        InstallerJob installer;
        StallJob jobs[3];
        HANDLE handles[4];
        env_open(&env, CANOPY_AUDIO_NULL);
        env_install(&env, wide_graph(1000, 0));
        memset(&installer, 0, sizeof installer);
        installer.engine = env.engine; installer.stop = &stop; installer.trios = 1000;
        for (k = 0; k < 3; k++) {
            memset(&jobs[k], 0, sizeof jobs[k]);
            jobs[k].engine = env.engine; jobs[k].stop = &stop; jobs[k].kind = k;
            handles[k] = (HANDLE)_beginthreadex(NULL, 0, stall_main, &jobs[k], 0, NULL);
        }
        handles[3] = phase ? (HANDLE)_beginthreadex(NULL, 0, installer_main, &installer, 0, NULL) : NULL;
        Sleep(3000);
        stop = 1;
        WaitForMultipleObjects(phase ? 4 : 3, handles, TRUE, INFINITE);
        printf(phase ? " while installing (%lld installs, each took mean %.2f ms, p99 %.2f ms, max %.2f ms):\n" : " with no installing:\n", installer.installs,
               installer.install_time.count ? installer.install_time.sum / (double)installer.install_time.count / 1e6 : 0.0, hist_percentile(&installer.install_time, 0.99) / 1e6,
               installer.install_time.max / 1e6);
        for (k = 0; k < 3; k++) hist_print(WHAT[k], &jobs[k].hist);
        for (k = 0; k < (phase ? 4 : 3); k++) CloseHandle(handles[k]);
        env_close(&env);
    }
}

/* ---- the preview ---- */

static void measure_preview(void)
{
    int phase;
    printf("PREVIEW (the null backend's audio thread, polled every 0.2 ms for 6 s: the time between two moves of the playback position is the time between two callbacks;\n"
           "         a callback asks the graph, a chain of 8 gains, for three inlets of one period each)\n");
    for (phase = 0; phase < 3; phase++) {
        Env env;
        InstallerJob installer;
        volatile LONG stop = 0;
        HANDLE handle = NULL;
        Hist gaps;
        int64_t last = -1;
        double last_move = 0.0, start;
        long long moves = 0;
        int32_t playing = 0;
        int64_t time_ns = 0;
        memset(&gaps, 0, sizeof gaps);
        env_open(&env, CANOPY_AUDIO_NULL);
        env_install(&env, preview_graph(phase == 0 ? 0 : (phase == 1 ? 100 : 1000), 0));
        memset(&installer, 0, sizeof installer);
        installer.engine = env.engine; installer.stop = &stop; installer.trios = phase == 1 ? 100 : 1000; installer.with_preview = 1;
        if (canopy_engine_action(env.engine, 900, "play") != CANOPY_OK) die("play", 0);
        Sleep(200);
        if (phase > 0) handle = (HANDLE)_beginthreadex(NULL, 0, installer_main, &installer, 0, NULL);
        start = now_ns();
        while (now_ns() - start < 6e9) {
            double t = now_ns();
            canopy_preview_state(env.engine, 900, &playing, &time_ns);
            if (time_ns != last) {
                if (last >= 0) {
                    hist_add(&gaps, t - last_move);
                    moves++;
                }
                last = time_ns;
                last_move = t;
            }
            Sleep(0);
            { double spin = now_ns(); while (now_ns() - spin < 150000.0) YieldProcessor(); }             /* about 0.2 ms between two polls */
        }
        stop = 1;
        if (handle) {
            WaitForSingleObject(handle, INFINITE);
            CloseHandle(handle);
        }
        printf("  %-52s %5lld position moves; between two: mean %6.2f ms  p50 %6.2f  p99 %6.2f  max %7.2f ms; position advanced %.3f s in the 6 s%s\n",
               phase == 0 ? "playing, nothing else going on:" : (phase == 1 ? "while 100 trios (300 nodes) are installed again and again:" :
                                                                  "while 1000 trios (3000 nodes) are installed again and again:"),
               moves, gaps.sum / (double)(gaps.count ? gaps.count : 1) / 1e6, hist_percentile(&gaps, 0.5) / 1e6, hist_percentile(&gaps, 0.99) / 1e6, gaps.max / 1e6,
               (double)(time_ns) / 1e9, "");
        env_close(&env);
    }
}

/* ---- a file ---- */

static void measure_file(double megabytes)
{
    const char *path = temp_path("canopy_bench_file");
    Env env;
    double t, load_ns, open_ns, before, after_load, after_open;
    float out[480];
    QueryJob job;
    int32_t status;
    printf("FILE (16-bit stereo, 44.1 kHz, %.0f MB: %.0f seconds of audio)\n", megabytes, megabytes * 1024.0 * 1024.0 / 4.0 / 44100.0);
    t = now_ns();
    write_big_wav(path, megabytes);
    printf("  (writing the file took %.2f s)\n", (now_ns() - t) / 1e9);
    env_open(&env, CANOPY_AUDIO_NULL);
    before = private_megabytes();
    t = now_ns();
    env_install(&env, file_graph(path));                                                             /* the file is read when the node first appears in an installed graph */
    load_ns = now_ns() - t;
    after_load = private_megabytes();
    env_instance(&env);
    t = now_ns();
    status = canopy_engine_action(env.engine, 1, "open");                                            /* and again: a second copy exists until the first can be freed */
    open_ns = now_ns() - t;
    after_open = private_megabytes();
    canopy_engine_collect(env.engine);
    memset(&job, 0, sizeof job);
    job.instance = env.instance; job.outlet = "y"; job.n = 480; job.t1 = 10000000LL; job.advance = job.t1; job.out = out;
    printf("  first load (with the install) %9.1f ms (%6.1f MB/s of file), memory grew by %8.1f MB (the file is %.1f MB: 2 channels of float32 are %.1f MB)\n", load_ns / 1e6,
           megabytes / (load_ns / 1e9), after_load - before, megabytes, megabytes * 2.0);
    printf("  \"open\" again (status %d)     %9.1f ms (%6.1f MB/s), memory peak after it %.1f MB above the start, after collect %.1f MB\n", (int)status, open_ns / 1e6,
           megabytes / (open_ns / 1e9), after_open - before, private_megabytes() - before);
    report_query("a span of 480 samples over 10 ms, playing on", &job, 0.3);
    env_close(&env);
    remove(path);
}

/* ---- deep chains ---- */

typedef struct { int depth; int result; } ChainJob;

static int ask_chain(int depth)
{
    static float out[65536];
    Env env;
    float one = 0.0f;
    int32_t status;
    int ok;
    env_open(&env, CANOPY_AUDIO_NULL);
    env_install(&env, chain_graph(depth));
    printf("installed %d gains\n", depth);
    fflush(stdout);
    env_instance(&env);
    canopy_engine_set_boundary(env.engine, "x", 1.0f);
    status = canopy_instance_read_at(env.instance, "y", 0, &one);
    ok = status == CANOPY_OK;
    status = canopy_instance_read_span(env.instance, "y", 0, 1000000, 64, out);
    ok = ok && status == CANOPY_OK;
    status = canopy_instance_read_span(env.instance, "y", 0, 1000000, 65536, out);
    ok = ok && status == CANOPY_OK;
    printf("answered: point %g (a chain of %d halvings: %g), spans %s\n", (double)one, depth, depth < 100 ? pow(0.5, depth) : 0.0, ok ? "ok" : "FAILED");
    fflush(stdout);
    env_close(&env);
    return ok ? 0 : 1;
}

static unsigned __stdcall chain_thread(void *argument)
{
    ChainJob *job = (ChainJob *)argument;
    job->result = ask_chain(job->depth);
    return 0;
}

static int measure_chain(int depth, const char *mode)
{
    if (strcmp(mode, "main") == 0) return ask_chain(depth);
    if (strcmp(mode, "worker") == 0) {
        ChainJob job;
        HANDLE handle;
        job.depth = depth; job.result = 9;
        handle = (HANDLE)_beginthreadex(NULL, 0, chain_thread, &job, 0, NULL);
        WaitForSingleObject(handle, INFINITE);
        CloseHandle(handle);
        return job.result;
    }
    {
        Env env;
        CanopyGraph *g = chain_graph(depth);
        int32_t playing = 0;
        int64_t time_ns = 0, first = -1;
        int i;
        node(g, 900000000, "realtime_preview");
        wire(g, 1 + depth, "out", 900000000, "left");
        env_open(&env, CANOPY_AUDIO_NULL);
        env_install(&env, g);
        printf("installed %d gains with a preview\n", depth);
        fflush(stdout);
        canopy_engine_action(env.engine, 900000000, "play");
        for (i = 0; i < 50; i++) {
            Sleep(20);
            canopy_preview_state(env.engine, 900000000, &playing, &time_ns);
            if (first < 0) first = time_ns;
        }
        printf("the preview played on: position moved by %.3f s\n", (double)(time_ns - first) / 1e9);
        fflush(stdout);
        env_close(&env);
        return time_ns > first ? 0 : 1;
    }
}

/* ---- the real device ---- */

typedef struct {
    CanopyEngine *engine;
    const char *action;
    volatile LONG done;
    double ns;
    int32_t status;
} ActionJob;

static unsigned __stdcall action_main(void *argument)
{
    ActionJob *job = (ActionJob *)argument;
    double start = now_ns();
    job->status = canopy_engine_action(job->engine, 900, job->action);
    job->ns = now_ns() - start;
    job->done = 1;
    return 0;
}

static void measure_device(void)
{
    static const char *STEPS[] = {"play", "pause", "play", "device", "pause", "play", "pause"};
    Env env;
    CanopyGraph *g = boundary_graph();
    int step;
    char message[300];
    int32_t length = 0, playing = 0;
    int64_t time_ns = 0;
    printf("DEVICE (the machine's real audio system, the system default device; the graph plays silence: the preview's inlets are knobs at 0). A thread presses the\n"
           "        button; this one writes a boundary value every 100 us meanwhile and records how long each write took.\n");
    node(g, 900, "realtime_preview");
    canopy_graph_set_string(g, 900, "device", "(system default)");
    env_open(&env, CANOPY_AUDIO_SYSTEM);
    env_install(&env, g);
    for (step = 0; step < 7; step++) {
        ActionJob job;
        HANDLE handle;
        Hist writes;
        double start;
        memset(&writes, 0, sizeof writes);
        job.engine = env.engine; job.action = STEPS[step]; job.done = 0; job.ns = 0.0; job.status = -1;
        handle = (HANDLE)_beginthreadex(NULL, 0, action_main, &job, 0, NULL);
        start = now_ns();
        while (!job.done) {
            double t = now_ns();
            canopy_engine_set_boundary(env.engine, "x", (float)(t / 1e12));
            hist_add(&writes, now_ns() - t);
            { double spin = now_ns(); while (now_ns() - spin < 100000.0) YieldProcessor(); }
        }
        WaitForSingleObject(handle, INFINITE);
        CloseHandle(handle);
        (void)start;
        Sleep(300);
        canopy_preview_state(env.engine, 900, &playing, &time_ns);
        canopy_engine_node_message(env.engine, 900, message, sizeof message, &length);
        printf("  press \"%-6s\": the call took %7.2f ms (status %d); %4lld boundary writes meanwhile, the slowest %7.2f ms; afterwards playing=%d, position %.3f s%s%s\n", STEPS[step],
               job.ns / 1e6, (int)job.status, writes.count, writes.max / 1e6, (int)playing, (double)time_ns / 1e9, length ? ", message: " : "", length ? message : "");
    }
    {
        double t = now_ns();
        env_close(&env);
        printf("  freeing the engine (the device is closed with it) took %.2f ms\n", (now_ns() - t) / 1e6);
    }
}

int main(int argc, char **argv)
{
    QueryPerformanceFrequency(&frequency);
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc >= 2 && strcmp(argv[1], "queries") == 0) measure_queries();
    else if (argc >= 2 && strcmp(argv[1], "scaling") == 0) {
        scaling_pinned_too = argc >= 3 && strcmp(argv[2], "--pinned") == 0;
        measure_scaling();
    }
    else if (argc >= 2 && strcmp(argv[1], "installs") == 0) measure_installs();
    else if (argc >= 2 && strcmp(argv[1], "stalls") == 0) measure_stalls();
    else if (argc >= 2 && strcmp(argv[1], "preview") == 0) measure_preview();
    else if (argc >= 3 && strcmp(argv[1], "file") == 0) measure_file(atof(argv[2]));
    else if (argc >= 4 && strcmp(argv[1], "chain") == 0) return measure_chain(atoi(argv[2]), argv[3]);
    else if (argc >= 3 && strcmp(argv[1], "device") == 0 && strcmp(argv[2], "--real-device") == 0) {
        measure_device();
    } else {
        printf("usage: bench queries | scaling | installs | stalls | preview | file MEGABYTES | chain DEPTH main|worker|preview | device --real-device\n");
        return 2;
    }
    return 0;
}
