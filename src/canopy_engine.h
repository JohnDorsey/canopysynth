/* canopysynth - graphs, the engine and instances (docs/canopy_design.md sections 5 to 8, 10 and 16).

   The life of a graph:
     1. A host describes it with a CanopyGraph: nodes (an integer ID and a node-type key), settings, knob positions and connections. The
        description is only data; nothing is checked until it is compiled.
     2. canopy_engine_set_graph() compiles it into an immutable compiled graph and installs it. Every fault (an unknown node type, a
        duplicate node ID, two connections into one inlet...) is a CANOPY_ERR_GRAPH with a message from canopy_engine_last_error(), and the
        previously installed graph, if any, stays in place.
     3. canopy_engine_new_instance() makes one instance per querying thread; the instance answers queries.
     4. Installing another graph (compile-and-swap) never touches a running instance: for every live instance the engine prepares, before it
        publishes anything, everything the instance needs to run the new graph (its new table of node states, state for any new node, a
        bigger scratch arena if the graph needs one). The instance adopts the new graph at the start of its next query by swapping pointers: a
        query never allocates or frees memory. The state of a node that is in both graphs (same node ID and node type) is carried over; the
        state of a node that went is destroyed later, by the thread that installs, collects or frees an instance.
   Knob positions (and boundary values) live in the engine, not in the compiled graph: they are atomic, can be written from any thread at
   any time, and survive installing another graph for nodes with the same ID. Each has a generation number that is bumped by every write.

   Threads: a CanopyGraph is used by one thread. canopy_engine_new and canopy_engine_free are called with no other call to the engine in
   progress. Every other call may be made from any thread: the engine holds a lock inside (except that canopy_engine_last_error reads the
   message of the last canopy_engine_set_graph, so ask it from the thread that installed). Installing (canopy_engine_set_graph), collecting,
   making and freeing an instance take the lock exclusively, one at a time; setting and getting a knob, writing a boundary value, pressing a button
   (canopy_engine_action, whose handler runs in the calling thread while the lock is held shared) and the two counts take it shared, so
   they run together and wait only for an install or the like in progress. A query never takes the lock and never waits for it. The node-type
   handlers create_shared, destroy_shared, create_instance and destroy_instance run in whichever thread installs, collects, makes or frees
   an instance, with the lock held (never in the thread that queries). A CanopyInstance is used by one thread at a time (a second concurrent
   use is refused with CANOPY_ERR_BUSY where that can be detected). The registry must outlive the engine, and every instance must be freed
   before its engine. */
#ifndef CANOPY_ENGINE_H
#define CANOPY_ENGINE_H

#include "canopy_node.h"

/* ---- the graph description ---- */
typedef struct CanopyGraph CanopyGraph;

CANOPY_API CanopyGraph *canopy_graph_new(void);
CANOPY_API void canopy_graph_free(CanopyGraph *graph);

/* Each call below only records its arguments (copying the strings); it returns CANOPY_OK, CANOPY_ERR_ARGUMENT (a NULL pointer) or
   CANOPY_ERR_MEMORY. Setting the same setting or knob twice keeps the last value. */
CANOPY_API int32_t canopy_graph_add_node(CanopyGraph *graph, int64_t node_id, const char *type_key);
/* INT settings, and CHOICE settings by the index of the choice. */
CANOPY_API int32_t canopy_graph_set_int(CanopyGraph *graph, int64_t node_id, const char *setting_key, int64_t value);
CANOPY_API int32_t canopy_graph_set_float(CanopyGraph *graph, int64_t node_id, const char *setting_key, double value);
/* STRING and PATH settings. */
CANOPY_API int32_t canopy_graph_set_string(CanopyGraph *graph, int64_t node_id, const char *setting_key, const char *value);
/* The position of an inlet's knob, -1 .. 1; an inlet whose knob is not set starts at its node type's default knob position. */
CANOPY_API int32_t canopy_graph_set_knob(CanopyGraph *graph, int64_t node_id, const char *inlet_key, float value);
/* A connection from an outlet to an inlet. */
CANOPY_API int32_t canopy_graph_connect(CanopyGraph *graph, int64_t from_node, const char *outlet_key, int64_t to_node, const char *inlet_key);

/* ---- the engine ---- */
typedef struct CanopyEngine CanopyEngine;

/* The registry is borrowed: it must outlive the engine. */
CANOPY_API CanopyEngine *canopy_engine_new(const CanopyRegistry *registry);

/* Frees the engine, its compiled graphs and its shared resources (calling each node type's destroy_shared). Returns CANOPY_ERR_BUSY, and
   frees nothing, while an instance made from it still exists. */
CANOPY_API int32_t canopy_engine_free(CanopyEngine *engine);

/* Compiles `graph` and installs it. Faults (all CANOPY_ERR_GRAPH, the message names the node, connection or setting at fault):
     two nodes with one ID; an unknown node type; a setting, knob or connection that names a node, setting, inlet or outlet that does not
     exist; a setting given with a call of the wrong kind (set_int for a FLOAT setting...); a CHOICE index out of range; a FLOAT setting that
     is not finite; an internal sampling rate outside 1 .. 384000; a knob that is not finite or is outside -1 .. 1; two connections into
     one inlet. Loops are not a fault (design section 8). On a fault nothing changes.
   Nodes whose IDs were in an earlier graph keep their knob slots and shared resources; a knob position in the description replaces the
   slot's current value (and counts as a write when it differs), and a setting whose value differs from the installed graph's has its
   generation number bumped. Instances made earlier adopt the new graph at the start of their next query (see above). Memory running out
   while installing returns CANOPY_ERR_MEMORY and leaves the engine and every instance as they were. Older graphs, and the shared
   resources of nodes that are in none of the graphs still in use, are freed when no instance can use them any more. */
CANOPY_API int32_t canopy_engine_set_graph(CanopyEngine *engine, const CanopyGraph *graph);

/* Frees what is no longer needed: node state that instances have replaced, older graphs no instance uses any more, shared resources of
   nodes that are in no graph in use. Installing and freeing an instance do the same. Call it after instances have adopted a graph, to
   release the memory of the old one at once. Returns the number of compiled graphs still held (the installed one included). */
CANOPY_API int32_t canopy_engine_collect(CanopyEngine *engine);

/* For tests and diagnostics: the serial number of the installed graph, 0 if none. It increases with every install (1, 2, 3... unless an
   install has failed for lack of memory, which uses up a number). */
CANOPY_API int64_t canopy_engine_graph_serial(CanopyEngine *engine);

/* The reason for the last failed canopy_engine_set_graph (empty when it did not fail). */
CANOPY_API const char *canopy_engine_last_error(const CanopyEngine *engine);

/* The number of nodes of the installed graph (0 when there is none). */
CANOPY_API int32_t canopy_engine_node_count(CanopyEngine *engine);

/* A knob of the installed graph, by node ID and inlet index. set_knob stores an atomic float and bumps the knob's generation number; it
   refuses (CANOPY_ERR_ARGUMENT) a value that is not finite or is outside -1 .. 1, and returns CANOPY_ERR_NODE / CANOPY_ERR_PORT for a node
   or inlet that does not exist. get_knob reports the position and the generation number (either output pointer may be NULL). */
CANOPY_API int32_t canopy_engine_set_knob(CanopyEngine *engine, int64_t node_id, int32_t inlet, float value);
CANOPY_API int32_t canopy_engine_get_knob(CanopyEngine *engine, int64_t node_id, int32_t inlet, float *value, uint64_t *generation);

/* A button of a node was pressed: calls the node type's on_action(ctx, action) on the calling (UI) thread. CANOPY_ERR_NODE if the node does
   not exist; a node type without an on_action handler ignores the call. */
CANOPY_API int32_t canopy_engine_action(CanopyEngine *engine, int64_t node_id, const char *action);

/* What a node of the installed graph last said about itself with canopy_ctx_set_message ("file not found..."; empty for nothing to say):
   copied into `buffer`, cut to `capacity` bytes and NUL-terminated if too small (buffer may be NULL when the capacity is 0); *length gets the
   full length in bytes. CANOPY_ERR_NODE for an unknown node ID. */
CANOPY_API int32_t canopy_engine_node_message(CanopyEngine *engine, int64_t node_id, char *buffer, int32_t capacity, int32_t *length);

/* ---- boundary nodes: how the host talks to the installed graph (design section 10) ----
   The host addresses a boundary node by its name (the text setting `name`; compiling refuses a graph in which a name is empty or used twice).
   A boundary inlet is written by the host; a boundary outlet is read by it. Names are case-sensitive and compared byte for byte. */
enum { CANOPY_BOUNDARY_INLET = 0, CANOPY_BOUNDARY_OUTLET = 1 };

/* Writes `value` (any float: NaN, infinities and values beyond -1 .. 1 included, nothing is clamped) to the boundary inlet called `name`: an
   atomic store, visible to every query that starts after it, from any thread. CANOPY_ERR_NODE if the installed graph has no boundary inlet
   of that name (a boundary outlet of that name does not count), CANOPY_ERR_ARGUMENT for a NULL pointer. The value belongs to the node, not to
   its name or to a graph description: it survives installing another graph, also when the node is renamed, and starts at 0.0 for a new node. */
CANOPY_API int32_t canopy_engine_set_boundary(CanopyEngine *engine, const char *name, float value);

/* The boundary nodes of the installed graph, sorted by name (byte order): how many, and the one at `index` (0 .. count - 1). `name` receives
   the name, NUL-terminated and cut to `name_capacity` bytes if that is too small (it may be NULL when the capacity is 0); *name_length gets
   its full length in bytes without the NUL, so a caller can ask again with a buffer that is big enough. Every output pointer may be NULL.
   *kind is CANOPY_BOUNDARY_INLET or _OUTLET. CANOPY_ERR_INDEX if there is no such index (the graph can change between the two calls). */
CANOPY_API int32_t canopy_engine_boundary_count(CanopyEngine *engine);
CANOPY_API int32_t canopy_engine_boundary_at(CanopyEngine *engine, int32_t index, char *name, int32_t name_capacity, int32_t *name_length,
                                             int32_t *kind, int64_t *node_id);

/* ---- instances ---- */
typedef struct CanopyInstance CanopyInstance;

/* A new instance over the installed graph: its own instance state for every node (create_instance) and its own scratch arena. NULL if no
   graph is installed or memory ran out. The engine keeps a list of live instances (for the preparing described at the top); the instance
   leaves it when freed. */
CANOPY_API CanopyInstance *canopy_engine_new_instance(CanopyEngine *engine);
CANOPY_API void canopy_instance_free(CanopyInstance *instance);

/* For tests and diagnostics: the number of floats in the instance's scratch arena, and the serial number of the graph it runs now (an
   installed graph is adopted at the instance's next query, so this can be older than canopy_engine_graph_serial). */
CANOPY_API int64_t canopy_instance_arena_floats(const CanopyInstance *instance);
CANOPY_API int64_t canopy_instance_graph_serial(const CanopyInstance *instance);

/* The host reads from a graph through an inlet (this is what a BoundaryOutletNode does): the same two kinds of query as canopy_inlet_at and
   canopy_inlet_span, with the same statuses and the same knob fallback, plus CANOPY_ERR_NODE for an unknown node ID and CANOPY_ERR_BUSY
   when the instance is in use. A point query that cannot be answered returns 0.0f. */
CANOPY_API float canopy_instance_inlet_at(CanopyInstance *instance, int64_t node_id, int32_t inlet, int64_t t);
CANOPY_API int32_t canopy_instance_inlet_span(CanopyInstance *instance, int64_t node_id, int32_t inlet, int64_t t0, int64_t t1, int64_t n,
                                              float *out);

/* The same two queries through the boundary outlet called `name` (in the graph the instance runs; a newly installed graph is adopted first):
   statuses as above, with CANOPY_ERR_NODE when there is no boundary outlet of that name (a boundary inlet of that name does not count) and
   CANOPY_ERR_ARGUMENT for a NULL `name`; a point query that cannot be answered returns 0.0f. */
CANOPY_API float canopy_instance_read_at(CanopyInstance *instance, const char *name, int64_t t);
CANOPY_API int32_t canopy_instance_read_span(CanopyInstance *instance, const char *name, int64_t t0, int64_t t1, int64_t n, float *out);

/* ---- diagnostics: memory the library has allocated and not yet freed, and blocks ever allocated (to check for leaks) ---- */
CANOPY_API int64_t canopy_alloc_live(void);
CANOPY_API int64_t canopy_alloc_total(void);

#endif
