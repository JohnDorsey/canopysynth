/* The multi-thread stress of plan step 13 (tests/c/test_stress.c): everything a host and an editor do at once, with every answer checked. */
#ifndef STRESS_H
#define STRESS_H

#include <stdint.h>

typedef struct {
    double seconds;                 /* how long to run */
    uint64_t seed;                  /* the seed of every thread's random numbers (the interleaving of the threads is the system's, not the seed's) */
    int readers;                    /* threads that query, each through an instance of its own (at least 1; the last one is slow on purpose) */
    int preview;                    /* 1: the realtime preview node is played, paused, moved and switched between devices (miniaudio's null backend) */
    int verbose;                    /* 1: print the figures at the end whether or not the run passed */
} StressOptions;

typedef struct {
    long long queries, span_queries, point_queries;         /* checked answers (the readers' and the lifecycle thread's) */
    long long unchecked;                                    /* answers whose set of possible versions was too wide to check (counted, not passed over silently) */
    long long installs, bad_installs, opens, collects;      /* the installing thread */
    long long boundary_writes, knob_writes;
    long long instance_cycles;                              /* instances made, queried and freed again */
    long long info_calls, preview_actions;
    long long playing_seen;                                 /* times the info thread found the preview node playing (0 when the preview is off) */
    long long file_a_seen, file_b_seen;                     /* spans of the file node that held one file or the other */
    long long max_spread_versions;                          /* the widest range of graph versions a single answer could have come from */
    long long small_query_ns_max;                           /* the slowest query of 64 samples or fewer, in nanoseconds, over all readers */
    long long small_query_ns_p999, small_query_ns_p9999;    /* the time within which 99.9% and 99.99% of those queries finished (bucket upper bounds) */
    long long problems;                                     /* what went wrong (the first few are printed) */
} StressResult;

/* Runs the stress; returns 1 if every check passed, 0 if not. Prints the problems found (the first few), and the figures if options->verbose or it failed. */
int stress_run(const StressOptions *options, StressResult *result);

#endif
