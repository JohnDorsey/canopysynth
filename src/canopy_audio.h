/* The audio device layer (not exported): the only code that talks to miniaudio. It opens a stereo float32 playback device at 48000 Hz that
   calls `fill` in its own thread whenever it needs audio, and lists the devices by name. The realtime preview node (canopy_preview.c) is its
   only user. Everything that miniaudio allocates goes through canopy_alloc. miniaudio says that creating and destroying contexts and devices
   is not safe to do from two threads at once, so every such call here is made under one lock for the whole process. */
#ifndef CANOPY_AUDIO_H
#define CANOPY_AUDIO_H

#include <stddef.h>
#include "canopy_internal.h"

typedef struct CanopyAudioDevice CanopyAudioDevice;

typedef struct {
    /* In the device's thread, whenever it needs `frames` frames: write that many interleaved stereo float frames (2 * frames floats).
       Must not block, allocate or call back into canopy_audio_*. */
    void (*fill)(void *user, float *stereo, uint32_t frames);
    /* In a thread of miniaudio's, when the device has stopped without canopy_audio_close (it was unplugged, say). Never called by close. */
    void (*stopped)(void *user);
    void *user;
} CanopyAudioCallbacks;

/* An internal status (never given to a host): the audio system or the device could not be used; the reason is in `why`. */
#define CANOPY_AUDIO_ERR_DEVICE 100

/* The playback devices of the audio system `backend` (CANOPY_AUDIO_SYSTEM or CANOPY_AUDIO_NULL), as one block of text from canopy_alloc (the
   caller frees it), one name per line separated by '\n', no final newline, "" for none. An audio system that cannot be started is a list of
   none. Returns CANOPY_OK, CANOPY_ERR_MEMORY or CANOPY_ERR_ARGUMENT (an unknown backend). */
int32_t canopy_audio_list(int32_t backend, char **text);

/* Opens the playback device called `name` and starts it: stereo, float32, CANOPY_AUDIO_RATE Hz, periods of 20 ms (three of them). The
   system default device is used when `name` is empty, is CANOPY_AUDIO_DEFAULT_NAME, or names no device; in the last case *used_default is set
   to 1 (it is 0 otherwise; the pointer may be NULL). On success returns CANOPY_OK and the device; the first call of `fill` can come before this
   returns. Otherwise returns CANOPY_ERR_MEMORY or CANOPY_AUDIO_ERR_DEVICE, with a sentence in `why` for the latter, and nothing is left open. */
int32_t canopy_audio_open(int32_t backend, const char *name, const CanopyAudioCallbacks *callbacks, CanopyAudioDevice **device,
                          int *used_default, char *why, size_t why_size);

/* Stops and closes the device and returns when `fill` is not running and will not run again. Does not call `stopped`. NULL is fine. */
void canopy_audio_close(CanopyAudioDevice *device);

/* For tests: stops the device from outside, so that `stopped` is called as if it had been unplugged. */
void canopy_audio_stop_for_test(CanopyAudioDevice *device);

/* For tests: what the device really runs at (the rate, the number of channels, and 1 if the samples are float32). Pointers may be NULL. */
void canopy_audio_describe(const CanopyAudioDevice *device, uint32_t *rate, uint32_t *channels, int *is_float32);

/* For tests: makes canopy_audio_open and canopy_audio_list behave as if miniaudio had failed before the context started (5: no audio system), after
   the context started (1), after the devices were listed (2), after the device was made (3), after the device was started (4); 0 turns it off. The
   null backend never fails by itself, so this is the only way to run the clean-up of each stage. */
void canopy_audio_force_failure(int stage);

/* The text canopy_audio_list gives, made from `count` names that lie `stride` bytes apart from `first` (a newline or carriage return inside a name
   becomes a space): one block from canopy_alloc, names separated by one '\n', no final newline, "" for none. CANOPY_OK or CANOPY_ERR_MEMORY. */
int32_t canopy_audio_join_names(const char *first, size_t stride, uint32_t count, char **text);

/* The allocation callbacks given to miniaudio (exposed for tests), each block with a 16 byte header that holds its size. `user` is the flag a
   failed allocation sets (a pointer to an atomic_int), or NULL. A block is freed with canopy_audio_release. */
void *canopy_audio_alloc(size_t size, void *user);
void *canopy_audio_grow(void *block, size_t size, void *user);
void canopy_audio_release(void *block, void *user);

#endif
