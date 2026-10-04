/* The audio device layer (src/canopy_audio.c, plan step 7) on miniaudio's null backend: a device that takes audio in real time and plays it
   nowhere, so these tests need no sound hardware. The real system is only listed (what it lists depends on the machine). */
#include <process.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <windows.h>
#include "support.h"
#include "../../src/canopy_audio.h"

typedef struct {
    atomic_llong callbacks, frames, stops;
    atomic_int bad;
} AudioProbe;

static void probe_fill(void *user, float *stereo, uint32_t frames)
{
    AudioProbe *probe = (AudioProbe *)user;
    memset(stereo, 0, (size_t)frames * 2 * sizeof(float));
    if (frames == 0 || frames > CANOPY_MAX_N) atomic_store(&probe->bad, 1);
    atomic_fetch_add(&probe->frames, frames);
    atomic_fetch_add(&probe->callbacks, 1);
}

static void probe_stopped(void *user)
{
    atomic_fetch_add(&((AudioProbe *)user)->stops, 1);
}

static CanopyAudioCallbacks callbacks_of(AudioProbe *probe)
{
    CanopyAudioCallbacks callbacks;
    callbacks.fill = probe_fill;
    callbacks.stopped = probe_stopped;
    callbacks.user = probe;
    return callbacks;
}

/* waits (at most 5 s, only to end a failing run) until *value is at least `target`: progress, not hope */
static int wait_at_least(atomic_llong *value, long long target)
{
    ULONGLONG deadline = GetTickCount64() + 5000;
    while (atomic_load(value) < target) {
        if (GetTickCount64() > deadline) return 0;
        Sleep(1);
    }
    return 1;
}

static void test_c_the_null_audio_system_lists_its_one_device_and_asking_for_the_list_leaks_nothing(void)
{
    int64_t live = canopy_alloc_live();
    char *text = NULL;
    CHECK_INT(canopy_audio_list(CANOPY_AUDIO_NULL, &text), CANOPY_OK);
    CHECK(text != NULL);
    if (text) CHECK(strcmp(text, "NULL Playback Device") == 0);
    canopy_free(text);
    CHECK_INT(canopy_alloc_live(), live);
    text = NULL;
    CHECK_INT(canopy_audio_list(99, &text), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_audio_list(-1, &text), CANOPY_ERR_ARGUMENT);
    CHECK(text == NULL);
    CHECK_INT(canopy_audio_list(CANOPY_AUDIO_NULL, NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_the_systems_own_audio_system_can_be_listed_whatever_the_machine_has_and_nothing_is_leaked(void)
{
    int64_t live = canopy_alloc_live();
    char *text = NULL;
    CHECK_INT(canopy_audio_list(CANOPY_AUDIO_SYSTEM, &text), CANOPY_OK);      /* a machine without sound hardware gives an empty list, not an error */
    CHECK(text != NULL);
    if (text) CHECK(strchr(text, '\r') == NULL);                              /* one name per line, separated by newlines only */
    if (text) CHECK(strstr(text, "NULL Playback Device") == NULL);            /* the null backend's device is not one of the machine's */
    canopy_free(text);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_a_device_calls_fill_in_real_time_at_48000_stereo_float_and_close_stops_it_for_good(void)
{
    int64_t live = canopy_alloc_live();
    AudioProbe probe;
    CanopyAudioCallbacks callbacks;
    CanopyAudioDevice *device = NULL;
    char why[200] = "";
    int used_default = -1, is_float = 0;
    uint32_t rate = 0, channels = 0;
    long long frames_after_close;
    LARGE_INTEGER start, now, frequency;
    double seconds;
    memset(&probe, 0, sizeof probe);
    callbacks = callbacks_of(&probe);
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&start);
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, &used_default, why, sizeof why), CANOPY_OK);
    CHECK(device != NULL);
    CHECK_INT(used_default, 0);
    if (!device) return;
    canopy_audio_describe(device, &rate, &channels, &is_float);
    CHECK_INT(rate, CANOPY_AUDIO_RATE);
    CHECK_INT(channels, 2);
    CHECK_INT(is_float, 1);
    CHECK(wait_at_least(&probe.callbacks, 3));                                /* it calls fill by itself... */
    CHECK(wait_at_least(&probe.frames, 24000));                               /* ...at the pace of the sound: half a second of audio takes about half a second */
    QueryPerformanceCounter(&now);
    seconds = (double)(now.QuadPart - start.QuadPart) / (double)frequency.QuadPart;
    CHECK(seconds > 0.40);                                                    /* (three periods of 20 ms may be handed over at the start) */
    CHECK(seconds < 3.0);
    canopy_audio_close(device);
    frames_after_close = atomic_load(&probe.frames);
    Sleep(100);
    CHECK_INT(atomic_load(&probe.frames), frames_after_close);                /* after close returns, fill is never called again */
    CHECK_INT(atomic_load(&probe.stops), 0);                                  /* and closing is not "the device stopped by itself" */
    CHECK_INT(atomic_load(&probe.bad), 0);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_a_device_is_found_by_its_exact_name_and_any_other_name_falls_back_to_the_default_and_says_so(void)
{
    static const struct { const char *name; int fell_back; } cases[] = {
        {"NULL Playback Device", 0}, {"", 0}, {CANOPY_AUDIO_DEFAULT_NAME, 0}, {NULL, 0},
        {"No such device", 1}, {"null playback device", 1}, {"NULL Playback Device ", 1},
    };
    int64_t live = canopy_alloc_live();
    size_t i;
    for (i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        AudioProbe probe;
        CanopyAudioCallbacks callbacks;
        CanopyAudioDevice *device = NULL;
        int used_default = -1;
        memset(&probe, 0, sizeof probe);
        callbacks = callbacks_of(&probe);
        CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, cases[i].name, &callbacks, &device, &used_default, NULL, 0), CANOPY_OK);
        CHECK_INT(used_default, cases[i].fell_back);
        if (!device) continue;
        CHECK(wait_at_least(&probe.callbacks, 1));                            /* it plays, whichever device it fell back to */
        canopy_audio_close(device);
    }
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_a_device_that_stops_by_itself_calls_stopped_once_and_closing_it_never_does(void)
{
    int64_t live = canopy_alloc_live();
    AudioProbe probe, quiet;
    CanopyAudioCallbacks callbacks;
    CanopyAudioDevice *device = NULL;
    long long frames_when_stopped;
    memset(&probe, 0, sizeof probe);
    memset(&quiet, 0, sizeof quiet);
    callbacks = callbacks_of(&probe);
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, NULL, 0), CANOPY_OK);
    if (!device) return;
    CHECK(wait_at_least(&probe.callbacks, 2));
    canopy_audio_stop_for_test(device);                                       /* as if it had been unplugged */
    CHECK(wait_at_least(&probe.stops, 1));
    frames_when_stopped = atomic_load(&probe.frames);
    Sleep(100);
    CHECK_INT(atomic_load(&probe.frames), frames_when_stopped);              /* a stopped device asks for no more audio */
    canopy_audio_close(device);                                               /* closing a device that has stopped is fine */
    CHECK_INT(atomic_load(&probe.stops), 1);
    callbacks = callbacks_of(&quiet);                                         /* closing a running device is not a stop by itself */
    device = NULL;
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, NULL, 0), CANOPY_OK);
    if (device) {
        CHECK(wait_at_least(&quiet.callbacks, 2));
        canopy_audio_close(device);
    }
    Sleep(50);
    CHECK_INT(atomic_load(&quiet.stops), 0);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_a_device_opened_without_a_stopped_callback_can_stop_by_itself_without_harm(void)
{
    int64_t live = canopy_alloc_live();
    AudioProbe probe;
    CanopyAudioCallbacks callbacks;
    CanopyAudioDevice *device = NULL;
    long long frames;
    memset(&probe, 0, sizeof probe);
    callbacks = callbacks_of(&probe);
    callbacks.stopped = NULL;
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, NULL, 0), CANOPY_OK);
    if (!device) return;
    CHECK(wait_at_least(&probe.callbacks, 2));
    canopy_audio_stop_for_test(device);                                           /* nobody to tell: nothing may happen, and nothing may crash */
    Sleep(100);
    frames = atomic_load(&probe.frames);
    Sleep(60);
    CHECK_INT(atomic_load(&probe.frames), frames);
    canopy_audio_close(device);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_opening_a_device_with_bad_arguments_is_refused_and_nothing_is_left_open(void)
{
    int64_t live = canopy_alloc_live();
    AudioProbe probe;
    CanopyAudioCallbacks callbacks, no_fill;
    CanopyAudioDevice *device = NULL;
    char why[100];
    memset(&probe, 0, sizeof probe);
    callbacks = callbacks_of(&probe);
    no_fill = callbacks;
    no_fill.fill = NULL;
    CHECK_INT(canopy_audio_open(99, "", &callbacks, &device, NULL, why, sizeof why), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_audio_open(-1, "", &callbacks, &device, NULL, why, sizeof why), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", NULL, &device, NULL, why, sizeof why), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", &no_fill, &device, NULL, why, sizeof why), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, NULL, NULL, why, sizeof why), CANOPY_ERR_ARGUMENT);
    CHECK(device == NULL);
    canopy_audio_close(NULL);                                                 /* nothing to close is fine */
    CHECK_INT(atomic_load(&probe.callbacks), 0);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_running_out_of_memory_while_opening_a_device_fails_cleanly_and_leaks_nothing(void)
{
    int64_t live = canopy_alloc_live();
    int k, failures = 0, successes = 0;
    for (k = 0; k < 300 && successes < 2; k++) {
        AudioProbe probe;
        CanopyAudioCallbacks callbacks;
        CanopyAudioDevice *device = NULL;
        char why[200] = "";
        int32_t status;
        memset(&probe, 0, sizeof probe);
        callbacks = callbacks_of(&probe);
        canopy_alloc_fail_after(k);
        status = canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, why, sizeof why);
        canopy_alloc_fail_after(-1);
        if (status == CANOPY_OK) {
            successes++;
            CHECK(device != NULL);
            canopy_audio_close(device);
        } else {
            failures++;
            CHECK_INT(status, CANOPY_ERR_MEMORY);                             /* (nothing but memory is wrong with the null backend) */
            CHECK(device == NULL);
        }
        CHECK_INT(canopy_alloc_live(), live);
    }
    CHECK(failures > 0);
    CHECK(successes >= 1);
    CHECK_HEAP();
}

static void test_c_running_out_of_memory_while_listing_devices_fails_cleanly_and_leaks_nothing(void)
{
    int64_t live = canopy_alloc_live();
    int k, failures = 0, successes = 0;
    for (k = 0; k < 300 && successes < 2; k++) {
        char *text = NULL;
        int32_t status;
        canopy_alloc_fail_after(k);
        status = canopy_audio_list(CANOPY_AUDIO_NULL, &text);
        canopy_alloc_fail_after(-1);
        if (status == CANOPY_OK) {
            successes++;
            CHECK(text != NULL);                                              /* (a start that failed for lack of memory is a failure, not an empty list) */
            canopy_free(text);
        } else {
            failures++;
            CHECK_INT(status, CANOPY_ERR_MEMORY);
            CHECK(text == NULL);
        }
        CHECK_INT(canopy_alloc_live(), live);
    }
    CHECK(failures > 0);
    CHECK(successes >= 1);
    CHECK_HEAP();
}

static unsigned __stdcall opener_main(void *argument)
{
    volatile LONG *bad = (volatile LONG *)argument;
    int i;
    for (i = 0; i < 12; i++) {
        AudioProbe probe;
        CanopyAudioCallbacks callbacks;
        CanopyAudioDevice *device = NULL;
        char *text = NULL;
        memset(&probe, 0, sizeof probe);
        callbacks = callbacks_of(&probe);
        if (canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, NULL, 0) != CANOPY_OK || !device) {
            InterlockedIncrement(bad);
            continue;
        }
        if (canopy_audio_list(CANOPY_AUDIO_NULL, &text) != CANOPY_OK) InterlockedIncrement(bad);
        canopy_free(text);
        canopy_audio_close(device);
    }
    return 0;
}

static void test_c_devices_opened_listed_and_closed_from_several_threads_at_once_all_work_and_leak_nothing(void)
{
    enum { THREADS = 4 };
    int64_t live = canopy_alloc_live();
    volatile LONG bad = 0;
    HANDLE handles[THREADS];
    int i;
    for (i = 0; i < THREADS; i++) handles[i] = (HANDLE)_beginthreadex(NULL, 0, opener_main, (void *)&bad, 0, NULL);
    WaitForMultipleObjects(THREADS, handles, TRUE, INFINITE);
    for (i = 0; i < THREADS; i++) CloseHandle(handles[i]);
    CHECK_INT(bad, 0);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_a_failure_at_any_stage_of_opening_a_device_says_why_cleans_up_and_lets_the_next_open_work(void)
{
    static const char *const SAYS[5] = {"forced failure after the context started", "the audio devices cannot be listed",
                                        "forced failure after the device was made", "the audio device cannot be started", "no audio system"};
    int64_t live = canopy_alloc_live();
    int stage;
    for (stage = 1; stage <= 5; stage++) {
        AudioProbe probe;
        CanopyAudioCallbacks callbacks;
        CanopyAudioDevice *device = (CanopyAudioDevice *)&probe;             /* (must be reset to NULL by the failing call) */
        char why[200] = "";
        int32_t status;
        long long frames;
        memset(&probe, 0, sizeof probe);
        callbacks = callbacks_of(&probe);
        canopy_audio_force_failure(stage);
        status = canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, why, sizeof why);
        canopy_audio_force_failure(0);
        CHECK_INT(status, CANOPY_AUDIO_ERR_DEVICE);
        CHECK(device == NULL);
        CHECK(strstr(why, SAYS[stage - 1]) != NULL);                          /* the reason is the sentence of the stage */
        CHECK_INT(canopy_alloc_live(), live);                                 /* nothing is left: the context, the device and the record are gone */
        frames = atomic_load(&probe.frames);
        Sleep(60);
        CHECK_INT(atomic_load(&probe.frames), frames);                        /* (stage 4 had started the device: it is stopped for good) */
        device = NULL;
        status = canopy_audio_open(CANOPY_AUDIO_NULL, "", &callbacks, &device, NULL, why, sizeof why);
        CHECK_INT(status, CANOPY_OK);                                         /* the lock was let go: the next open is not stuck behind the failed one */
        CHECK(device != NULL);
        if (device) {
            CHECK(wait_at_least(&probe.callbacks, 1));
            canopy_audio_close(device);
        }
        CHECK_INT(canopy_alloc_live(), live);
    }
    CHECK_HEAP();
}

static void test_c_a_device_list_that_fails_is_a_list_of_none_not_an_error_and_the_next_list_works(void)
{
    int64_t live = canopy_alloc_live();
    char *text = NULL;
    int stage;
    for (stage = 2; stage <= 5; stage += 3) {                                    /* the devices cannot be listed (2); there is no audio system (5) */
        canopy_audio_force_failure(stage);
        CHECK_INT(canopy_audio_list(CANOPY_AUDIO_NULL, &text), CANOPY_OK);
        canopy_audio_force_failure(0);
        CHECK(text != NULL && text[0] == '\0');
        canopy_free(text);
        text = NULL;
    }
    CHECK_INT(canopy_audio_list(CANOPY_AUDIO_NULL, &text), CANOPY_OK);          /* the lock was let go and the context closed */
    CHECK(text != NULL && strcmp(text, "NULL Playback Device") == 0);
    canopy_free(text);
    CHECK_INT(canopy_alloc_live(), live);
    CHECK_HEAP();
}

static void test_c_device_names_are_joined_one_per_line_and_a_line_break_inside_a_name_becomes_a_space(void)
{
    static const char names[4][16] = {"Speakers", "Head\nphones", "A\r\nB", ""};
    int64_t live = canopy_alloc_live();
    char *text = NULL;
    CHECK_INT(canopy_audio_join_names(names[0], 16, 4, &text), CANOPY_OK);
    CHECK(text != NULL && strcmp(text, "Speakers\nHead phones\nA  B\n") == 0);   /* (the last name is empty: a name per line, none after the last) */
    canopy_free(text);
    text = NULL;
    CHECK_INT(canopy_audio_join_names(names[0], 16, 1, &text), CANOPY_OK);
    CHECK(text != NULL && strcmp(text, "Speakers") == 0);                         /* no final newline */
    canopy_free(text);
    text = NULL;
    CHECK_INT(canopy_audio_join_names(names[0], 16, 0, &text), CANOPY_OK);
    CHECK(text != NULL && text[0] == '\0');
    canopy_free(text);
    text = NULL;
    canopy_alloc_fail_after(0);
    CHECK_INT(canopy_audio_join_names(names[0], 16, 2, &text), CANOPY_ERR_MEMORY);
    canopy_alloc_fail_after(-1);
    CHECK(text == NULL);
    CHECK_INT(canopy_alloc_live(), live);
}

#define FLAG(f) ((void *)&(f))         /* the flag a failed allocation sets, as the void pointer the callbacks take */

static void test_c_the_allocation_callbacks_of_miniaudio_keep_their_size_zero_the_new_tail_and_are_counted_with_ours(void)
{
    int64_t live = canopy_alloc_live();
    atomic_int failed;
    unsigned char *p;
    int i, bad = 0;
    atomic_init(&failed, 0);
    p = (unsigned char *)canopy_audio_alloc(100, FLAG(failed));
    CHECK(p != NULL);
    if (!p) return;
    CHECK_INT(((uintptr_t)p) & 15u, 0);                                          /* 16 byte aligned, as miniaudio's own allocator would give */
    CHECK_INT(canopy_alloc_live(), live + 1);
    memset(p, 0xAB, 100);
    p = (unsigned char *)canopy_audio_grow(p, 300, FLAG(failed));
    CHECK(p != NULL);
    if (!p) return;
    for (i = 0; i < 100; i++) if (p[i] != 0xAB) bad++;
    for (i = 100; i < 300; i++) if (p[i] != 0) bad++;                              /* the new tail is zero */
    CHECK_INT(bad, 0);
    p = (unsigned char *)canopy_audio_grow(p, 50, FLAG(failed));                       /* a smaller size keeps what fits */
    CHECK(p != NULL);
    if (!p) return;
    for (i = 0; i < 50; i++) if (p[i] != 0xAB) bad++;
    CHECK_INT(bad, 0);
    p = (unsigned char *)canopy_audio_grow(p, 400, FLAG(failed));                      /* and the size is the new one: 50 kept, the rest zero */
    CHECK(p != NULL);
    if (!p) return;
    for (i = 0; i < 50; i++) if (p[i] != 0xAB) bad++;
    for (i = 50; i < 400; i++) if (p[i] != 0) bad++;
    CHECK_INT(bad, 0);
    canopy_audio_release(p, FLAG(failed));
    canopy_audio_release(NULL, FLAG(failed));                                          /* nothing to release is fine */
    CHECK_INT(canopy_alloc_live(), live);
    p = (unsigned char *)canopy_audio_grow(NULL, 64, FLAG(failed));                    /* growing nothing is allocating */
    CHECK(p != NULL);
    canopy_audio_release(p, NULL);
    canopy_alloc_fail_after(0);                                                   /* the tests' failure hook does not reach miniaudio's allocations... */
    p = (unsigned char *)canopy_audio_alloc(10, FLAG(failed));
    CHECK(p != NULL);
    if (p) p = (unsigned char *)canopy_audio_grow(p, 5000, FLAG(failed));         /* ...nor its growing of one */
    canopy_alloc_fail_after(-1);
    CHECK(p != NULL);
    canopy_audio_release(p, FLAG(failed));
    CHECK_INT(atomic_load(&failed), 0);
    CHECK(canopy_audio_alloc(SIZE_MAX - 8, FLAG(failed)) == NULL);                     /* a size whose header would overflow is refused... */
    CHECK_INT(atomic_load(&failed), 1);                                           /* ...and the flag says that memory is the reason */
    atomic_store(&failed, 0);
    p = (unsigned char *)canopy_audio_alloc(10, NULL);
    CHECK(p != NULL);
    CHECK(canopy_audio_grow(p, SIZE_MAX - 8, FLAG(failed)) == NULL);
    CHECK_INT(atomic_load(&failed), 1);
    canopy_audio_release(p, NULL);                                                 /* (the block is still ours when growing fails) */
    atomic_store(&failed, 0);
    CHECK(canopy_audio_alloc((size_t)1 << 50, FLAG(failed)) == NULL);                  /* more than the machine has */
    CHECK_INT(atomic_load(&failed), 1);
    CHECK_INT(canopy_alloc_live(), live);
}

void register_test_audio(void)
{
    RUN(test_c_the_null_audio_system_lists_its_one_device_and_asking_for_the_list_leaks_nothing);
    RUN(test_c_the_systems_own_audio_system_can_be_listed_whatever_the_machine_has_and_nothing_is_leaked);
    RUN(test_c_a_device_calls_fill_in_real_time_at_48000_stereo_float_and_close_stops_it_for_good);
    RUN(test_c_a_device_is_found_by_its_exact_name_and_any_other_name_falls_back_to_the_default_and_says_so);
    RUN(test_c_a_device_that_stops_by_itself_calls_stopped_once_and_closing_it_never_does);
    RUN(test_c_a_device_opened_without_a_stopped_callback_can_stop_by_itself_without_harm);
    RUN(test_c_opening_a_device_with_bad_arguments_is_refused_and_nothing_is_left_open);
    RUN(test_c_running_out_of_memory_while_opening_a_device_fails_cleanly_and_leaks_nothing);
    RUN(test_c_running_out_of_memory_while_listing_devices_fails_cleanly_and_leaks_nothing);
    RUN(test_c_devices_opened_listed_and_closed_from_several_threads_at_once_all_work_and_leak_nothing);
    RUN(test_c_a_failure_at_any_stage_of_opening_a_device_says_why_cleans_up_and_lets_the_next_open_work);
    RUN(test_c_a_device_list_that_fails_is_a_list_of_none_not_an_error_and_the_next_list_works);
    RUN(test_c_device_names_are_joined_one_per_line_and_a_line_break_inside_a_name_becomes_a_space);
    RUN(test_c_the_allocation_callbacks_of_miniaudio_keep_their_size_zero_the_new_tail_and_are_counted_with_ours);
}
