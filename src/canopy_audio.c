/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The audio device layer (canopy_audio.h): miniaudio's device I/O, compiled here and nowhere else.
     What is compiled   Only device I/O and miniaudio's data conversion; decoding, encoding, the resource manager, the node graph and the engine
                        of miniaudio are switched off. Only two backends: WASAPI (the system's, on Windows) and miniaudio's null backend (a device
                        that takes audio in real time and plays it nowhere: for tests and hosts without sound hardware).
     Memory             Everything miniaudio allocates goes through canopy_alloc_unhooked: counted, so that tests see a leak, but not failed on
                        purpose by the tests' failure hook, because miniaudio itself leaks when one of its allocations fails inside ma_device_init
                        (found by trying; see canopy_internal.h). Its callbacks have no old size for a resize, so each block carries a 16 byte
                        header with its size, which also keeps the 16 byte alignment. A call that fails after an allocation really failed says
                        "out of memory", not "no device".
     Threads            miniaudio's contexts and devices must not be created or destroyed by two threads at once (it says so for each call, because
                        some backends keep global state), so one lock for the whole process covers every such call here. The data callback and the
                        notification run in miniaudio's threads and take no lock. */
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "canopy_core.h"
#include "canopy_audio.h"

#pragma warning(push, 0)
#pragma warning(disable: 4701 4703)
#define MA_NO_DECODING
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#define MA_NO_ENGINE
#define MA_ENABLE_ONLY_SPECIFIC_BACKENDS
#define MA_ENABLE_WASAPI
#define MA_ENABLE_NULL
#define MINIAUDIO_IMPLEMENTATION
#include "../third_party/miniaudio.h"
#pragma warning(pop)

#define PERIOD_MS 20          /* a period of the device: 20 ms, three of them (about 60 ms of latency) */
#define PERIODS 3

static SRWLOCK audio_lock = SRWLOCK_INIT;      /* every miniaudio call that makes or destroys a context or a device */

/* ---- allocation for miniaudio ---- */

typedef struct {
    atomic_int failed;                         /* an allocation failed: whatever miniaudio reports next, memory is the reason */
} AllocTracker;

void *canopy_audio_alloc(size_t size, void *user)
{
    unsigned char *block = size > SIZE_MAX - 16 ? NULL : (unsigned char *)canopy_alloc_unhooked(size + 16);
    if (!block) {
        if (user) atomic_store((atomic_int *)user, 1);
        return NULL;
    }
    memcpy(block, &size, sizeof size);
    return block + 16;
}

void *canopy_audio_grow(void *block, size_t size, void *user)
{
    unsigned char *old, *grown;
    size_t old_size;
    if (!block) return canopy_audio_alloc(size, user);
    old = (unsigned char *)block - 16;
    memcpy(&old_size, old, sizeof old_size);
    grown = size > SIZE_MAX - 16 ? NULL : (unsigned char *)canopy_realloc_unhooked(old, old_size + 16, size + 16);
    if (!grown) {
        if (user) atomic_store((atomic_int *)user, 1);
        return NULL;
    }
    memcpy(grown, &size, sizeof size);
    return grown + 16;
}

void canopy_audio_release(void *block, void *user)
{
    (void)user;
    if (block) canopy_free((unsigned char *)block - 16);
}

/* ---- failures made on purpose (for tests) ---- */

static int forced_stage;             /* 0: none; 5: pretend that the audio system does not start; 1 to 4: that miniaudio failed after the context started, the devices were listed, the device was made, the device was started */

void canopy_audio_force_failure(int stage)
{
    forced_stage = stage;
}

/* ---- contexts ---- */

static int backend_ok(int32_t backend)
{
    return backend == CANOPY_AUDIO_SYSTEM || backend == CANOPY_AUDIO_NULL;
}

/* Starts miniaudio's context for the audio system `backend` (the audio_lock held). CANOPY_OK; CANOPY_ERR_MEMORY; or CANOPY_AUDIO_ERR_DEVICE
   with miniaudio's result in *result (the system has no audio). */
static int32_t context_start(int32_t backend, ma_context *context, AllocTracker *tracker, ma_result *result)
{
    ma_backend list[1];
    ma_context_config config = ma_context_config_init();
    if (forced_stage == 5) {                                                   /* the audio system does not start */
        *result = MA_ERROR;
        return CANOPY_AUDIO_ERR_DEVICE;
    }
    list[0] = backend == CANOPY_AUDIO_NULL ? ma_backend_null : ma_backend_wasapi;
    config.allocationCallbacks.pUserData = &tracker->failed;
    config.allocationCallbacks.onMalloc = canopy_audio_alloc;
    config.allocationCallbacks.onRealloc = canopy_audio_grow;
    config.allocationCallbacks.onFree = canopy_audio_release;
    *result = ma_context_init(list, 1, &config, context);
    if (*result == MA_SUCCESS) return CANOPY_OK;
    return atomic_load(&tracker->failed) ? CANOPY_ERR_MEMORY : CANOPY_AUDIO_ERR_DEVICE;
}

int32_t canopy_audio_join_names(const char *first, size_t stride, uint32_t count, char **text)
{
    size_t total = 0, used = 0;
    uint32_t i;
    char *built;
    for (i = 0; i < count; i++) total += strlen(first + (size_t)i * stride) + 1;
    built = (char *)canopy_alloc(total + 1);
    if (!built) return CANOPY_ERR_MEMORY;
    for (i = 0; i < count; i++) {
        const char *name = first + (size_t)i * stride;
        size_t k;
        if (i > 0) built[used++] = '\n';
        for (k = 0; name[k]; k++) built[used++] = (name[k] == '\n' || name[k] == '\r') ? ' ' : name[k];
    }
    built[used] = '\0';
    *text = built;
    return CANOPY_OK;
}

int32_t canopy_audio_list(int32_t backend, char **text)
{
    ma_context context;
    AllocTracker tracker;
    ma_device_info *playback = NULL;
    ma_uint32 count = 0;
    ma_result result = MA_SUCCESS;
    int32_t status;
    char *built = NULL;
    if (!text || !backend_ok(backend)) return CANOPY_ERR_ARGUMENT;
    memset(&tracker, 0, sizeof tracker);
    AcquireSRWLockExclusive(&audio_lock);
    status = context_start(backend, &context, &tracker, &result);
    if (status == CANOPY_OK) {
        result = ma_context_get_devices(&context, &playback, &count, NULL, NULL);
        if (forced_stage == 2) result = MA_ERROR;
        if (result != MA_SUCCESS) {
            count = 0;                                                         /* devices that cannot be listed are a list of none... */
            if (atomic_load(&tracker.failed)) status = CANOPY_ERR_MEMORY;      /* ...unless memory is the reason */
        }
        if (status == CANOPY_OK) status = canopy_audio_join_names(count > 0 ? playback[0].name : "", sizeof playback[0], count, &built);
        ma_context_uninit(&context);
    } else if (status == CANOPY_AUDIO_ERR_DEVICE) {                            /* no audio system at all: a list of none */
        built = (char *)canopy_alloc(1);
        status = built ? CANOPY_OK : CANOPY_ERR_MEMORY;
    }
    ReleaseSRWLockExclusive(&audio_lock);
    if (status != CANOPY_OK) {
        canopy_free(built);
        return status;
    }
    *text = built;
    return CANOPY_OK;
}

/* ---- devices ---- */

struct CanopyAudioDevice {
    ma_context context;
    ma_device device;
    CanopyAudioCallbacks callbacks;
    AllocTracker tracker;
    atomic_int closing;                        /* close has begun: the stop that follows is ours, not the device's own */
    int context_ready, device_ready;
};

static void data_proc(ma_device *device, void *output, const void *input, ma_uint32 frames)
{
    CanopyAudioDevice *self = (CanopyAudioDevice *)device->pUserData;
    (void)input;
    self->callbacks.fill(self->callbacks.user, (float *)output, (uint32_t)frames);
}

static void notification_proc(const ma_device_notification *notification)
{
    CanopyAudioDevice *self = (CanopyAudioDevice *)notification->pDevice->pUserData;
    if (notification->type == ma_device_notification_type_stopped && !atomic_load(&self->closing) && self->callbacks.stopped)
        self->callbacks.stopped(self->callbacks.user);
}

static void say(char *why, size_t why_size, const char *what, ma_result result)
{
    if (why && why_size > 0) snprintf(why, why_size, "%s: %s", what, ma_result_description(result));
}

int32_t canopy_audio_open(int32_t backend, const char *name, const CanopyAudioCallbacks *callbacks, CanopyAudioDevice **device,
                          int *used_default, char *why, size_t why_size)
{
    CanopyAudioDevice *self;
    ma_device_info *playback = NULL;
    ma_uint32 count = 0, i;
    const ma_device_id *id = NULL;
    ma_device_config config;
    ma_result result = MA_SUCCESS;
    int32_t status;
    int fell_back = 0;
    if (used_default) *used_default = 0;
    if (why && why_size > 0) why[0] = '\0';
    if (!callbacks || !callbacks->fill || !device || !backend_ok(backend)) return CANOPY_ERR_ARGUMENT;
    *device = NULL;
    self = (CanopyAudioDevice *)canopy_alloc(sizeof *self);
    if (!self) return CANOPY_ERR_MEMORY;
    self->callbacks = *callbacks;
    AcquireSRWLockExclusive(&audio_lock);
    status = context_start(backend, &self->context, &self->tracker, &result);
    if (status != CANOPY_OK) {
        say(why, why_size, "no audio system", result);
        goto fail;
    }
    self->context_ready = 1;
    if (forced_stage == 1) {
        status = CANOPY_AUDIO_ERR_DEVICE;
        say(why, why_size, "forced failure after the context started", MA_ERROR);
        goto fail;
    }
    result = ma_context_get_devices(&self->context, &playback, &count, NULL, NULL);
    if (forced_stage == 2) result = MA_ERROR;
    if (result != MA_SUCCESS) {
        status = atomic_load(&self->tracker.failed) ? CANOPY_ERR_MEMORY : CANOPY_AUDIO_ERR_DEVICE;
        say(why, why_size, "the audio devices cannot be listed", result);
        goto fail;
    }
    if (name && name[0] && strcmp(name, CANOPY_AUDIO_DEFAULT_NAME) != 0) {
        for (i = 0; i < count; i++)
            if (strcmp(playback[i].name, name) == 0) {
                id = &playback[i].id;
                break;
            }
        if (!id) fell_back = 1;
    }
    config = ma_device_config_init(ma_device_type_playback);
    config.playback.pDeviceID = id;                                            /* NULL: the system default */
    config.playback.format = ma_format_f32;
    config.playback.channels = 2;
    config.sampleRate = CANOPY_AUDIO_RATE;
    config.periodSizeInMilliseconds = PERIOD_MS;
    config.periods = PERIODS;
    config.dataCallback = data_proc;
    config.notificationCallback = notification_proc;
    config.pUserData = self;
    result = ma_device_init(&self->context, &config, &self->device);
    if (result != MA_SUCCESS) {
        status = atomic_load(&self->tracker.failed) ? CANOPY_ERR_MEMORY : CANOPY_AUDIO_ERR_DEVICE;
        say(why, why_size, "the audio device cannot be opened", result);
        goto fail;
    }
    self->device_ready = 1;
    if (forced_stage == 3) {
        status = CANOPY_AUDIO_ERR_DEVICE;
        say(why, why_size, "forced failure after the device was made", MA_ERROR);
        goto fail;
    }
    result = ma_device_start(&self->device);
    if (forced_stage == 4) result = MA_ERROR;
    if (result != MA_SUCCESS) {
        status = atomic_load(&self->tracker.failed) ? CANOPY_ERR_MEMORY : CANOPY_AUDIO_ERR_DEVICE;
        say(why, why_size, "the audio device cannot be started", result);
        goto fail;
    }
    ReleaseSRWLockExclusive(&audio_lock);
    *device = self;
    if (used_default) *used_default = fell_back;
    return CANOPY_OK;
fail:
    if (self->device_ready) ma_device_uninit(&self->device);
    if (self->context_ready) ma_context_uninit(&self->context);
    ReleaseSRWLockExclusive(&audio_lock);
    canopy_free(self);
    return status;
}

void canopy_audio_close(CanopyAudioDevice *self)
{
    if (!self) return;
    atomic_store(&self->closing, 1);
    AcquireSRWLockExclusive(&audio_lock);
    ma_device_uninit(&self->device);                                           /* stops it, and returns when its thread has ended */
    ma_context_uninit(&self->context);
    ReleaseSRWLockExclusive(&audio_lock);
    canopy_free(self);
}

void canopy_audio_stop_for_test(CanopyAudioDevice *self)
{
    if (self) (void)ma_device_stop(&self->device);
}

void canopy_audio_describe(const CanopyAudioDevice *self, uint32_t *rate, uint32_t *channels, int *is_float32)
{
    if (!self) return;
    if (rate) *rate = (uint32_t)self->device.sampleRate;
    if (channels) *channels = (uint32_t)self->device.playback.channels;
    if (is_float32) *is_float32 = self->device.playback.format == ma_format_f32;
}
