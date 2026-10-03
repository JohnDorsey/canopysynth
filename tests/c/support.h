/* Helpers shared by the C tests of the engine: guarded output buffers, small test node types, and a rig that builds a graph, an engine and
   an instance and checks at the end that every allocation was returned. */
#ifndef SUPPORT_H
#define SUPPORT_H

#include <stdint.h>
#include "../../src/canopy_engine.h"
#include "../../src/canopy_internal.h"
#include "ctest.h"

/* ---- guarded output buffers ----
   n floats that all hold an "unwritten" pattern, between two guard zones of canary values. After a call: guarded_guards_intact() says
   nothing was written outside the n floats, guarded_unwritten() how many floats the callee never wrote. */
#define GUARD_FLOATS 16
typedef struct {
    float *block;
    float *data;
    int64_t n;
} Guarded;

Guarded guarded_new(int64_t n);
void guarded_reset(Guarded *g);                                   /* back to the freshly made state: unwritten data, intact guards */
void guarded_free(Guarded *g);
int guarded_guards_intact(const Guarded *g);
int64_t guarded_unwritten(const Guarded *g);
int guarded_all_zero(const Guarded *g);                           /* every float is +0.0 (all bits clear) */
int guarded_equals(const Guarded *g, const float *expected);      /* bitwise equal to expected[0..n) */
int guarded_bits_equal(const Guarded *a, const Guarded *b);       /* bitwise equal data (same n) */
uint32_t float_bits(float value);

/* ---- a log of the calls the recorder node types receive ---- */
#define CALL_LOG_MAX 70000
typedef struct {
    int is_span;
    int32_t outlet;
    int64_t t0, t1, n;                                           /* a point call has t0 = its t, t1 = t0, n = 1 */
} LoggedCall;
extern LoggedCall support_calls[CALL_LOG_MAX];
extern int support_ncalls;
void support_calls_reset(void);

/* ---- the test node types ----
   test.const         out = the setting `value` (FLOAT), at any time. Pointwise (query_at only).
   test.const_span    the same with query_span only (a node with no point handler).
   test.time          outlets a = (float)t and b = 2 * (float)t. Pointwise.
   test.recorder      out = 0.5; logs each point call. Pointwise.
   test.recorder_span out = 0.25; logs each span call. Span only.
   test.gain          inlets in (knob 0) and gain (knob 1); out = in * gain. Both handlers (the span handler uses one scratch buffer).
   test.sum           inlets a and b; out = a + b. Pointwise.
   test.shift         inlet in; out(t) = in(t + shift), the setting `shift` (INT, ns): looks ahead. Both handlers.
   test.sink          inlets in0 (knob 0) and in1 (knob 0.5), no outlets: the host reads through its inlets.
   test.failing       inlet in; out: query_at returns 5.0, query_span writes 123 into out and returns status 77.
   test.failing_span_only  outlet out: query_span only, as test.failing. */
#define FAILING_STATUS 77
/* More (plan step 4: generation numbers, state, adoption of a new graph):
   test.saw        out(t) = a sawtooth of period 0.25 s from -1 up to 1: (t mod 250000000) * (2 / 250000000) - 1, as a float. Pointwise.
   test.jitter     out(t) = (t mod 1000) / 1000 as a float: moves by 0.001 for every nanosecond. Pointwise.
   test.config     out = 0.0; one setting of every kind and nothing reads them: text (STRING, "a"), file (PATH, ""), mode (CHOICE of x, y, z),
                   level (FLOAT), count (INT). Pointwise.
   test.counter    out = the setting `value`; counts every point call in support_counts[tag] (setting `tag`). Pointwise.
   test.stamp      inlet in; every call records canopy_ctx_upstream_stamp() in support_stamps[tag]; out = in(t) if the setting `pass` is 1 (the
                   default), else 0 without asking upstream. Settings tag, pass and salt (an INT nothing reads: a setting whose change must
                   change the stamp).
   test.source     out = its shared resource, a float that starts at 1.0; the action "bump" adds 1 and calls canopy_ctx_shared_changed().
                   Counted in support_shared_created / support_shared_destroyed.
   test.state      out = a counter in its instance state: 4, 5, 6... on successive queries of one instance. Counted in support_state_created /
                   support_state_destroyed.
   test_boundary   (a built-in key: it has a boundary slot) out = the value the host last wrote with canopy_engine_set_boundary_value, 0.0 at first.
   test_filter     the hidden filter of the DLL, registered by canopy_registry_add_test_nodes (see src/canopy_test_nodes.c). */
#define SUPPORT_TAGS 16
extern int support_counts[SUPPORT_TAGS];
extern uint64_t support_stamps[SUPPORT_TAGS];
extern int support_shared_created, support_shared_destroyed, support_state_created, support_state_destroyed;
void support_counters_reset(void);
float support_saw(int64_t t);                                     /* the formula of test.saw, for references */
float support_jitter(int64_t t);                                  /* test.jitter: (t mod 1000) / 1000 as a float, a value that changes with every nanosecond */

CanopyRegistry *support_registry(void);                           /* a new registry holding all of them */
void support_add_type(CanopyRegistry *registry, const CanopyNodeType *type);       /* registers one more (checked) */
void support_add_builtin(CanopyRegistry *registry, const CanopyNodeType *type);    /* the same, as a built-in type (flat key, boundary flag allowed) */
CanopyNodeType support_base_type(const char *key, const char *name);                /* a descriptor to fill in: ABI fields set, no ports */

/* ---- the rig ---- */
typedef struct {
    CanopyRegistry *registry;
    CanopyGraph *graph;
    CanopyEngine *engine;
    CanopyInstance *instance;
    int64_t live_before;
} Rig;

void rig_open(Rig *rig);                                           /* registry with the test node types, empty graph description, engine */
void rig_node(Rig *rig, int64_t id, const char *type);
void rig_connect(Rig *rig, int64_t from, const char *outlet, int64_t to, const char *inlet);
void rig_install(Rig *rig);                                        /* set_graph and new_instance, both checked */
void rig_close(Rig *rig);                                          /* frees all of it and checks that no allocation is left over */

#endif
