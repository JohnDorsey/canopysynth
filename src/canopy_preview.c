/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The realtime preview node (design sections 8, 9 and 11): plays what is connected to its inlets left, right and center to an audio device.
     State            The only playback state of CANOPY lives in this node's shared resource: a position (a frame count at 48000 Hz, so the
                      time is exact for every millisecond), whether it plays, and the device. The node has no outlets, so no other node can see it.
     The audio thread The device (canopy_audio.c: miniaudio) calls fill() in a thread of its own. fill() asks the graph through an instance
                      the engine made for this node (a service instance, canopy_service_instance_new): for each chunk of at most 65536 frames it
                      makes three span queries over the times of the frames about to be played, left, right and center, and sends left + center to
                      the left channel and right + center to the right channel, clipped to full scale (NaN is silence). Nothing in it allocates,
                      locks or waits: it reads a few atomics, queries, and adds. The position moves on by the frames played, by compare-and-
                      exchange, so that a seek made meanwhile wins.
     The device       Opened by the first Play (not when the node appears), 48000 Hz, stereo, float32; kept running and silent while paused, so
                      that the audio thread's instance goes on adopting edited graphs and Play answers within a period; closed when the node
                      leaves every graph in use, when the engine is freed, or when "device" / Play find that the `device` setting names another
                      one. The actions run with the engine's lock held exclusively (CANOPY_FLAG_SERVICE), which is what lets them make and free
                      the instance. A device that cannot be opened leaves the node paused with the reason as its message; a name no device has
                      falls back to the system default (the design) and the message says so.
     Buttons          "play", "pause", and "device" (switch to the device the setting now names, keeping the state).
     Exported         canopy_preview_state, canopy_preview_set_time, canopy_preview_warning, canopy_engine_audio_devices (canopy_engine.h). */
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "canopy_core.h"
#include "canopy_audio.h"

enum { SETTING_DEVICE = 0 };
enum { INLET_LEFT = 0, INLET_RIGHT = 1, INLET_CENTER = 2 };
#define BUFFER_FLOATS CANOPY_MAX_N                  /* each of the three buffers holds the largest chunk */
#define WARNING_PREFIX "not realtime safe, so the sound may break up: "

typedef struct {
    CanopyNodeRecord *record;                       /* the node's record: where the device's own notifications leave a message (it outlives this) */
    CanopyEngine *engine;
    int64_t node_id;
    CanopyAudioDevice *device;                      /* NULL: no device is open */
    CanopyInstance *instance;                       /* the service instance the audio thread queries through; NULL while there is no device */
    float *block;                                   /* three buffers of BUFFER_FLOATS: left, right, center */
    char *open_name;                                /* the text of the `device` setting the open device was made for */
    atomic_int playing;
    atomic_llong position;                          /* in frames of CANOPY_AUDIO_RATE: the frame about to be handed to the device */
    atomic_int lost;                                /* the device stopped by itself */
    atomic_llong callbacks;                         /* diagnostics: audio callbacks so far, devices opened so far */
    atomic_llong opens;
} Preview;

/* ---- the audio thread ---- */

static float clip(float x)
{
    if (x != x) return 0.0f;                        /* NaN: silence, not a click at full scale */
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return x;
}

/* One chunk of at most BUFFER_FLOATS frames. Returns 0, having written nothing, when it does not play: paused, no instance, a time that cannot
   be written in nanoseconds, or a node that is not in the graph the instance runs. */
static int play_chunk(Preview *p, float *stereo, uint32_t frames)
{
    float *left = p->block, *right = p->block + BUFFER_FLOATS, *center = p->block + 2 * BUFFER_FLOATS;
    int64_t position, t0, t1, i;
    int32_t status_left, status_right, status_center;
    long long expected;
    if (!atomic_load(&p->playing) || !p->instance) return 0;
    position = (int64_t)atomic_load(&p->position);
    if (canopy_frame_to_ns(position, CANOPY_AUDIO_RATE, &t0) != CANOPY_OK ||
        canopy_frame_to_ns(position + (int64_t)frames, CANOPY_AUDIO_RATE, &t1) != CANOPY_OK)
        return 0;
    status_left = canopy_instance_inlet_span(p->instance, p->node_id, INLET_LEFT, t0, t1, frames, left);        /* (a failure zero-fills the buffer) */
    status_right = canopy_instance_inlet_span(p->instance, p->node_id, INLET_RIGHT, t0, t1, frames, right);
    status_center = canopy_instance_inlet_span(p->instance, p->node_id, INLET_CENTER, t0, t1, frames, center);
    if (status_left == CANOPY_ERR_NODE && status_right == CANOPY_ERR_NODE && status_center == CANOPY_ERR_NODE) return 0;
    for (i = 0; i < frames; i++) {
        stereo[2 * i] = clip(left[i] + center[i]);
        stereo[2 * i + 1] = clip(right[i] + center[i]);
    }
    expected = (long long)position;
    atomic_compare_exchange_strong(&p->position, &expected, (long long)(position + (int64_t)frames));      /* a seek made meanwhile wins */
    return 1;
}

static void fill(Preview *p, float *stereo, uint32_t frames)
{
    uint32_t done = 0;
    atomic_fetch_add(&p->callbacks, 1);
    while (done < frames) {
        uint32_t n = frames - done < BUFFER_FLOATS ? frames - done : BUFFER_FLOATS;
        float *where = stereo + 2 * (size_t)done;
        if (!play_chunk(p, where, n)) memset(where, 0, (size_t)n * 2 * sizeof(float));
        done += n;
    }
}

static void device_fill(void *user, float *stereo, uint32_t frames)
{
    fill((Preview *)user, stereo, frames);
}

static void device_stopped(void *user)              /* in a thread of miniaudio's: the device stopped by itself */
{
    Preview *p = (Preview *)user;
    atomic_store(&p->lost, 1);
    atomic_store(&p->playing, 0);
    canopy_record_set_message(p->record, "the audio device stopped; press Play to start it again");
}

/* ---- the device (the engine's lock held exclusively) ---- */

static void device_close(Preview *p)
{
    if (p->device) {
        canopy_audio_close(p->device);              /* returns when the audio thread has gone: the instance and the buffers are ours again */
        p->device = NULL;
    }
    if (p->instance) {
        canopy_service_instance_free(p->engine, p->instance);
        p->instance = NULL;
    }
    canopy_free(p->block);
    p->block = NULL;
    canopy_free(p->open_name);
    p->open_name = NULL;
    atomic_store(&p->playing, 0);
    atomic_store(&p->lost, 0);
}

/* The buffers and the service instance. 0 if memory ran out, or if no graph is installed. */
static int prepare(Preview *p)
{
    if (!p->block) {
        p->block = (float *)canopy_alloc(3 * (size_t)BUFFER_FLOATS * sizeof(float));
        if (!p->block) return 0;
    }
    if (!p->instance) {
        p->instance = canopy_service_instance_new(p->engine);
        if (!p->instance) return 0;
    }
    return 1;
}

/* Opens the device called `name` and starts it. Returns 1, or 0 with nothing left open and the reason as the node's message. */
static int device_open(CanopyCtx *ctx, Preview *p, const char *name)
{
    CanopyAudioCallbacks callbacks;
    char why[250], text[CANOPY_MESSAGE_BYTES];
    int used_default = 0;
    int32_t status;
    size_t length = strlen(name);
    p->open_name = (char *)canopy_alloc(length + 1);
    if (!p->open_name || !prepare(p)) {
        device_close(p);
        canopy_ctx_set_message(ctx, "out of memory");
        return 0;
    }
    memcpy(p->open_name, name, length + 1);
    callbacks.fill = device_fill;
    callbacks.stopped = device_stopped;
    callbacks.user = p;
    why[0] = '\0';
    status = canopy_audio_open((int32_t)atomic_load(&p->engine->audio_backend), name, &callbacks, &p->device, &used_default, why, sizeof why);
    if (status != CANOPY_OK) {
        device_close(p);
        if (status == CANOPY_ERR_MEMORY) {
            canopy_ctx_set_message(ctx, "out of memory");
        } else {
            snprintf(text, sizeof text, "cannot play: %s", why);
            canopy_ctx_set_message(ctx, text);
        }
        return 0;
    }
    atomic_fetch_add(&p->opens, 1);
    if (used_default) {
        snprintf(text, sizeof text, "audio device not found: %s; using the system default", name);
        canopy_ctx_set_message(ctx, text);
    } else {
        canopy_ctx_set_message(ctx, "");
    }
    return 1;
}

/* ---- the node ---- */

static void *preview_create_shared(CanopyCtx *ctx)
{
    Preview *p = (Preview *)canopy_alloc(sizeof *p);
    if (!p) return NULL;
    p->record = ctx->node->record;
    p->engine = p->record->engine;
    p->node_id = ctx->node->id;
    return p;
}

static void preview_destroy_shared(CanopyCtx *ctx, void *shared)
{
    Preview *p = (Preview *)shared;
    (void)ctx;
    device_close(p);
    canopy_free(p);
}

static void preview_action(CanopyCtx *ctx, const char *action)
{
    Preview *p = (Preview *)canopy_ctx_shared(ctx);
    const char *name;
    if (!p) {
        canopy_ctx_set_message(ctx, "out of memory");
        return;
    }
    name = canopy_ctx_string(ctx, SETTING_DEVICE);
    if (strcmp(action, "play") == 0) {
        if (p->device && (atomic_load(&p->lost) || strcmp(p->open_name, name) != 0)) device_close(p);       /* gone, or another device now */
        if (!p->device && !device_open(ctx, p, name)) return;
        atomic_store(&p->playing, 1);
    } else if (strcmp(action, "pause") == 0) {
        atomic_store(&p->playing, 0);
    } else if (strcmp(action, "device") == 0) {
        if (p->device && strcmp(p->open_name, name) != 0) {
            int playing = atomic_load(&p->playing);
            device_close(p);
            if (device_open(ctx, p, name) && playing) atomic_store(&p->playing, 1);
        }
    }
}

static const CanopyInletDesc PREVIEW_INLETS[] = {{"left", "Left", 0.0f}, {"right", "Right", 0.0f}, {"center", "Center", 0.0f}};
static const CanopySettingDesc PREVIEW_SETTINGS[] = {{"device", CANOPY_SETTING_STRING, 0, 0.0, CANOPY_AUDIO_DEFAULT_NAME, 0, NULL}};
static const char *const DEVICE_CHOICES[] = {CANOPY_AUDIO_DEFAULT_NAME};      /* the one fixed entry: the editor adds the devices of the machine */
static const CanopyWidgetDesc PREVIEW_WIDGETS[] = {{CANOPY_WIDGET_BUTTON, "Play", NULL, "play", 0, NULL},
                                                   {CANOPY_WIDGET_BUTTON, "Pause", NULL, "pause", 0, NULL},
                                                   {CANOPY_WIDGET_CHOICE, "Device", "device", NULL, 1, DEVICE_CHOICES}};

int32_t canopy_preview_register_type(CanopyRegistry *registry)
{
    CanopyNodeType type;
    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = (uint32_t)sizeof type;
    type.key = "realtime_preview";
    type.name = "Realtime preview";
    type.type_version = 1;
    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_SERVICE;
    type.n_inlets = 3; type.inlets = PREVIEW_INLETS;
    type.n_settings = 1; type.settings = PREVIEW_SETTINGS;
    type.n_widgets = 3; type.widgets = PREVIEW_WIDGETS;
    type.handlers.create_shared = preview_create_shared;
    type.handlers.destroy_shared = preview_destroy_shared;
    type.handlers.on_action = preview_action;
    return canopy_registry_register_builtin(registry, &type);
}

/* ---- the exported calls ---- */

static int64_t position_ns(int64_t frame)
{
    int64_t ns;
    if (canopy_frame_to_ns(frame, CANOPY_AUDIO_RATE, &ns) == CANOPY_OK) return ns;
    return frame < 0 ? INT64_MIN : INT64_MAX;       /* (the nearest frame to the ends of time can be a hair beyond them) */
}

/* The preview node `node_id` of the installed graph (the engine's lock held): CANOPY_OK with its node and its resource (NULL if making it ran out
   of memory), CANOPY_ERR_NODE, or CANOPY_ERR_ARGUMENT for a node of another type. */
static int32_t find_installed(CanopyEngine *engine, int64_t node_id, const CanopyCompiled **graph, int32_t *index, Preview **preview)
{
    const CanopyCNode *node;
    *graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    node = *graph ? canopy_compiled_find(*graph, node_id, index) : NULL;
    if (!node) return CANOPY_ERR_NODE;
    if (node->type->handlers.create_shared != preview_create_shared) return CANOPY_ERR_ARGUMENT;
    *preview = (Preview *)node->shared;
    return CANOPY_OK;
}

int32_t canopy_preview_state(CanopyEngine *engine, int64_t node_id, int32_t *playing, int64_t *time_ns)
{
    const CanopyCompiled *graph;
    Preview *p = NULL;
    int32_t index = 0, status;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_installed(engine, node_id, &graph, &index, &p);
    if (status == CANOPY_OK) {
        if (playing) *playing = p ? atomic_load(&p->playing) : 0;
        if (time_ns) *time_ns = p ? position_ns((int64_t)atomic_load(&p->position)) : 0;
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_preview_set_time(CanopyEngine *engine, int64_t node_id, int64_t time_ns)
{
    const CanopyCompiled *graph;
    Preview *p = NULL;
    int32_t index = 0, status;
    int64_t frame = 0;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_installed(engine, node_id, &graph, &index, &p);
    if (status == CANOPY_OK) {
        if (!p) status = CANOPY_ERR_MEMORY;
        else if (canopy_ns_to_frame(time_ns, CANOPY_AUDIO_RATE, &frame) != CANOPY_OK) status = CANOPY_ERR_ARGUMENT;
        else atomic_store(&p->position, (long long)frame);
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}

/* Copies `text` as the calls with a buffer do: cut to capacity - 1 bytes and NUL-terminated, the full length in *length. */
static void copy_out(const char *text, size_t size, char *buffer, int32_t capacity, int32_t *length)
{
    if (capacity > 0) {
        size_t copied = size < (size_t)capacity - 1 ? size : (size_t)capacity - 1;
        if (copied) memcpy(buffer, text, copied);
        buffer[copied] = '\0';
    }
    if (length) *length = (int32_t)size;
}

int32_t canopy_preview_warning(CanopyEngine *engine, int64_t node_id, char *buffer, int32_t capacity, int32_t *length)
{
    const CanopyCompiled *graph;
    Preview *p = NULL;
    int32_t index = 0, status, n, i, j, sp = 0;
    unsigned char *seen;
    int32_t *stack;
    if (!engine || capacity < 0 || (capacity > 0 && !buffer)) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_installed(engine, node_id, &graph, &index, &p);
    if (status == CANOPY_OK) {
        n = graph->n_nodes;
        seen = (unsigned char *)canopy_alloc((size_t)n);
        stack = (int32_t *)canopy_alloc((size_t)n * sizeof *stack);
        if (!seen || !stack) {
            status = CANOPY_ERR_MEMORY;
        } else {
            size_t size = 0, used = 0;
            char *text;
            int pass;
            seen[index] = 1;                                                      /* what feeds the preview, directly or not (loops included) */
            stack[sp++] = index;
            while (sp > 0) {
                const CanopyCNode *node = &graph->nodes[stack[--sp]];
                for (j = 0; j < node->type->n_inlets; j++) {
                    int32_t source = node->links[j].node;
                    if (source >= 0 && !seen[source]) {
                        seen[source] = 1;
                        stack[sp++] = source;
                    }
                }
            }
            text = NULL;
            for (pass = 0; pass < 2; pass++) {                                    /* the first pass measures, the second writes */
                int count = 0;
                used = 0;
                for (i = 0; i < n; i++) {
                    const CanopyCNode *node = &graph->nodes[i];
                    if (!seen[i] || i == index || (node->type->flags & CANOPY_FLAG_REALTIME_SAFE)) continue;
                    if (count == 0) {
                        if (text) memcpy(text, WARNING_PREFIX, sizeof WARNING_PREFIX - 1);
                        used += sizeof WARNING_PREFIX - 1;
                    } else {
                        if (text) memcpy(text + used, ", ", 2);
                        used += 2;
                    }
                    used += (size_t)snprintf(text ? text + used : NULL, text ? size + 1 - used : 0, "%s (node %lld)", node->type->key, (long long)node->id);
                    count++;
                }
                if (pass == 0) {
                    size = used;
                    text = (char *)canopy_alloc(size + 1);
                    if (!text) {
                        status = CANOPY_ERR_MEMORY;
                        break;
                    }
                }
            }
            if (status == CANOPY_OK) {
                text[size] = '\0';
                copy_out(text, size, buffer, capacity, length);
            }
            canopy_free(text);
        }
        canopy_free(seen);
        canopy_free(stack);
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_engine_audio_devices(CanopyEngine *engine, char *buffer, int32_t capacity, int32_t *length)
{
    char *text = NULL;
    int32_t status;
    if (!engine || capacity < 0 || (capacity > 0 && !buffer)) return CANOPY_ERR_ARGUMENT;
    status = canopy_audio_list((int32_t)atomic_load(&engine->audio_backend), &text);
    if (status != CANOPY_OK) return status;
    copy_out(text, strlen(text), buffer, capacity, length);
    canopy_free(text);
    return CANOPY_OK;
}

/* ---- for tests and diagnostics (canopy_internal.h) ---- */

/* The resource of the preview node with this ID among the engine's records, found there rather than in the installed graph, as the audio thread
   has it: it works for a node that has been deleted from the installed graph but lives on in a graph still in use (the engine's lock held). */
static int32_t find_record(CanopyEngine *engine, int64_t node_id, Preview **preview)
{
    int32_t i;
    for (i = 0; i < engine->n_records; i++) {
        const CanopyNodeRecord *record = engine->records[i];
        if (record->id == node_id && record->type->handlers.create_shared == preview_create_shared) {
            *preview = (Preview *)record->shared;
            return *preview ? CANOPY_OK : CANOPY_ERR_MEMORY;
        }
    }
    return CANOPY_ERR_NODE;
}

int32_t canopy_preview_prepare(CanopyEngine *engine, int64_t node_id, int32_t playing)
{
    Preview *p = NULL;
    int32_t status;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_exclusive(&engine->lock);
    status = find_record(engine, node_id, &p);
    if (status == CANOPY_OK) {
        if (!prepare(p)) status = CANOPY_ERR_MEMORY;
        else atomic_store(&p->playing, playing ? 1 : 0);
    }
    canopy_unlock_exclusive(&engine->lock);
    return status;
}

int32_t canopy_preview_fill(CanopyEngine *engine, int64_t node_id, float *stereo, uint32_t frames)
{
    Preview *p = NULL;
    int32_t status;
    if (!engine || (!stereo && frames > 0)) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_record(engine, node_id, &p);
    if (status == CANOPY_OK) fill(p, stereo, frames);
    canopy_unlock_shared(&engine->lock);
    return status;
}

int32_t canopy_preview_counts(CanopyEngine *engine, int64_t node_id, int64_t *callbacks, int64_t *opens)
{
    Preview *p = NULL;
    int32_t status;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_record(engine, node_id, &p);
    if (status == CANOPY_OK) {
        if (callbacks) *callbacks = (int64_t)atomic_load(&p->callbacks);
        if (opens) *opens = (int64_t)atomic_load(&p->opens);
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}

const atomic_llong *canopy_preview_callback_counter(CanopyEngine *engine, int64_t node_id)
{
    Preview *p = NULL;
    const atomic_llong *counter = NULL;
    if (!engine) return NULL;
    canopy_lock_shared(&engine->lock);
    if (find_record(engine, node_id, &p) == CANOPY_OK) counter = &p->callbacks;
    canopy_unlock_shared(&engine->lock);
    return counter;
}

int32_t canopy_preview_stop_device(CanopyEngine *engine, int64_t node_id)
{
    Preview *p = NULL;
    int32_t status;
    if (!engine) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    status = find_record(engine, node_id, &p);
    if (status == CANOPY_OK) canopy_audio_stop_for_test(p->device);
    canopy_unlock_shared(&engine->lock);
    return status;
}
