/* Declarations shared inside the DLL (and with the C tests), not exported. */
#ifndef CANOPY_INTERNAL_H
#define CANOPY_INTERNAL_H

#include <stdatomic.h>
#include <stddef.h>
#include "canopy_engine.h"

/* Registers a built-in node type: the same checks as canopy_registry_register, except that the key must NOT contain a dot, and that the
   built-in-only flag CANOPY_FLAG_BOUNDARY_SLOT is allowed. */
int32_t canopy_registry_register_builtin(CanopyRegistry *registry, const CanopyNodeType *type);

/* A registry with no built-in node types in it (canopy_registry_new() has the boundary node types): for tests that count types. */
CanopyRegistry *canopy_registry_new_empty(void);
/* Registers the two boundary node types (canopy_boundary.c) and the file node type (canopy_fileread.c). */
int32_t canopy_boundary_register_types(CanopyRegistry *registry);
int32_t canopy_fileread_register_type(CanopyRegistry *registry);

/* ---- boundary nodes and slots (design sections 8 and 10) ----
   A built-in node type with CANOPY_FLAG_BOUNDARY_SLOT gets one slot in the engine's table of atomic floats, per node: a value the HOST writes
   (any float, with a generation number bumped by every write) and the node reads with canopy_ctx_boundary_value(). BoundaryInletNode is such a
   type. A type with CANOPY_FLAG_BOUNDARY_NODE is a boundary node (BoundaryInletNode and BoundaryOutletNode): the host addresses it by the text
   setting `name`, which such a type must have; the compiler refuses an empty or repeated name. Third-party registration refuses both flags. */
#define CANOPY_FLAG_BOUNDARY_SLOT 4u
#define CANOPY_FLAG_BOUNDARY_NODE 16u
#define CANOPY_BOUNDARY_NAME_KEY "name"
float canopy_ctx_boundary_value(CanopyCtx *ctx);                    /* 0.0f for a node without a boundary slot */
/* The host's write by node ID (canopy_engine_set_boundary does it by name): CANOPY_ERR_NODE for an unknown node, CANOPY_ERR_ARGUMENT for a node
   whose type has no boundary slot. */
int32_t canopy_engine_set_boundary_value(CanopyEngine *engine, int64_t node_id, float value);

/* ---- audio output (canopy_audio.c: miniaudio; canopy_preview.c: the realtime preview node; design sections 8, 9 and 11) ----
   CANOPY_FLAG_SERVICE is a built-in-only type flag: the node runs a thread of its own that queries the graph through an instance the engine
   makes for it (a "service instance", made and freed with the engine's lock held exclusively and not counted as an instance of the host by
   canopy_engine_free). The actions of such a node therefore run with the lock held exclusively, and canopy_engine_free destroys the shared
   resources of such nodes first, while every graph is still there. Third-party registration refuses the flag. */
#define CANOPY_FLAG_SERVICE 32u
#define CANOPY_AUDIO_RATE 48000
#define CANOPY_AUDIO_DEFAULT_NAME "(system default)"      /* the value of the preview's device setting that means the system default */
int32_t canopy_preview_register_type(CanopyRegistry *registry);

/* For tests and diagnostics (not exported). The preview node's audio thread is the miniaudio callback; tests run the same work directly.
   These return CANOPY_OK, CANOPY_ERR_NODE (no such node in the installed graph) or CANOPY_ERR_ARGUMENT (not a preview node, a NULL engine). */
int32_t canopy_preview_prepare(CanopyEngine *engine, int64_t node_id, int32_t playing);          /* the buffers and the service instance, without a device; sets "playing" */
int32_t canopy_preview_fill(CanopyEngine *engine, int64_t node_id, float *stereo, uint32_t frames);   /* one audio callback, run by the caller */
int32_t canopy_preview_counts(CanopyEngine *engine, int64_t node_id, int64_t *callbacks, int64_t *opens);   /* audio callbacks so far, devices opened so far */
const atomic_llong *canopy_preview_callback_counter(CanopyEngine *engine, int64_t node_id);   /* the callbacks counter itself, to be read without any lock (NULL: no such preview node); valid while the node lives */
int32_t canopy_preview_stop_device(CanopyEngine *engine, int64_t node_id);                       /* the device stops by itself, as when it is unplugged */
int32_t canopy_engine_service_count(CanopyEngine *engine);                                        /* the instances the engine made for its own nodes */
/* Test hook: `hook` is called (once per press of a service node's button) at the moment when the button has let go of the shared lock and has not
   yet taken the exclusive one, which is where another thread's install can replace the graph; NULL turns it off. */
void canopy_engine_test_action_window(void (*hook)(void));

/* ---- memory ----
   Every allocation of the library goes through these, so that tests can count live blocks (a leak check that works in every build) and make
   the Nth allocation fail (to run the out-of-memory paths). Blocks are zero-filled. The counters are atomic; the failure hook is for
   single-threaded tests. */
void *canopy_alloc(size_t size);                                    /* zero-filled; NULL on failure */
void *canopy_realloc(void *block, size_t old_size, size_t new_size);  /* the new tail is zero-filled; NULL on failure (block stays valid) */
void canopy_free(void *block);                                      /* NULL is fine */
/* Test hook: after `n` more successful allocations every allocation fails, until called again; a negative n turns the failures off. */
void canopy_alloc_fail_after(int64_t n);
/* Test hook: the allocation after `n` more successful ones fails, that one only (then everything works again); a negative n turns it off. It
   reaches the code that copes with ONE failed allocation (a node whose shared resource could not be made), which the hook above cannot. */
void canopy_alloc_fail_once(int64_t n);
/* The same two calls, counted the same and freed with canopy_free, but never made to fail by canopy_alloc_fail_after: for code that is not ours
   (miniaudio), whose own paths after a failed allocation are not ours to test: it was found to leak when memory runs out inside ma_device_init
   (its clean-up returns early for a device that is half made, leaving the intermediary buffer, and with the null backend a waiting thread). */
void *canopy_alloc_unhooked(size_t size);
void *canopy_realloc_unhooked(void *block, size_t old_size, size_t new_size);

/* A pool owns many small blocks and frees them all together, so a structure built of many pieces needs one cleanup, also when building it
   fails half way. Blocks are zero-filled. */
typedef struct {
    void **blocks;
    int32_t count, capacity;
} CanopyPool;

void *canopy_pool_alloc(CanopyPool *pool, size_t size);             /* NULL on failure */
char *canopy_pool_strdup(CanopyPool *pool, const char *text);       /* NULL on failure */
void canopy_pool_free(CanopyPool *pool);                            /* frees every block; the pool can be used again */

/* The time in nanoseconds of sample `frame` of a sample grid of `rate` Hz anchored at t = 0 (sample k at k / rate seconds): the exact value
   rounded half up, the inverse of canopy_ns_to_frame. Used by nodes with an internal sampling rate. rate must be 1 .. CANOPY_INTERNAL_RATE_MAX;
   returns CANOPY_ERR_RATE or CANOPY_ERR_OVERFLOW (the result does not fit in an int64). */
int32_t canopy_frame_to_ns(int64_t frame, int64_t rate, int64_t *ns);

/* The size in floats of a scratch arena that holds `buffers` buffers of the largest n; CANOPY_ERR_OVERFLOW if that many buffers cannot be
   addressed (the size in bytes must fit a signed 64-bit integer). */
int32_t canopy_arena_floats(int64_t buffers, int64_t *floats);

/* ---- sample placement of a span query (design section 5) ----
   A span [t0, t1) with n samples is planned once: sample i is at t0 + i*q + floor(i*r / n), where (q, r) is the floor division of t1 - t0 by n
   (0 <= r < n). */
typedef struct {
    int64_t t0, q, r, n;
} CanopySpanPlan;

/* 1 if t1 - t0 does not fit in a signed 64-bit integer. */
static inline int canopy_span_overflows(int64_t t0, int64_t t1)
{
    return (t0 < 0 && t1 > INT64_MAX + t0) || (t0 > 0 && t1 < INT64_MIN + t0);
}

/* CANOPY_ERR_N if n is not in 1 .. CANOPY_MAX_N, CANOPY_ERR_OVERFLOW if t1 - t0 does not fit in an int64 (checked in this order). */
int32_t canopy_span_plan(int64_t t0, int64_t t1, int64_t n, CanopySpanPlan *plan);
/* The time of sample i, 0 <= i < n (not checked). */
int64_t canopy_span_plan_time(const CanopySpanPlan *plan, int64_t i);

#endif
