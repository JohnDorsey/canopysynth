/* The library's private structures: shared by canopy_graph.c, canopy_engine.c, canopy_install.c and canopy_instance.c. Not exported, not for
   hosts or node authors (they use canopy_engine.h and canopy_node.h). */
#ifndef CANOPY_CORE_H
#define CANOPY_CORE_H

#include <stdatomic.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
#error "canopysynth version 1 is Windows only (the author's decision at plan step 0): a lock for another platform is needed below"
#endif
#include "canopy_engine.h"
#include "canopy_internal.h"

/* ---- the engine's lock ----
   Taken exclusively by everything that changes the engine's lists (installing, making and freeing an instance, collecting), and shared by
   the host calls that only use what the lists hold (knob and boundary writes, actions), so that those cannot find a graph or a record freed
   under them. It is never taken by a query, and never held while a handler can call back into the engine (handlers have no way to). */
typedef SRWLOCK CanopyLock;
static inline void canopy_lock_exclusive(CanopyLock *lock) { AcquireSRWLockExclusive(lock); }
static inline void canopy_unlock_exclusive(CanopyLock *lock) { ReleaseSRWLockExclusive(lock); }
static inline void canopy_lock_shared(CanopyLock *lock) { AcquireSRWLockShared(lock); }
static inline void canopy_unlock_shared(CanopyLock *lock) { ReleaseSRWLockShared(lock); }

/* ---- the graph description (canopy_graph.c) ---- */

typedef struct { int64_t id; char *type_key; } CanopyGraphNode;

typedef enum { CANOPY_VALUE_INT, CANOPY_VALUE_FLOAT, CANOPY_VALUE_STRING } CanopyValueKind;

typedef struct {
    int64_t node;
    char *key;
    CanopyValueKind kind;
    int64_t i;
    double f;
    char *s;
} CanopyGraphSetting;

typedef struct { int64_t node; char *key; float value; } CanopyGraphKnob;

typedef struct { int64_t from_node; char *outlet_key; int64_t to_node; char *inlet_key; } CanopyGraphConnection;

struct CanopyGraph {
    CanopyPool pool;                                  /* the strings */
    CanopyGraphNode *nodes;             int32_t n_nodes, cap_nodes;
    CanopyGraphSetting *settings;       int32_t n_settings, cap_settings;
    CanopyGraphKnob *knobs;             int32_t n_knobs, cap_knobs;
    CanopyGraphConnection *connections; int32_t n_connections, cap_connections;
};

/* ---- slots: the shared table of atomic floats (design section 8) ----
   A slot holds a float32 as its bit pattern in an atomic integer, and a generation number that is bumped after every write. The value is
   stored first and the generation bumped second, so a reader that reads the generation first and the value second can only see a value that
   is newer than its generation, never older: a result stamped with that generation is at worst discarded as stale, never kept wrongly.
   Knobs (one per inlet) and boundary values (one per boundary node) are slots. */
typedef struct CanopySlot {
    atomic_uint bits;
    atomic_uint_fast64_t generation;
} CanopySlot;

static inline float canopy_slot_load(CanopySlot *slot)
{
    unsigned bits = atomic_load_explicit(&slot->bits, memory_order_acquire);
    float value;
    memcpy(&value, &bits, sizeof value);
    return value;
}

static inline void canopy_slot_set(CanopySlot *slot, float value)       /* without a generation bump: for a slot nobody has seen yet */
{
    unsigned bits;
    memcpy(&bits, &value, sizeof bits);
    atomic_store_explicit(&slot->bits, bits, memory_order_release);
}

static inline void canopy_slot_write(CanopySlot *slot, float value)     /* a real write: value first, then the generation */
{
    canopy_slot_set(slot, value);
    atomic_fetch_add_explicit(&slot->generation, 1, memory_order_acq_rel);
}

static inline unsigned canopy_float_bits(float value)
{
    unsigned bits;
    memcpy(&bits, &value, sizeof bits);
    return bits;
}

/* A step of the digest of generation numbers (canopy_ctx_upstream_stamp): both multiplications by an odd constant and the xor-shift are
   bijections, so changing any one input changes the result. */
static inline uint64_t canopy_mix(uint64_t h, uint64_t v)
{
    h ^= v;
    h *= 0x9E3779B97F4A7C15ULL;
    h ^= h >> 32;
    return h;
}

#define CANOPY_MESSAGE_BYTES 256        /* a node's message is cut to 255 bytes (at a character boundary): it can always be stored, also when memory has run out */

/* ---- records: what survives installing another graph, per node ID and node type (canopy_install.c) ---- */

struct CanopyCNode;

typedef struct CanopyNodeRecord {
    uint64_t uid;                      /* never reused: tells a node that came back from one that stayed */
    int64_t id;
    const CanopyNodeType *type;
    CanopyPool pool;                   /* owns the slots and the arrays below */
    CanopySlot **knobs;                /* one slot per inlet of the type, in the type's order */
    CanopySlot boundary;               /* the boundary slot (types with CANOPY_FLAG_BOUNDARY_SLOT) */
    atomic_uint_fast64_t shared_generation;     /* bumped by canopy_ctx_shared_changed */
    int shared_made;                   /* create_shared has been called (it may have returned NULL: no resource) */
    void *shared;                      /* what create_shared returned */
    uint64_t *setting_gen;             /* one per setting: bumped when an install changes the setting's value */
    const struct CanopyCNode *published;   /* this node in the installed graph (NULL before the first install that has it) */
    int32_t refs;                      /* the compiled graphs still held that contain it */
    int fresh;                         /* made by the install in progress */
    struct CanopyEngine *engine;       /* the engine it belongs to */
    char message[CANOPY_MESSAGE_BYTES];   /* what the node last said about itself (canopy_ctx_set_message), "" for nothing; guarded by the engine's message lock */
} CanopyNodeRecord;

/* ---- the compiled graph (built in canopy_engine.c and canopy_install.c, immutable once installed) ---- */

typedef struct { int64_t i; double f; char *s; } CanopySettingValue;      /* INT and CHOICE use i, FLOAT f, STRING and PATH s (never NULL) */

typedef struct { int32_t node; int32_t outlet; } CanopyLink;              /* node < 0: the inlet is not connected */

typedef struct CanopyCNode {
    int64_t id;
    const CanopyNodeType *type;
    CanopyLink *links;                 /* one per inlet */
    CanopySlot **knobs;                /* one per inlet: its knob slot (filled in when the graph is installed) */
    float *knob_start;                 /* one per inlet: the position the description asks for */
    CanopySettingValue *settings;      /* one per setting of the type */
    uint64_t *setting_gen;             /* one per setting: its generation number in this graph */
    CanopyNodeRecord *record;
    void *shared;                      /* the shared resource (filled in when the graph is installed) */
    atomic_uint_fast64_t **cone_gens;  /* the generation counters of every source upstream of this node (itself included) */
    int32_t n_cone_gens;
    uint64_t cone_static;              /* a digest of what is upstream (identities, wiring) and of the setting generations */
} CanopyCNode;

typedef struct { const char *name; int32_t node; int32_t kind; } CanopyBoundary;    /* kind: CANOPY_BOUNDARY_INLET or _OUTLET; node: index in nodes[] */

typedef struct CanopyCompiled {
    CanopyPool pool;                   /* owns every array above */
    uint64_t serial;                   /* increases with every install (a failed one uses up a number): 1, 2, 3... when none has failed */
    int32_t n_nodes;
    CanopyCNode *nodes;                /* sorted by id */
    int32_t n_boundary;
    CanopyBoundary *boundary;          /* the boundary nodes, sorted by name (names are non-empty and unique) */
    int64_t arena_floats;              /* the size of one instance's scratch arena */
    int32_t has_cycle;
} CanopyCompiled;

/* The node with this id (binary search); NULL if there is none. *index (may be NULL) is its position in nodes[]. */
const CanopyCNode *canopy_compiled_find(const CanopyCompiled *graph, int64_t id, int32_t *index);
/* The boundary node with this name (binary search); NULL if there is none. */
const CanopyBoundary *canopy_compiled_find_boundary(const CanopyCompiled *graph, const char *name);

/* ---- instances, and the packages that move them to a newly installed graph (canopy_instance.c) ----
   Installing a graph prepares, for every live instance, a package: everything the instance needs to run the new graph, built by the
   installing thread. The instance applies the packages in order at the start of its next query, by swapping pointers; nothing is allocated
   or freed there. A package is shared between the two threads like this: the installing thread builds it completely, then links it to the
   previous one with a release store; the instance reads the link with an acquire load, applies the package, records in it what it took out
   of use (the old table of states, the old arena) and sets `done` last; the installing thread then frees the spent state, later the node. */
typedef struct CanopyPackage {
    _Atomic(struct CanopyPackage *) next;
    atomic_int done;
    int payload_disposed;
    const CanopyCompiled *from, *to;   /* the graph the instance runs before, and after */
    int32_t *map;                      /* per node of `to`: the node of `from` whose state it keeps, or -1 */
    unsigned char *carried;            /* per node of `from`: 1 if its state is kept */
    void **fresh;                      /* per node of `to`: the new state made for it (map -1) */
    void **new_states;                 /* the table of states the instance will have */
    void *new_arena_block;             /* a bigger arena, if `to` needs one (else NULL) */
    float *new_arena;
    int64_t new_arena_floats;
    void **old_states;                 /* filled in by the instance: the table it had */
    void *old_arena_block;             /* filled in by the instance: the arena it had, if replaced */
} CanopyPackage;

struct CanopyInstance {
    CanopyEngine *engine;
    atomic_int busy;
    atomic_uint_fast64_t epoch;        /* odd while a host query runs in this instance, even between them; read by the thread that retires data */
    /* used by the thread that queries (and read by the installing thread only through the atomics of the packages) */
    const CanopyCompiled *graph;
    void **states;                     /* one per node: what create_instance returned */
    void *arena_block;                 /* what was allocated... */
    float *arena;                      /* ...and the 64-byte aligned start of the arena inside it */
    int64_t arena_floats, arena_top;
    CanopyPackage *applied;            /* the last package applied (a sentinel at first) */
    /* used under the engine's lock only */
    CanopyPackage *first, *tail;       /* the oldest package not yet freed, and the newest */
    const CanopyCompiled *planned_graph;   /* the graph the instance will run once every package is applied */
    int64_t planned_arena_floats;
};

/* ---- the engine ---- */

struct CanopyEngine {
    const CanopyRegistry *registry;
    CanopyLock lock;
    CanopyNodeRecord **records;        int32_t n_records, cap_records;      /* sorted by (id, type) */
    CanopyCompiled **compiled;         int32_t n_compiled, cap_compiled;    /* the graphs still held, oldest first */
    _Atomic(const CanopyCompiled *) current;
    CanopyInstance **instances;        int32_t n_instances, cap_instances;  /* the live instances */
    uint64_t serial;                   /* the serial of the newest graph made */
    uint64_t uid;                      /* the last record uid given */
    CanopyLock retire_lock;            /* guards `retired` (taken after the engine lock, never before it) */
    struct CanopyRetired *retired;     /* data given up by nodes, waiting until no query that began before can still be reading it */
    CanopyLock message_lock;           /* guards the `message` of every record */
    char error[400];
};

/* canopy_install.c (the engine's lock held exclusively) */
int32_t canopy_install(CanopyEngine *engine, CanopyCompiled *compiled);      /* takes ownership of `compiled`, also when it fails */
void canopy_reclaim(CanopyEngine *engine);                                    /* frees what no instance can use any more */
void canopy_free_graph(CanopyEngine *engine, CanopyCompiled *compiled);
void canopy_compiled_release(CanopyCompiled *compiled);                      /* frees a compiled graph that holds no record references */

/* canopy_retire.c (the engine's lock held, shared or exclusive) */
void canopy_retire_collect(CanopyEngine *engine);                             /* frees the retired data that no query can still be reading */
void canopy_retire_forget(CanopyEngine *engine, CanopyInstance *instance);    /* an instance is going: nothing waits for it any more */

/* canopy_package.c: the thread that queries applies the packages that were prepared for its instance (no allocation, no lock) */
void canopy_instance_adopt(CanopyInstance *instance);

/* canopy_package.c (the engine's lock held exclusively) */
CanopyPackage *canopy_package_build(CanopyEngine *engine, CanopyInstance *instance, const CanopyCompiled *to);   /* NULL if memory ran out */
void canopy_package_discard(CanopyPackage *package);                         /* a package that was never queued or applied */
void canopy_package_enqueue(CanopyInstance *instance, CanopyPackage *package);
void canopy_instance_reap(CanopyInstance *instance);                          /* frees what the instance has finished with */
uint64_t canopy_instance_oldest_serial(CanopyInstance *instance);            /* the oldest graph the instance may still use */

struct CanopyCtx {
    CanopyInstance *instance;          /* NULL when no instance is involved (everything outside a query) */
    const CanopyCNode *node;
    int32_t node_index;
    int querying;                      /* 1 inside query_at and query_span */
    int64_t mark;                      /* the arena top when this call began */
    int32_t scratch_taken;
    void *state;                       /* the node's instance state, if any */
};

/* A context for the handlers that run outside a query. */
static inline void canopy_ctx_setup(struct CanopyCtx *ctx, const CanopyCNode *node, int32_t node_index, void *state)
{
    ctx->instance = NULL;
    ctx->node = node;
    ctx->node_index = node_index;
    ctx->querying = 0;
    ctx->mark = 0;
    ctx->scratch_taken = 0;
    ctx->state = state;
}

#endif
