/* SPDX-License-Identifier: GPL-3.0-or-later */
/* canopysynth - the node-type descriptor and the registry (docs/canopy_design.md section 12).

   A node type is described by one CanopyNodeType. An author fills one in (strings and arrays only need to live until the call) and
   registers it; the registry keeps its own deep copy, so the author's memory can go away. Python reads the same structure
   (canopysynth/_descriptor.py mirrors it), so the metadata has one source of truth. */
#ifndef CANOPY_NODE_H
#define CANOPY_NODE_H

#include "canopy.h"

/* The version of this descriptor layout. A descriptor made for another version is refused (CANOPY_ERR_ABI). */
#define CANOPY_ABI_VERSION 2
CANOPY_API int32_t canopy_abi_version(void);

/* "this node, in this instance, during this call": opaque, handed to every handler, valid only until the handler returns, and never to be
   used from another thread. The functions a handler may call through it are declared below, after CanopyHandlers. */
typedef struct CanopyCtx CanopyCtx;

/* ---- flags ---- */
#define CANOPY_FLAG_REALTIME_SAFE 1u        /* safe to run in the audio thread: no allocation, no locks, no Python */
#define CANOPY_FLAG_HAS_INTERNAL_RATE 2u    /* keeps discrete-time state: the registry adds the internal sampling rate setting */
#define CANOPY_FLAGS_KNOWN (CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_HAS_INTERNAL_RATE)

/* The reserved setting added to every node type that has CANOPY_FLAG_HAS_INTERNAL_RATE (whole Hz). */
#define CANOPY_INTERNAL_RATE_KEY "internal_sampling_rate"
#define CANOPY_INTERNAL_RATE_MIN 1
#define CANOPY_INTERNAL_RATE_MAX 384000
#define CANOPY_INTERNAL_RATE_DEFAULT 48000

/* ---- inlets and outlets ---- */
typedef struct {
    const char *key;             /* permanent: lowercase letters, digits, underscores */
    const char *label;
    float default_knob;          /* -1 .. 1; 0 when the author has no preference */
} CanopyInletDesc;

typedef struct {
    const char *key;
    const char *label;
} CanopyOutletDesc;

/* ---- settings (saved with the graph) ---- */
enum { CANOPY_SETTING_INT = 0, CANOPY_SETTING_FLOAT = 1, CANOPY_SETTING_STRING = 2, CANOPY_SETTING_PATH = 3, CANOPY_SETTING_CHOICE = 4 };

typedef struct {
    const char *key;
    int32_t kind;                /* CANOPY_SETTING_* */
    int64_t default_int;         /* INT; for CHOICE the index of the default choice */
    double default_float;        /* FLOAT */
    const char *default_string;  /* STRING and PATH (NULL means empty) */
    int32_t n_choices;           /* CHOICE: at least 1 */
    const char *const *choices;
} CanopySettingDesc;

/* ---- widgets, declared in data ---- */
enum { CANOPY_WIDGET_BUTTON = 0, CANOPY_WIDGET_TEXT = 1, CANOPY_WIDGET_CHOICE = 2, CANOPY_WIDGET_LABEL = 3 };

typedef struct {
    int32_t kind;                /* CANOPY_WIDGET_* */
    const char *label;
    const char *setting;         /* TEXT and CHOICE: the setting it edits */
    const char *action;          /* BUTTON: the action name passed to on_action */
    int32_t n_choices;           /* CHOICE: the choices shown (for a CHOICE setting: none, or the same as the setting's) */
    const char *const *choices;
} CanopyWidgetDesc;

/* ---- handlers ----
   query_at(ctx, outlet, t, out): writes the value of the outlet at time t to *out and returns CANOPY_OK, or returns a nonzero status of the
   node's own choosing; after a nonzero status the engine sets *out to 0.0f whatever the node wrote. `out` is never NULL. (Until ABI version 2 a
   point query returned the float itself and could not report an error; now it reports one exactly as a span query does.)
   query_span(ctx, outlet, t0, t1, n, out): fills exactly n floats of `out` with the outlet's values at the n sample times of the span
   (design section 5) and returns CANOPY_OK, or a nonzero status of the node's own choosing; after a nonzero status the engine zero-fills
   `out` whatever the node wrote. Before calling it the engine has checked that n is in 1 .. CANOPY_MAX_N, that `out` is not NULL and that
   t1 - t0 fits in an int64, so the node need not. `out` is the caller's: it may be uninitialized (write before reading), it never overlaps
   another buffer of the call, and the node keeps no pointer to it after returning.
   A node type implements query_at, query_span or both. With only query_at (a "pointwise" node) the engine derives the span by calling
   query_at once per sample time (the first nonzero status ends the span: `out` is zero-filled and the status returned); with only query_span a
   point query at t is answered by query_span(t, t, 1), its status passed on. Implement both when a span can be done faster than n point
   queries. */
typedef struct CanopyHandlers {
    void *(*create_shared)(CanopyCtx *ctx);                       /* the shared runtime resource, once per node ID; may be NULL */
    void (*destroy_shared)(CanopyCtx *ctx, void *shared);
    void *(*create_instance)(CanopyCtx *ctx);                     /* the instance state, once per instance; may be NULL */
    void (*destroy_instance)(CanopyCtx *ctx, void *state);
    int32_t (*query_at)(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out);
    int32_t (*query_span)(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out);
    void (*on_action)(CanopyCtx *ctx, const char *action);        /* a button was pressed (UI thread) */
} CanopyHandlers;

/* ---- what a handler may call (docs/canopy_design.md sections 5, 6 and 12) ----
   Which handlers get which context:
     query_at, query_span: everything below.
     create_shared, destroy_shared, create_instance, destroy_instance, on_action: only the settings getters, canopy_ctx_shared() and
     canopy_ctx_state(). There is no query in progress there, so canopy_inlet_at() and canopy_inlet_span() return CANOPY_ERR_ARGUMENT (and
     set or zero-fill `out`) and canopy_scratch() returns NULL.
   A handler that returns NULL from create_shared or create_instance simply has no shared resource or no instance state (its destroy handler
   is then not called).
   Which thread: query_at and query_span run in the thread that queries. create_shared, destroy_shared, create_instance and destroy_instance
   run in the thread that installs a graph, makes or frees an instance, or collects (never in a thread that queries), with the engine's lock
   held: a slow one delays installs and knob writes, never a query. on_action runs in the thread that calls canopy_engine_action (the UI
   thread) with the lock held shared (exclusive for the buttons of the built-in realtime preview node, which make and free its audio instance): it
   delays installs (and, behind a waiting install, knob writes), never a query. None of these handlers
   may call back into the engine (they have no way to; a node that kept an engine pointer of its own would deadlock). */

/* Point query of an inlet: writes to *out the connected outlet's answer for time `t`, or the inlet's knob position (-1..1, ignoring `t`) when
   nothing is connected, so a node never needs to know whether it is connected. Returns CANOPY_OK, or a nonzero status with *out set to 0.0f:
     CANOPY_ERR_ARGUMENT  `out` is NULL (then nothing is written), or this handler has no query in progress
     CANOPY_ERR_PORT      a bad inlet index
   or the status the queried node returned, passed through unchanged. A node that does not care may ignore the status: *out is silence then. */
CANOPY_API int32_t canopy_inlet_at(CanopyCtx *ctx, int32_t inlet, int64_t t, float *out);

/* Span query of an inlet: fills exactly `n` floats of `out` with the connected outlet's answer for the span [t0, t1) sampled as in design
   section 5 (sample i at t0 + floor(i * (t1 - t0) / n); t1 < t0 plays the span backwards; t1 == t0 puts every sample at t0), or with the knob
   position n times when nothing is connected. The caller owns `out` (room for n floats, may be uninitialized memory, must not overlap any
   other buffer of this call). Returns CANOPY_OK, or a nonzero status with all n floats of `out` zero-filled:
     CANOPY_ERR_N         n is not in 1 .. 65536 (then `out` is not touched: its size is unknown)
     CANOPY_ERR_ARGUMENT  `out` is NULL, or this handler has no query in progress
     CANOPY_ERR_OVERFLOW  t1 - t0 does not fit in a signed 64-bit integer
     CANOPY_ERR_PORT      a bad inlet index
   or the status the queried node returned, passed through unchanged. These checks apply whether or not the inlet is connected. */
CANOPY_API int32_t canopy_inlet_span(CanopyCtx *ctx, int32_t inlet, int64_t t0, int64_t t1, int64_t n, float *out);

/* `n` uninitialized floats from the instance's scratch arena (64-byte aligned), or NULL when n is below 1 or above 65536, when this call has
   already taken as many buffers as the node type declares in `scratch_buffers`, or when the arena is exhausted. Released automatically
   when the handler returns; the node never frees them. */
CANOPY_API float *canopy_scratch(CanopyCtx *ctx, int64_t n);

/* The instance state (what create_instance returned; in destroy_instance, the state being destroyed) and the shared runtime resource (what
   create_shared returned); NULL if there is none. The instance state of a node is carried over to the next graph when an edit keeps the node
   (same node ID, same node type); it is destroyed when the node goes, or its type changes. */
CANOPY_API void *canopy_ctx_state(CanopyCtx *ctx);
CANOPY_API void *canopy_ctx_shared(CanopyCtx *ctx);

/* For nodes that keep history (design section 7). A digest of the generation numbers of every source upstream of this node: the knobs of
   unconnected inlets, boundary values, the settings and the shared resources of this node and of every node that feeds it, directly or not.
   It changes when any of them is written (a knob move, a boundary write), when a setting is changed by installing another graph, when a
   shared resource is reported changed (canopy_ctx_shared_changed), and when the graph around the node is rewired; it does not change when
   something unrelated is edited. A node remembers the digest its checkpoints were made under, reads it at the start of every query, and
   discards its checkpoints when it differs. Read the digest BEFORE reading any input: an input newer than the digest then only makes a later
   query discard its checkpoints, never keep them wrongly. Equal digests mean equal generation numbers except with a probability of 2^-64. */
CANOPY_API uint64_t canopy_ctx_upstream_stamp(CanopyCtx *ctx);

/* The node's shared resource changed in a way that results downstream depend on (a file was opened): bumps its generation number, so that
   the digest of every node downstream changes. Call it from on_action, or any handler, after changing the resource. */
CANOPY_API void canopy_ctx_shared_changed(CanopyCtx *ctx);

/* For a node that replaces data its queries read (a file's samples, when "open" is pressed again): publish the new data with an atomic pointer
   swap (sequentially consistent, and read with a sequentially consistent load in the queries), then hand the OLD block to this call. `release`
   is called with the block once no query that began before the call can still be running: at once if none is, else by the thread that installs,
   collects or frees an instance (or when the engine is freed). Call it from on_action, create_shared or destroy_shared, never from a query;
   `release` must not call back into the engine. A query that begins after the swap reads the new data. */
CANOPY_API void canopy_ctx_retire(CanopyCtx *ctx, void *block, void (*release)(void *block));

/* What the node says about itself: shown on the node by the editor and read by the host with canopy_engine_node_message(). Text replaces the
   last message; an empty text clears it (a node that succeeds clears its message). Not for query handlers (it allocates). */
CANOPY_API void canopy_ctx_set_message(CanopyCtx *ctx, const char *text);

/* The node's settings, by index: the position in the descriptor's `settings` array (the internal sampling rate the registry adds comes last).
   canopy_ctx_int reads an INT setting, or the chosen index of a CHOICE setting; canopy_ctx_float a FLOAT setting; canopy_ctx_string a
   STRING or PATH setting (valid until the handler returns; never NULL). A bad index or the wrong kind returns 0, 0.0 or "". */
CANOPY_API int64_t canopy_ctx_int(CanopyCtx *ctx, int32_t setting);
CANOPY_API double canopy_ctx_float(CanopyCtx *ctx, int32_t setting);
CANOPY_API const char *canopy_ctx_string(CanopyCtx *ctx, int32_t setting);

/* ---- the descriptor ---- */
typedef struct CanopyNodeType {
    uint32_t abi_version;        /* CANOPY_ABI_VERSION */
    uint32_t struct_size;        /* sizeof(CanopyNodeType) as the author compiled it (a larger one, from a newer layout, is accepted) */
    const char *key;             /* permanent. Built-in keys are lowercase letters, digits and underscores; every other key must contain
                                    a dot, "vendor.name" */
    const char *name;            /* display name */
    int32_t type_version;        /* >= 1 */
    uint32_t flags;              /* CANOPY_FLAG_* */
    int32_t n_inlets;
    const CanopyInletDesc *inlets;
    int32_t n_outlets;
    const CanopyOutletDesc *outlets;
    int32_t n_settings;
    const CanopySettingDesc *settings;
    int32_t n_widgets;
    const CanopyWidgetDesc *widgets;
    int32_t scratch_buffers;     /* the most scratch buffers this node holds at once (>= 0) */
    CanopyHandlers handlers;
} CanopyNodeType;

/* ---- the registry ---- */
typedef struct CanopyRegistry CanopyRegistry;

CANOPY_API CanopyRegistry *canopy_registry_new(void);          /* holds the built-in node types (the boundary nodes so far) */
CANOPY_API void canopy_registry_free(CanopyRegistry *registry);

/* Registers the hidden, test-only node types (design section 11): they are never in a registry unless this is called, so that no editor or
   host listing shows them. Currently `test_filter`: a one-pole low-pass filter whose output depends on all of its past, with checkpoints
   (see src/canopy_test_nodes.c). Returns CANOPY_OK or the first error of registering. */
CANOPY_API int32_t canopy_registry_add_test_nodes(CanopyRegistry *registry);

/* Registers a copy of `type` (a plug-in or host node type: its key must contain a dot). Returns CANOPY_OK or the first problem found:
   CANOPY_ERR_ABI, CANOPY_ERR_KEY, CANOPY_ERR_DUPLICATE, CANOPY_ERR_DESCRIPTOR, CANOPY_ERR_MEMORY. Nothing is added on failure, and
   canopy_registry_last_error() then says what was wrong. */
CANOPY_API int32_t canopy_registry_register(CanopyRegistry *registry, const CanopyNodeType *type);

CANOPY_API int32_t canopy_registry_count(const CanopyRegistry *registry);
CANOPY_API const CanopyNodeType *canopy_registry_at(const CanopyRegistry *registry, int32_t index);     /* registration order; NULL if out of range */
CANOPY_API const CanopyNodeType *canopy_registry_find(const CanopyRegistry *registry, const char *key);  /* NULL if unknown */
CANOPY_API const char *canopy_registry_last_error(const CanopyRegistry *registry);

#endif
