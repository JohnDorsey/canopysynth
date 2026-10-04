/* The realtime preview node (src/canopy_preview.c, plan step 7, design sections 9 and 11).
   Most tests run the audio callback's work directly (canopy_preview_fill: the same function the device's thread calls), against exact
   references; the rest open miniaudio's null backend, which takes the audio in real time and plays it nowhere, and pace themselves by the
   callbacks' progress. Nothing here needs sound hardware. */
#include <math.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "support.h"
#include "../../src/canopy_core.h"
#include "../../src/canopy_audio.h"

#define PREVIEW 50

/* ---- references and helpers ---- */

/* The time of a frame of 48000 Hz in nanoseconds, floor((frame * 10^9 + 24000) / 48000): round half up, for frames of any sign that are not huge. */
static int64_t ref_ns(int64_t frame)
{
    int64_t numerator = frame * 1000000000LL + 24000, q = numerator / 48000, r = numerator % 48000;
    if (r < 0) q--;
    return q;
}

/* The frame nearest to a time, floor((ns * 48000 + 5 * 10^8) / 10^9), for times that are not huge. */
static int64_t ref_frame(int64_t ns)
{
    int64_t numerator = ns * 48000 + 500000000LL, q = numerator / 1000000000LL, r = numerator % 1000000000LL;
    if (r < 0) q--;
    return q;
}

/* Sample i of a span [t0, t1) with n samples, t0 + floor(i * (t1 - t0) / n), by the plain formula (the engine uses quotient and remainder). */
static int64_t ref_sample_time(int64_t t0, int64_t t1, int64_t n, int64_t i)
{
    int64_t numerator = i * (t1 - t0), q = numerator / n, r = numerator % n;
    if (r < 0) q--;
    return t0 + q;
}

static void preview_rig(Rig *rig)
{
    rig_open(rig);
    CHECK_INT(canopy_engine_set_audio_backend(rig->engine, CANOPY_AUDIO_NULL), CANOPY_OK);
}

/* a preview node (50) fed on `left` by a constant (1) */
static void constant_rig(Rig *rig, double left_value)
{
    preview_rig(rig);
    rig_node(rig, 1, "test.const");
    rig_node(rig, PREVIEW, "realtime_preview");
    rig_connect(rig, 1, "out", PREVIEW, "left");
    CHECK_INT(canopy_graph_set_float(rig->graph, 1, "value", left_value), CANOPY_OK);
    rig_install(rig);
}

/* how many frames of `out` (interleaved stereo) are not exactly (left, right) */
static int bad_frames(const Guarded *out, uint32_t frames, float left, float right)
{
    int bad = 0;
    uint32_t i;
    for (i = 0; i < frames; i++)
        if (float_bits(out->data[2 * i]) != float_bits(left) || float_bits(out->data[2 * i + 1]) != float_bits(right)) bad++;
    return bad;
}

static int wait_for_callbacks(const atomic_llong *counter, long long target)
{
    ULONGLONG deadline = GetTickCount64() + 5000;
    while (atomic_load(counter) < target) {
        if (GetTickCount64() > deadline) return 0;
        Sleep(1);
    }
    return 1;
}

static int wait_for_time(CanopyEngine *engine, int64_t node_id, int64_t ns)
{
    ULONGLONG deadline = GetTickCount64() + 5000;
    for (;;) {
        int64_t t = -1;
        if (canopy_preview_state(engine, node_id, NULL, &t) == CANOPY_OK && t >= ns) return 1;
        if (GetTickCount64() > deadline) return 0;
        Sleep(1);
    }
}

static int32_t playing_of(CanopyEngine *engine, int64_t node_id)
{
    int32_t playing = -1;
    (void)canopy_preview_state(engine, node_id, &playing, NULL);
    return playing;
}

static int64_t time_of(CanopyEngine *engine, int64_t node_id)
{
    int64_t t = INT64_MIN;
    (void)canopy_preview_state(engine, node_id, NULL, &t);
    return t;
}

static int64_t opens_of(CanopyEngine *engine, int64_t node_id)
{
    int64_t callbacks = -1, opens = -1;
    (void)canopy_preview_counts(engine, node_id, &callbacks, &opens);
    return opens;
}

static void message_of(CanopyEngine *engine, int64_t node_id, char *buffer, int32_t size)
{
    int32_t length = -1;
    buffer[0] = '?';
    if (canopy_engine_node_message(engine, node_id, buffer, size, &length) != CANOPY_OK) strcpy(buffer, "(no such node)");
}

static const atomic_llong *counter_of(CanopyEngine *engine, int64_t node_id)
{
    const atomic_llong *counter = canopy_preview_callback_counter(engine, node_id);
    CHECK(counter != NULL);
    return counter;
}

/* ---- the node type ---- */

static void test_c_the_preview_node_type_is_built_in_and_described_as_the_design_says(void)
{
    CanopyRegistry *registry = canopy_registry_new(), *empty = canopy_registry_new_empty();
    const CanopyNodeType *type = canopy_registry_find(registry, "realtime_preview");
    CHECK(type != NULL);
    CHECK(canopy_registry_find(empty, "realtime_preview") == NULL);
    if (type) {
        CHECK(strcmp(type->name, "Realtime preview") == 0);
        CHECK_INT(type->type_version, 1);
        CHECK_INT(type->flags, CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_SERVICE);
        CHECK_INT(type->n_inlets, 3);
        if (type->n_inlets == 3) {
            CHECK(strcmp(type->inlets[0].key, "left") == 0 && strcmp(type->inlets[0].label, "Left") == 0);
            CHECK(strcmp(type->inlets[1].key, "right") == 0 && strcmp(type->inlets[1].label, "Right") == 0);
            CHECK(strcmp(type->inlets[2].key, "center") == 0 && strcmp(type->inlets[2].label, "Center") == 0);
            CHECK(type->inlets[0].default_knob == 0.0f && type->inlets[1].default_knob == 0.0f && type->inlets[2].default_knob == 0.0f);
        }
        CHECK_INT(type->n_outlets, 0);                                              /* other nodes cannot see the playback state */
        CHECK_INT(type->n_settings, 1);
        if (type->n_settings == 1) {
            CHECK(strcmp(type->settings[0].key, "device") == 0);
            CHECK_INT(type->settings[0].kind, CANOPY_SETTING_STRING);
            CHECK(type->settings[0].default_string && strcmp(type->settings[0].default_string, CANOPY_AUDIO_DEFAULT_NAME) == 0);
        }
        CHECK_INT(type->n_widgets, 3);
        if (type->n_widgets == 3) {
            CHECK_INT(type->widgets[0].kind, CANOPY_WIDGET_BUTTON);
            CHECK(strcmp(type->widgets[0].label, "Play") == 0 && strcmp(type->widgets[0].action, "play") == 0);
            CHECK_INT(type->widgets[1].kind, CANOPY_WIDGET_BUTTON);
            CHECK(strcmp(type->widgets[1].label, "Pause") == 0 && strcmp(type->widgets[1].action, "pause") == 0);
            CHECK_INT(type->widgets[2].kind, CANOPY_WIDGET_CHOICE);
            CHECK(strcmp(type->widgets[2].label, "Device") == 0 && strcmp(type->widgets[2].setting, "device") == 0);
            CHECK_INT(type->widgets[2].n_choices, 1);                                /* the one fixed entry; the editor adds the devices of the machine */
            if (type->widgets[2].n_choices == 1) CHECK(strcmp(type->widgets[2].choices[0], CANOPY_AUDIO_DEFAULT_NAME) == 0);
        }
        CHECK(type->handlers.create_shared && type->handlers.destroy_shared && type->handlers.on_action);
        CHECK(!type->handlers.query_at && !type->handlers.query_span && !type->handlers.create_instance);
        CHECK_INT(type->scratch_buffers, 0);
    }
    canopy_registry_free(registry);
    canopy_registry_free(empty);
}

/* ---- what the audio callback does, run directly ---- */

static void test_c_the_preview_sends_left_plus_center_to_the_left_channel_and_right_plus_center_to_the_right_channel_exactly(void)
{
    enum { FRAMES = 480 };
    Rig rig;
    Guarded out;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.const");
    rig_node(&rig, 3, "test.const");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    rig_connect(&rig, 2, "out", PREVIEW, "right");
    rig_connect(&rig, 3, "out", PREVIEW, "center");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.25), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig.graph, 2, "value", -0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig.graph, 3, "value", 0.125), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.25f + 0.125f, -0.5f + 0.125f), 0);
    CHECK(guarded_guards_intact(&out));
    CHECK_INT(guarded_unwritten(&out), 0);
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_unconnected_preview_inlets_play_their_knobs(void)
{
    enum { FRAMES = 64 };
    Rig rig;
    Guarded out;
    preview_rig(&rig);
    rig_node(&rig, PREVIEW, "realtime_preview");
    CHECK_INT(canopy_graph_set_knob(rig.graph, PREVIEW, "left", 0.5f), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(rig.graph, PREVIEW, "right", -0.25f), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(rig.graph, PREVIEW, "center", 0.125f), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.5f + 0.125f, -0.25f + 0.125f), 0);
    CHECK_INT(canopy_engine_set_knob(rig.engine, PREVIEW, 2, -0.5f), CANOPY_OK);          /* a knob moved at run time is heard at the next callback */
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.5f + -0.5f, -0.25f + -0.5f), 0);
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_the_preview_clips_sums_beyond_full_scale_and_plays_nan_as_silence(void)
{
    enum { FRAMES = 8 };
    static const struct { float l, r, c, want_l, want_r; } cases[] = {
        {0.9f, 0.9f, 0.9f, 1.0f, 1.0f},                 /* 1.8 is beyond full scale */
        {-0.9f, -0.9f, -0.9f, -1.0f, -1.0f},
        {0.5f, 0.5f, 0.5f, 1.0f, 1.0f},                 /* exactly full scale stays */
        {0.5f, -0.5f, 0.25f, 0.75f, -0.25f},            /* inside: untouched */
        {1.0f, -1.0f, 0.0f, 1.0f, -1.0f},
        {1.0f, 1.0f, 1.0f, 1.0f, 1.0f},
        {-1.0f, -1.0f, -1.0f, -1.0f, -1.0f},
        {NAN, 0.25f, 0.0f, 0.0f, 0.25f},                /* NaN is silence, not a click at full scale */
        {0.0f, NAN, 0.0f, 0.0f, 0.0f},
        {0.25f, 0.5f, NAN, 0.0f, 0.0f},                 /* the center is in both channels */
        {INFINITY, 0.0f, 0.0f, 1.0f, 0.0f},
        {-INFINITY, 0.0f, 0.0f, -1.0f, 0.0f},
        {INFINITY, 0.0f, -INFINITY, 0.0f, -1.0f},       /* +inf + -inf is NaN: silence; the other channel is -inf: clipped */
        {1.0e30f, -1.0e30f, 0.0f, 1.0f, -1.0f},
    };
    Rig rig;
    Guarded out;
    size_t k;
    preview_rig(&rig);
    rig_node(&rig, 1, "boundary_inlet");
    rig_node(&rig, 2, "boundary_inlet");
    rig_node(&rig, 3, "boundary_inlet");
    rig_node(&rig, PREVIEW, "realtime_preview");
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "name", "l"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig.graph, 2, "name", "r"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig.graph, 3, "name", "c"), CANOPY_OK);
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    rig_connect(&rig, 2, "out", PREVIEW, "right");
    rig_connect(&rig, 3, "out", PREVIEW, "center");
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    for (k = 0; k < sizeof cases / sizeof cases[0]; k++) {
        CHECK_INT(canopy_engine_set_boundary(rig.engine, "l", cases[k].l), CANOPY_OK);
        CHECK_INT(canopy_engine_set_boundary(rig.engine, "r", cases[k].r), CANOPY_OK);
        CHECK_INT(canopy_engine_set_boundary(rig.engine, "c", cases[k].c), CANOPY_OK);
        guarded_reset(&out);
        CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
        if (bad_frames(&out, FRAMES, cases[k].want_l, cases[k].want_r) != 0) {
            printf("    case %d: (%g, %g, %g) gave (%g, %g), wanted (%g, %g)\n", (int)k, cases[k].l, cases[k].r, cases[k].c, out.data[0], out.data[1],
                   cases[k].want_l, cases[k].want_r);
            ctest_current_failed = 1;
        }
    }
    guarded_free(&out);
    rig_close(&rig);
}

/* The source is a recorder that is asked once for every sample time (test.recorder, pointwise): the log is the exact list of times the preview asked
   for. The callback must ask for exactly the frames it is about to play. (The output itself cannot show the times: it is clipped to full scale.) */
static void check_time_chunk(Rig *rig, int64_t start_frame, uint32_t frames)
{
    Guarded out = guarded_new(2 * (int64_t)frames);
    int64_t t0 = ref_ns(start_frame), t1 = ref_ns(start_frame + frames), i;
    int bad = 0;
    CHECK_INT(canopy_preview_set_time(rig->engine, PREVIEW, t0), CANOPY_OK);
    CHECK_INT(time_of(rig->engine, PREVIEW), t0);
    support_calls_reset();
    CHECK_INT(canopy_preview_fill(rig->engine, PREVIEW, out.data, frames), CANOPY_OK);
    CHECK_INT(support_ncalls, (int)frames);
    for (i = 0; i < frames && i < support_ncalls; i++)
        if (support_calls[i].is_span || support_calls[i].t0 != ref_sample_time(t0, t1, frames, i)) bad++;
    if (bad != 0) {
        printf("    from frame %lld, %u frames: %d of the times asked for are not where the span puts them\n", (long long)start_frame, (unsigned)frames, bad);
        ctest_current_failed = 1;
    }
    CHECK_INT(bad_frames(&out, frames, 0.5f, 0.0f), 0);
    CHECK_INT(time_of(rig->engine, PREVIEW), t1);                                    /* the time has moved on by exactly the frames played */
    CHECK(guarded_guards_intact(&out));
    guarded_free(&out);
}

static void test_c_the_preview_asks_the_graph_for_exactly_the_frames_it_is_about_to_play_and_the_time_moves_on_by_that_many(void)
{
    Rig rig;
    Guarded out;
    preview_rig(&rig);
    rig_node(&rig, 4, "test.recorder");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 4, "out", PREVIEW, "left");
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    check_time_chunk(&rig, 0, 480);
    check_time_chunk(&rig, 960000, 480);                                              /* 20 s */
    check_time_chunk(&rig, 48000 * 3600LL, 1000);                                     /* an hour in */
    check_time_chunk(&rig, -48000, 480);                                              /* before t = 0: negative times are legal */
    check_time_chunk(&rig, 12345, 1);
    check_time_chunk(&rig, 777, 4096);
    /* consecutive callbacks tile: the second asks from where the first stopped */
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, 0), CANOPY_OK);
    out = guarded_new(2 * 480);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, 480), CANOPY_OK);
    CHECK_INT(time_of(rig.engine, PREVIEW), ref_ns(480));
    support_calls_reset();
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, 480), CANOPY_OK);
    CHECK_INT(support_ncalls, 480);
    if (support_ncalls > 0) CHECK_INT(support_calls[0].t0, ref_ns(480));             /* the first sample of the second callback is at the end of the first */
    CHECK_INT(time_of(rig.engine, PREVIEW), ref_ns(960));
    guarded_free(&out);
    rig_close(&rig);
}

static CanopyEngine *seek_engine;
static int seek_done;

static float seeker_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx; (void)outlet; (void)t;
    if (!seek_done) {
        seek_done = 1;
        CHECK_INT(canopy_preview_set_time(seek_engine, PREVIEW, 5000000000LL), CANOPY_OK);      /* the user types a new time while the callback runs */
    }
    return 0.25f;
}

static void test_c_a_seek_during_a_callback_wins_over_the_advance(void)
{
    static const CanopyOutletDesc SEEKER_OUTLET[] = {{"out", "Out"}};
    enum { FRAMES = 480 };
    Rig rig;
    CanopyNodeType type;
    Guarded out;
    preview_rig(&rig);
    type = support_base_type("test.seeker", "Seeker");
    type.n_outlets = 1; type.outlets = SEEKER_OUTLET;
    type.handlers.query_at = seeker_at;
    support_add_type(rig.registry, &type);
    rig_node(&rig, 5, "test.seeker");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 5, "out", PREVIEW, "left");
    rig_install(&rig);
    seek_engine = rig.engine;
    seek_done = 0;
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, 1000000000LL), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK(seek_done);
    CHECK_INT(time_of(rig.engine, PREVIEW), 5000000000LL);                           /* not 5 s + 10 ms, and not 1 s + 10 ms */
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(time_of(rig.engine, PREVIEW), 5000000000LL + 10000000LL);              /* and it goes on from there */
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_a_paused_preview_plays_silence_asks_the_graph_nothing_and_stands_still(void)
{
    enum { FRAMES = 480 };
    Rig rig;
    Guarded out;
    support_counters_reset();
    preview_rig(&rig);
    rig_node(&rig, 1, "test.counter");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.75), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "tag", 3), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 0), CANOPY_OK);
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, 2000000000LL), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.0f, 0.0f), 0);
    CHECK_INT(guarded_unwritten(&out), 0);                                           /* every sample was written, with silence */
    CHECK_INT(support_counts[3], 0);
    CHECK_INT(time_of(rig.engine, PREVIEW), 2000000000LL);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);            /* playing: the sound, and the time moves */
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.75f, 0.0f), 0);
    CHECK_INT(support_counts[3], FRAMES);
    CHECK_INT(time_of(rig.engine, PREVIEW), 2010000000LL);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "pause"), CANOPY_OK);        /* pause needs no device */
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.0f, 0.0f), 0);
    CHECK_INT(time_of(rig.engine, PREVIEW), 2010000000LL);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, 0), CANOPY_OK);     /* an empty callback does nothing */
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_a_callback_for_more_than_65536_frames_asks_in_chunks_that_tile_exactly(void)
{
    enum { FRAMES = 150000 };
    Rig rig;
    Guarded out;
    int64_t start = 4800, expect_n[3] = {65536, 65536, FRAMES - 2 * 65536}, edge = start;
    int i;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.recorder_span");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, ref_ns(start)), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    support_calls_reset();
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(support_ncalls, 3);                                                    /* only the connected inlet is asked, once per chunk */
    for (i = 0; i < 3 && i < support_ncalls; i++) {
        CHECK_INT(support_calls[i].is_span, 1);
        CHECK_INT(support_calls[i].n, expect_n[i]);
        CHECK_INT(support_calls[i].t0, ref_ns(edge));                                /* each chunk starts where the one before ended... */
        CHECK_INT(support_calls[i].t1, ref_ns(edge + expect_n[i]));                  /* ...and ends at the frame boundary after its own frames */
        edge += expect_n[i];
    }
    CHECK_INT(bad_frames(&out, FRAMES, 0.25f, 0.0f), 0);
    CHECK_INT(time_of(rig.engine, PREVIEW), ref_ns(start + FRAMES));
    CHECK(guarded_guards_intact(&out));
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_a_source_that_fails_is_silence_for_its_channel_only(void)
{
    enum { FRAMES = 120 };
    Rig rig;
    Guarded out;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.failing_span_only");
    rig_node(&rig, 2, "test.const");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    rig_connect(&rig, 2, "out", PREVIEW, "right");
    CHECK_INT(canopy_graph_set_float(rig.graph, 2, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.0f, 0.5f), 0);                              /* (the node wrote 123 and said 77: the engine zero-filled it) */
    CHECK_INT(time_of(rig.engine, PREVIEW), ref_ns(FRAMES));                         /* the time goes on: a failing node is not a stopped preview */
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_a_deleted_preview_plays_silence_and_stands_still_and_comes_back_when_it_is_added_again(void)
{
    enum { FRAMES = 480 };
    Rig rig;
    CanopyGraph *without, *again;
    Guarded out;
    int64_t when;
    constant_rig(&rig, 0.25);
    without = canopy_graph_new();                                                      /* (the graphs are made after the rig, which counts what is live at its start) */
    again = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(without, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(again, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(again, PREVIEW, "realtime_preview"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(again, 1, "out", PREVIEW, "left"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(again, 1, "value", 0.75), CANOPY_OK);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.25f, 0.0f), 0);
    when = time_of(rig.engine, PREVIEW);
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);              /* the node is deleted: the audio thread's instance still has it until it looks */
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.0f, 0.0f), 0);                              /* it adopted the graph without the node: silence... */
    CHECK_INT(guarded_unwritten(&out), 0);
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    /* ...and the position stands still (the node's record lives while a graph that has it is held) */
    CHECK_INT(canopy_engine_set_graph(rig.engine, again), CANOPY_OK);                 /* added again, same ID, before anything was collected */
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.75f, 0.0f), 0);                              /* plays again, from where it stood (not from zero) */
    CHECK_INT(time_of(rig.engine, PREVIEW), when + 10000000LL);
    /* deleted and collected: the node's resource goes (the position with it), and a node of that ID added later starts afresh */
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);  /* the audio thread moves on to the graph without the node... */
    (void)canopy_instance_inlet_at(rig.instance, 1, 0, 0);                            /* ...and so does the host's instance: no graph that has the node is in use */
    (void)canopy_engine_collect(rig.engine);
    CHECK_INT(canopy_engine_service_count(rig.engine), 0);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_set_graph(rig.engine, again), CANOPY_OK);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    CHECK_INT(time_of(rig.engine, PREVIEW), 0);
    guarded_free(&out);
    canopy_graph_free(without);
    canopy_graph_free(again);
    rig_close(&rig);
}

static void test_c_the_next_callback_runs_an_edited_graph(void)
{
    enum { FRAMES = 120 };
    Rig rig;
    CanopyGraph *louder;
    Guarded out;
    constant_rig(&rig, 0.25);
    louder = canopy_graph_new();                                                       /* (made after the rig, which counts what is live at its start) */
    CHECK_INT(canopy_graph_add_node(louder, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(louder, PREVIEW, "realtime_preview"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(louder, 1, "out", PREVIEW, "left"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(louder, 1, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.25f, 0.0f), 0);
    CHECK_INT(canopy_engine_set_graph(rig.engine, louder), CANOPY_OK);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.5f, 0.0f), 0);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.25f, 0.0f), 0);
    CHECK_INT(time_of(rig.engine, PREVIEW), ref_ns(3 * FRAMES));                      /* the position went on through the edits */
    guarded_free(&out);
    canopy_graph_free(louder);
    rig_close(&rig);
}

static void test_c_the_callback_allocates_nothing(void)
{
    enum { FRAMES = 480 };
    Rig rig;
    Guarded out;
    int64_t before;
    int i;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.gain");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", PREVIEW, "left");                                      /* a node that uses scratch buffers in between */
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    for (i = 0; i < 3; i++) CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    before = canopy_alloc_total();
    for (i = 0; i < 200; i++) CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(canopy_alloc_total(), before);
    CHECK_INT(bad_frames(&out, FRAMES, 0.5f * 1.0f, 0.0f), 0);
    guarded_free(&out);
    rig_close(&rig);
}

static void test_c_times_at_the_ends_of_the_range_never_overflow(void)
{
    enum { FRAMES = 480 };
    Rig rig;
    Guarded out;
    int64_t t = 0, before;
    preview_rig(&rig);
    rig_node(&rig, 4, "test.time");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 4, "a", PREVIEW, "left");
    rig_install(&rig);
    CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_OK);
    out = guarded_new(2 * FRAMES);
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, INT64_MAX), CANOPY_OK);
    CHECK_INT(canopy_preview_state(rig.engine, PREVIEW, NULL, &t), CANOPY_OK);
    CHECK(t > INT64_MAX - 20000);                                                    /* (a frame is 20833 ns: the nearest frame is within half of it) */
    before = t;
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK_INT(bad_frames(&out, FRAMES, 0.0f, 0.0f), 0);                              /* the end of time: nothing to ask, silence, and no wrapping round */
    CHECK_INT(time_of(rig.engine, PREVIEW), before);
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, INT64_MIN), CANOPY_OK);
    CHECK_INT(canopy_preview_state(rig.engine, PREVIEW, NULL, &t), CANOPY_OK);
    CHECK(t < INT64_MIN + 20000);
    CHECK_INT(canopy_preview_fill(rig.engine, PREVIEW, out.data, FRAMES), CANOPY_OK);
    CHECK(guarded_guards_intact(&out));
    CHECK(time_of(rig.engine, PREVIEW) <= before);                                   /* it did not jump to the other end */
    guarded_free(&out);
    rig_close(&rig);
}

/* ---- the exported functions ---- */

static void test_c_state_set_time_and_warning_refuse_what_is_not_a_preview_node_and_report_unknown_nodes(void)
{
    Rig rig;
    char text[40];
    int32_t length = -1, playing = -1;
    int64_t t = -1;
    constant_rig(&rig, 0.25);
    CHECK_INT(canopy_preview_state(rig.engine, 999, &playing, &t), CANOPY_ERR_NODE);
    CHECK_INT(canopy_preview_set_time(rig.engine, 999, 0), CANOPY_ERR_NODE);
    CHECK_INT(canopy_preview_warning(rig.engine, 999, text, sizeof text, &length), CANOPY_ERR_NODE);
    CHECK_INT(canopy_preview_state(rig.engine, 1, &playing, &t), CANOPY_ERR_ARGUMENT);        /* node 1 is a constant */
    CHECK_INT(canopy_preview_set_time(rig.engine, 1, 0), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_preview_warning(rig.engine, 1, text, sizeof text, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_preview_state(NULL, PREVIEW, &playing, &t), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_preview_set_time(NULL, PREVIEW, 0), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_preview_warning(NULL, PREVIEW, text, sizeof text, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_preview_state(rig.engine, PREVIEW, NULL, NULL), CANOPY_OK);              /* both outputs are optional */
    CHECK_INT(canopy_preview_state(rig.engine, PREVIEW, &playing, &t), CANOPY_OK);
    CHECK_INT(playing, 0);
    CHECK_INT(t, 0);
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, NULL, 0, NULL), CANOPY_OK);
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, NULL, 4, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, text, -1, &length), CANOPY_ERR_ARGUMENT);
    rig_close(&rig);
}

static void test_c_the_playback_time_is_set_exactly_for_whole_milliseconds_and_rounded_to_a_frame_otherwise(void)
{
    static const int64_t whole_ms[] = {0, 1, 999, 1000, 61000, 3600000, 86400000, 360000000, -1500, -3600000};
    static const int64_t odd_ns[] = {1, 10416, 10417, 20833, 20834, 123456789, 999999999, 1000000001, -1, -10417, -10418, -123456789};
    Rig rig;
    size_t i;
    constant_rig(&rig, 0.25);
    for (i = 0; i < sizeof whole_ms / sizeof whole_ms[0]; i++) {
        CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, whole_ms[i] * 1000000LL), CANOPY_OK);
        CHECK_INT(time_of(rig.engine, PREVIEW), whole_ms[i] * 1000000LL);                       /* 48 frames per millisecond: exact */
    }
    for (i = 0; i < sizeof odd_ns / sizeof odd_ns[0]; i++) {
        CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, odd_ns[i]), CANOPY_OK);
        CHECK_INT(time_of(rig.engine, PREVIEW), ref_ns(ref_frame(odd_ns[i])));                  /* the nearest frame, halves up */
    }
    rig_close(&rig);
}

static void test_c_the_warning_names_the_nodes_that_feed_the_preview_and_are_not_realtime_safe(void)
{
    Rig rig;
    char text[400];
    int32_t length = -1;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.const");                       /* 1 -> 2.in, 7 (a file, safe) -> 2.gain, 2 -> left */
    rig_node(&rig, 2, "test.gain");
    rig_node(&rig, 3, "boundary_inlet");                   /* safe -> right */
    rig_node(&rig, 4, "test.const");                       /* 4 -> 5.a, 5 -> center */
    rig_node(&rig, 5, "test.sum");
    rig_node(&rig, 6, "test.const");                       /* connected to nothing: not upstream of any preview */
    rig_node(&rig, 7, "file_read");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_node(&rig, 51, "realtime_preview");                /* a second preview that only has safe nodes upstream */
    CHECK_INT(canopy_graph_set_string(rig.graph, 3, "name", "x"), CANOPY_OK);
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 7, "left", 2, "gain");
    rig_connect(&rig, 2, "out", PREVIEW, "left");
    rig_connect(&rig, 3, "out", PREVIEW, "right");
    rig_connect(&rig, 4, "out", 5, "a");
    rig_connect(&rig, 5, "out", PREVIEW, "center");
    rig_connect(&rig, 3, "out", 51, "left");
    rig_install(&rig);
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, text, sizeof text, &length), CANOPY_OK);
    CHECK(strcmp(text, "not realtime safe, so the sound may break up: test.const (node 1), test.gain (node 2), test.const (node 4), test.sum (node 5)") == 0);
    CHECK_INT(length, (int32_t)strlen(text));
    CHECK_INT(canopy_preview_warning(rig.engine, 51, text, sizeof text, &length), CANOPY_OK);
    CHECK_INT(length, 0);                                                              /* only safe nodes feed it: nothing to warn about */
    CHECK_INT(text[0], 0);
    rig_close(&rig);
}

static void test_c_the_warning_text_is_copied_with_the_usual_protocol_and_a_loop_does_not_hang_it(void)
{
    static const char FULL[] = "not realtime safe, so the sound may break up: test.gain (node 1), test.gain (node 2)";
    Rig rig;
    char text[200], cut[16];
    int32_t length = -1;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.gain");
    rig_node(&rig, 2, "test.gain");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", 2, "in");                  /* a loop between the two gains: allowed by the engine */
    rig_connect(&rig, 2, "out", 1, "in");
    rig_connect(&rig, 2, "out", PREVIEW, "left");
    rig_install(&rig);
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, text, sizeof text, &length), CANOPY_OK);
    CHECK(strcmp(text, FULL) == 0);
    CHECK_INT(length, (int32_t)strlen(FULL));
    memset(cut, 'x', sizeof cut);
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, cut, sizeof cut, &length), CANOPY_OK);
    CHECK_INT(length, (int32_t)strlen(FULL));                                          /* the full length, so that a caller can ask again */
    CHECK(strlen(cut) == sizeof cut - 1 && memcmp(cut, FULL, sizeof cut - 1) == 0);       /* cut, and NUL-terminated */
    length = -1;
    CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, NULL, 0, &length), CANOPY_OK);
    CHECK_INT(length, (int32_t)strlen(FULL));
    rig_close(&rig);
}

static void test_c_the_audio_backend_is_one_of_two_and_the_device_list_is_copied_with_the_usual_protocol(void)
{
    static const char NAME[] = "NULL Playback Device";
    Rig rig;
    char text[64], cut[5];
    int32_t length = -1;
    int64_t live;
    rig_open(&rig);
    CHECK_INT(canopy_engine_set_audio_backend(rig.engine, CANOPY_AUDIO_SYSTEM), CANOPY_OK);
    CHECK_INT(canopy_engine_set_audio_backend(rig.engine, CANOPY_AUDIO_NULL), CANOPY_OK);
    CHECK_INT(canopy_engine_set_audio_backend(rig.engine, 2), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_audio_backend(rig.engine, -1), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_audio_backend(NULL, CANOPY_AUDIO_NULL), CANOPY_ERR_ARGUMENT);
    live = canopy_alloc_live();
    CHECK_INT(canopy_engine_audio_devices(rig.engine, text, sizeof text, &length), CANOPY_OK);
    CHECK(strcmp(text, NAME) == 0);
    CHECK_INT(length, (int32_t)strlen(NAME));
    memset(cut, 'x', sizeof cut);
    CHECK_INT(canopy_engine_audio_devices(rig.engine, cut, sizeof cut, &length), CANOPY_OK);
    CHECK(strcmp(cut, "NULL") == 0);                                                 /* cut to the capacity, NUL-terminated */
    CHECK_INT(length, (int32_t)strlen(NAME));                                          /* the full length */
    length = -1;
    CHECK_INT(canopy_engine_audio_devices(rig.engine, NULL, 0, &length), CANOPY_OK);
    CHECK_INT(length, (int32_t)strlen(NAME));
    CHECK_INT(canopy_engine_audio_devices(rig.engine, NULL, 0, NULL), CANOPY_OK);
    CHECK_INT(canopy_engine_audio_devices(rig.engine, NULL, 4, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_audio_devices(rig.engine, text, -1, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_audio_devices(NULL, text, sizeof text, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_alloc_live(), live);                                              /* asking leaks nothing */
    CHECK_INT(canopy_engine_set_audio_backend(rig.engine, CANOPY_AUDIO_SYSTEM), CANOPY_OK);      /* the real system: whatever the machine has, as lines of text */
    {
        char all[4096];
        CHECK_INT(canopy_engine_audio_devices(rig.engine, all, sizeof all, &length), CANOPY_OK);
        CHECK(length >= 0 && length < (int32_t)sizeof all);
        CHECK(strstr(all, NAME) == NULL);                                              /* the null backend's device is not one of the machine's */
    }
    rig_close(&rig);
}

/* ---- with a device (the null backend) ---- */

static void test_c_play_moves_the_time_in_real_time_pause_stops_it_and_play_goes_on_from_there(void)
{
    Rig rig;
    const atomic_llong *calls;
    int64_t t_paused, t_resumed;
    constant_rig(&rig, 0.25);
    calls = counter_of(rig.engine, PREVIEW);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    CHECK_INT(time_of(rig.engine, PREVIEW), 0);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    CHECK(wait_for_time(rig.engine, PREVIEW, 100000000LL));                           /* 100 ms of audio has gone to the device */
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "pause"), CANOPY_OK);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    if (calls) {
        long long mark = atomic_load(calls);
        CHECK(wait_for_callbacks(calls, mark + 2));                                   /* a callback that began before the pause may still add its chunk: wait it out */
        t_paused = time_of(rig.engine, PREVIEW);
        mark = atomic_load(calls);
        CHECK(wait_for_callbacks(calls, mark + 4));                                   /* the device goes on (silence)... */
        CHECK_INT(time_of(rig.engine, PREVIEW), t_paused);                            /* ...and the time stands still */
        CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
        CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
        CHECK(wait_for_time(rig.engine, PREVIEW, t_paused + 60000000LL));
        t_resumed = time_of(rig.engine, PREVIEW);
        CHECK(t_resumed >= t_paused + 60000000LL);                                    /* it went on from where it was paused, not from zero */
        CHECK(t_resumed < t_paused + 4000000000LL);
    }
    CHECK_INT(canopy_preview_set_time(rig.engine, PREVIEW, 7000000000LL), CANOPY_OK);  /* a typed time, while playing */
    CHECK(wait_for_time(rig.engine, PREVIEW, 7000000000LL + 20000000LL));
    CHECK(time_of(rig.engine, PREVIEW) < 7000000000LL + 4000000000LL);
    rig_close(&rig);                                                                   /* the engine closes the device of a node that is still playing */
}

static void test_c_pressing_play_twice_opens_one_device_and_a_good_play_leaves_no_message(void)
{
    Rig rig;
    char message[100];
    int64_t live;
    constant_rig(&rig, 0.25);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    live = canopy_alloc_live();
    CHECK_INT(opens_of(rig.engine, PREVIEW), 1);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(opens_of(rig.engine, PREVIEW), 1);
    CHECK_INT(canopy_alloc_live(), live);                                              /* no second device, no second instance */
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strcmp(message, "") == 0);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "unknown action"), CANOPY_OK);  /* an action the node does not know is ignored */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 1);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    rig_close(&rig);
}

static CanopyGraph *constant_graph(double value, const char *device)
{
    CanopyGraph *graph = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(graph, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(graph, PREVIEW, "realtime_preview"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(graph, 1, "out", PREVIEW, "left"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(graph, 1, "value", value), CANOPY_OK);
    if (device) CHECK_INT(canopy_graph_set_string(graph, PREVIEW, "device", device), CANOPY_OK);
    return graph;
}

static void test_c_a_device_that_does_not_exist_falls_back_to_the_default_says_so_and_plays(void)
{
    Rig rig;
    CanopyGraph *good;
    char message[300];
    preview_rig(&rig);
    good = constant_graph(0.25, "NULL Playback Device");
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    CHECK_INT(canopy_graph_set_string(rig.graph, PREVIEW, "device", "No such device"), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);                                     /* "if that device is missing, the system default is used" */
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strstr(message, "No such device") != NULL);                                  /* and the node says which name it could not find */
    CHECK(strstr(message, "system default") != NULL);
    CHECK(wait_for_time(rig.engine, PREVIEW, 40000000LL));                             /* it really plays */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 1);
    CHECK_INT(canopy_engine_set_graph(rig.engine, good), CANOPY_OK);                   /* the setting now names a device that exists */
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);          /* play looks at the setting again: another device than the open one */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 2);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strcmp(message, "") == 0);                                                   /* a good play clears the note */
    canopy_graph_free(good);
    rig_close(&rig);
}

static void test_c_the_device_action_switches_to_the_device_the_setting_names_and_keeps_the_state(void)
{
    Rig rig;
    CanopyGraph *named, *missing;
    const atomic_llong *calls;
    char message[300];
    long long mark;
    constant_rig(&rig, 0.25);
    named = constant_graph(0.25, "NULL Playback Device");
    missing = constant_graph(0.25, "Gone");
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "device"), CANOPY_OK);        /* no device is open: nothing to switch */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 0);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(opens_of(rig.engine, PREVIEW), 1);
    calls = counter_of(rig.engine, PREVIEW);
    CHECK_INT(canopy_engine_set_graph(rig.engine, named), CANOPY_OK);
    CHECK_INT(opens_of(rig.engine, PREVIEW), 1);                                       /* changing the setting alone does nothing yet */
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "device"), CANOPY_OK);
    CHECK_INT(opens_of(rig.engine, PREVIEW), 2);                                       /* the action switches... */
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);                                     /* ...and it goes on playing */
    if (calls) {
        mark = atomic_load(calls);
        CHECK(wait_for_callbacks(calls, mark + 3));
    }
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "device"), CANOPY_OK);        /* the same device: nothing to do */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 2);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "pause"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, missing), CANOPY_OK);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "device"), CANOPY_OK);        /* switching while paused stays paused */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 3);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strstr(message, "Gone") != NULL);
    canopy_graph_free(named);
    canopy_graph_free(missing);
    rig_close(&rig);
}

static void test_c_a_device_that_stops_by_itself_pauses_the_node_says_so_and_play_starts_it_again(void)
{
    Rig rig;
    const atomic_llong *calls;
    char message[300];
    long long mark;
    int64_t t_stopped;
    ULONGLONG deadline;
    constant_rig(&rig, 0.25);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    calls = counter_of(rig.engine, PREVIEW);
    CHECK(calls && wait_for_callbacks(calls, 3));
    CHECK_INT(canopy_preview_stop_device(rig.engine, PREVIEW), CANOPY_OK);            /* as if it had been unplugged */
    deadline = GetTickCount64() + 5000;
    while (playing_of(rig.engine, PREVIEW) != 0 && GetTickCount64() < deadline) Sleep(1);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strstr(message, "stopped") != NULL);
    t_stopped = time_of(rig.engine, PREVIEW);
    mark = calls ? atomic_load(calls) : 0;
    Sleep(100);
    CHECK_INT(calls ? atomic_load(calls) : 0, mark);                                   /* the stopped device asks for nothing */
    CHECK_INT(time_of(rig.engine, PREVIEW), t_stopped);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);          /* play opens a device again */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 2);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strcmp(message, "") == 0);
    CHECK(wait_for_time(rig.engine, PREVIEW, t_stopped + 50000000LL));
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);          /* the new device is a good one: pressing play again does not open yet another */
    CHECK_INT(opens_of(rig.engine, PREVIEW), 2);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    rig_close(&rig);
}

static void test_c_deleting_the_preview_node_closes_its_device_once_the_audio_thread_has_moved_on(void)
{
    Rig rig;
    CanopyGraph *without;
    const atomic_llong *calls;
    ULONGLONG deadline;
    constant_rig(&rig, 0.25);
    without = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(without, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    calls = counter_of(rig.engine, PREVIEW);
    CHECK(calls && wait_for_callbacks(calls, 3));
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);
    (void)canopy_instance_inlet_at(rig.instance, 1, 0, 0);                             /* the host's instance moves on at once... */
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);                             /* ...the preview's own does when its next callback comes */
    deadline = GetTickCount64() + 5000;
    while (canopy_engine_service_count(rig.engine) != 0 && GetTickCount64() < deadline) {
        (void)canopy_engine_collect(rig.engine);                                       /* (what the editor does after an edit) */
        Sleep(1);
    }
    CHECK_INT(canopy_engine_service_count(rig.engine), 0);                             /* the node's resource went, with its device and instance */
    CHECK_INT(canopy_engine_node_count(rig.engine), 1);
    canopy_graph_free(without);
    rig_close(&rig);                                                                   /* (checks that the device left nothing behind) */
}

static void test_c_freeing_the_engine_closes_a_playing_preview_and_one_whose_device_has_stopped_behind_newer_graphs(void)
{
    Rig rig;
    CanopyGraph *second, *third;
    const atomic_llong *calls;
    ULONGLONG deadline;
    constant_rig(&rig, 0.25);
    second = constant_graph(0.5, NULL);
    third = constant_graph(0.75, NULL);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    calls = counter_of(rig.engine, PREVIEW);
    CHECK(calls && wait_for_callbacks(calls, 3));
    CHECK_INT(canopy_preview_stop_device(rig.engine, PREVIEW), CANOPY_OK);            /* its instance now stays behind: nobody queries it */
    deadline = GetTickCount64() + 5000;
    while (playing_of(rig.engine, PREVIEW) != 0 && GetTickCount64() < deadline) Sleep(1);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, third), CANOPY_OK);
    (void)canopy_instance_inlet_at(rig.instance, 1, 0, 0);
    CHECK(canopy_engine_collect(rig.engine) >= 3);                                     /* the old graphs are held for the preview's instance */
    canopy_graph_free(second);
    canopy_graph_free(third);
    rig_close(&rig);                                                                   /* frees the engine: devices and instances first, then the graphs they used */
}

/* two graphs that differ in a counter's tag: while the preview plays, each is run by the audio thread after it is installed */
static CanopyGraph *counter_graph(int tag)
{
    CanopyGraph *graph = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(graph, 1, "test.counter"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(graph, PREVIEW, "realtime_preview"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(graph, 1, "out", PREVIEW, "left"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(graph, 1, "tag", tag), CANOPY_OK);
    return graph;
}

static void test_c_graph_edits_installed_while_the_preview_plays_are_run_by_the_audio_thread_one_after_the_other(void)
{
    Rig rig;
    CanopyGraph *a, *b;
    const atomic_llong *calls;
    int i, stalled = 0;
    support_counters_reset();
    preview_rig(&rig);
    a = counter_graph(1);
    b = counter_graph(2);
    CHECK_INT(canopy_engine_set_graph(rig.engine, a), CANOPY_OK);
    rig.instance = canopy_engine_new_instance(rig.engine);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    calls = counter_of(rig.engine, PREVIEW);
    for (i = 0; i < 60 && calls; i++) {
        int tag = (i & 1) ? 1 : 2, before = support_counts[tag];
        ULONGLONG deadline = GetTickCount64() + 5000;
        CHECK_INT(canopy_engine_set_graph(rig.engine, (i & 1) ? a : b), CANOPY_OK);
        if (i % 7 == 0) (void)canopy_engine_collect(rig.engine);
        while (*(volatile int *)&support_counts[tag] == before && GetTickCount64() < deadline) Sleep(0);
        if (support_counts[tag] == before) {
            stalled = i + 1;
            break;
        }
    }
    CHECK_INT(stalled, 0);                                                              /* every installed graph was run by the audio thread */
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    canopy_graph_free(a);
    canopy_graph_free(b);
    rig_close(&rig);
}

static void test_c_running_out_of_memory_while_pressing_play_leaves_the_node_paused_with_a_message_and_leaks_nothing(void)
{
    Rig rig;
    char message[300];
    int k, failures = 0;
    constant_rig(&rig, 0.25);
    for (k = 0; k < 300; k++) {
        canopy_alloc_fail_after(k);
        CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);      /* an action cannot fail: it says what happened on the node */
        canopy_alloc_fail_after(-1);
        if (playing_of(rig.engine, PREVIEW) == 1) break;
        failures++;
        message_of(rig.engine, PREVIEW, message, sizeof message);
        CHECK(message[0] != '\0');                                                     /* "out of memory", or why the device could not be opened */
        CHECK_INT(canopy_engine_service_count(rig.engine), 0);                         /* nothing half made is left behind */
        CHECK_INT(opens_of(rig.engine, PREVIEW), 0);
    }
    CHECK(failures > 0);
    CHECK(k < 300);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strcmp(message, "") == 0);
    rig_close(&rig);                                                                   /* leaks nothing */
}

static void test_c_a_device_that_cannot_be_opened_leaves_the_node_paused_with_nothing_half_made_and_says_why(void)
{
    static const char *const SAYS[5] = {"forced failure after the context started", "the audio devices cannot be listed",
                                        "forced failure after the device was made", "the audio device cannot be started", "no audio system"};
    Rig rig;
    char message[300];
    int stage;
    constant_rig(&rig, 0.25);
    for (stage = 1; stage <= 5; stage++) {
        canopy_audio_force_failure(stage);
        CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);          /* a button cannot fail: it says what happened on the node */
        canopy_audio_force_failure(0);
        CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
        CHECK_INT(canopy_engine_service_count(rig.engine), 0);                             /* the instance made for the attempt is gone again */
        CHECK_INT(opens_of(rig.engine, PREVIEW), 0);
        message_of(rig.engine, PREVIEW, message, sizeof message);
        CHECK(strncmp(message, "cannot play: ", 13) == 0);
        CHECK(strstr(message, SAYS[stage - 1]) != NULL);                                  /* and the reason is the audio layer's own */
    }
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);              /* the next press, with a working audio system, plays... */
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strcmp(message, "") == 0);                                                       /* ...and the old complaint is gone */
    rig_close(&rig);
}

static void test_c_running_out_of_memory_while_switching_device_leaves_the_node_paused_with_a_message_and_leaks_nothing(void)
{
    Rig rig;
    CanopyGraph *named;
    char message[300];
    int k, failures = 0;
    constant_rig(&rig, 0.25);
    named = constant_graph(0.25, "NULL Playback Device");
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);          /* playing on the device the first graph names */
    for (k = 0; k < 300; k++) {
        /* each round the setting names the other device than the one that is open, so that the action really is a switch */
        CHECK_INT(canopy_engine_set_graph(rig.engine, (k & 1) ? rig.graph : named), CANOPY_OK);
        canopy_alloc_fail_after(k);
        CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "device"), CANOPY_OK);
        canopy_alloc_fail_after(-1);
        if (playing_of(rig.engine, PREVIEW) == 1) break;                               /* the switch got through */
        failures++;
        CHECK_INT(canopy_engine_service_count(rig.engine), 0);                         /* the old device is closed, the new one could not be opened */
        message_of(rig.engine, PREVIEW, message, sizeof message);
        CHECK(message[0] != '\0');
        CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);      /* the user presses Play again: a device of the new name */
        CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    }
    CHECK(failures > 0);
    CHECK(k < 300);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strcmp(message, "") == 0);
    canopy_graph_free(named);
    rig_close(&rig);
}

static void test_c_the_audio_thread_goes_on_while_others_hold_the_engines_locks(void)
{
    Rig rig;
    const atomic_llong *calls;
    long long mark;
    constant_rig(&rig, 0.25);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    calls = counter_of(rig.engine, PREVIEW);
    CHECK(calls && wait_for_callbacks(calls, 3));
    if (calls) {
        canopy_lock_exclusive(&rig.engine->lock);                                      /* as an install holds it */
        canopy_lock_exclusive(&rig.engine->retire_lock);
        canopy_lock_exclusive(&rig.engine->message_lock);
        mark = atomic_load(calls);
        CHECK(wait_for_callbacks(calls, mark + 5));                                    /* the audio thread keeps getting its audio... */
        canopy_unlock_exclusive(&rig.engine->message_lock);
        canopy_unlock_exclusive(&rig.engine->retire_lock);
        canopy_unlock_exclusive(&rig.engine->lock);
    }
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    rig_close(&rig);
}

static void test_c_the_audio_thread_allocates_nothing_while_playing(void)
{
    Rig rig;
    const atomic_llong *calls;
    long long mark;
    int64_t before;
    constant_rig(&rig, 0.25);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    calls = counter_of(rig.engine, PREVIEW);
    if (calls) {
        CHECK(wait_for_callbacks(calls, 5));
        before = canopy_alloc_total();
        mark = atomic_load(calls);
        CHECK(wait_for_callbacks(calls, mark + 15));
        CHECK_INT(canopy_alloc_total(), before);                                       /* nothing allocated, by us or by miniaudio, in 15 callbacks */
    }
    rig_close(&rig);
}

static void test_c_two_preview_nodes_play_on_devices_of_their_own_and_are_paused_and_moved_separately(void)
{
    Rig rig;
    const atomic_llong *first, *second;
    int64_t t_first;
    preview_rig(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_node(&rig, 51, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    rig_connect(&rig, 1, "out", 51, "right");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.25), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(canopy_engine_action(rig.engine, 51, "play"), CANOPY_OK);
    CHECK_INT(canopy_engine_service_count(rig.engine), 2);
    first = counter_of(rig.engine, PREVIEW);
    second = counter_of(rig.engine, 51);
    CHECK(first && second && wait_for_callbacks(first, 3) && wait_for_callbacks(second, 3));
    CHECK_INT(canopy_preview_set_time(rig.engine, 51, 3000000000LL), CANOPY_OK);
    CHECK(wait_for_time(rig.engine, 51, 3000000000LL + 40000000LL));
    CHECK(time_of(rig.engine, PREVIEW) < 3000000000LL);                                 /* the other one is not affected */
    CHECK_INT(canopy_engine_action(rig.engine, 51, "pause"), CANOPY_OK);
    CHECK_INT(playing_of(rig.engine, 51), 0);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    if (first && second) {
        long long mark = atomic_load(first);
        CHECK(wait_for_callbacks(first, mark + 4));
        CHECK(wait_for_callbacks(second, atomic_load(second) + 4));                    /* (both devices go on) */
        t_first = time_of(rig.engine, PREVIEW);
        CHECK(wait_for_time(rig.engine, PREVIEW, t_first + 40000000LL));               /* the first goes on, the second is paused */
    }
    rig_close(&rig);
}

typedef struct {
    CanopyEngine *engine;
    CanopyGraph *a, *b;
    volatile LONG stop, installs, bad;
} Installer;

static unsigned __stdcall installer_main(void *argument)
{
    Installer *worker = (Installer *)argument;
    int i = 0;
    while (!worker->stop) {
        if (canopy_engine_set_graph(worker->engine, (i++ & 1) ? worker->a : worker->b) != CANOPY_OK) InterlockedIncrement(&worker->bad);
        if (i % 4 == 0) (void)canopy_engine_collect(worker->engine);
        InterlockedIncrement(&worker->installs);
    }
    return 0;
}

static void test_c_buttons_pressed_while_another_thread_installs_graphs_neither_deadlock_nor_use_a_graph_that_was_freed(void)
{
    static const char *const ACTIONS[] = {"play", "device", "pause", "play", "device", "device", "pause", "play"};
    enum { ROUNDS = 160 };
    Rig rig;
    CanopyGraph *a, *b;
    Installer worker;
    HANDLE thread;
    int i, stuck = 0;
    preview_rig(&rig);
    a = constant_graph(0.25, NULL);
    b = constant_graph(0.5, "NULL Playback Device");                                   /* another device name: "device" and "play" switch devices all the time */
    CHECK_INT(canopy_engine_set_graph(rig.engine, a), CANOPY_OK);
    memset(&worker, 0, sizeof worker);
    worker.engine = rig.engine;
    worker.a = a;
    worker.b = b;
    thread = (HANDLE)_beginthreadex(NULL, 0, installer_main, &worker, 0, NULL);
    for (i = 0; i < ROUNDS; i++) {
        LONG before = worker.installs;
        ULONGLONG deadline = GetTickCount64() + 5000;
        char message[300];
        while (worker.installs == before && GetTickCount64() < deadline) Sleep(0);       /* the installer has gone on between two presses: they really interleave */
        if (worker.installs == before) {
            stuck = i + 1;
            break;
        }
        CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, ACTIONS[i % 8]), CANOPY_OK);
        if (i % 5 == 0) (void)canopy_preview_set_time(rig.engine, PREVIEW, (int64_t)i * 1000000LL);
        if (i % 7 == 0) message_of(rig.engine, PREVIEW, message, sizeof message);
    }
    InterlockedExchange(&worker.stop, 1);
    WaitForSingleObject(thread, INFINITE);
    CloseHandle(thread);
    CHECK_INT(stuck, 0);                                                                /* nothing waited forever */
    CHECK_INT(worker.bad, 0);                                                           /* and every install worked */
    CHECK(worker.installs > ROUNDS / 2);
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);                              /* the last press was a play: one device, one instance */
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    canopy_graph_free(a);
    canopy_graph_free(b);
    rig_close(&rig);
}

static void test_c_a_preview_whose_shared_resource_could_not_be_made_says_so_and_nothing_crashes(void)
{
    int k, failed_installs = 0, without_resource = 0;
    for (k = 0; k < 400 && without_resource == 0; k++) {
        Rig rig;
        CanopyGraph *graph;
        char message[300];
        int32_t status;
        preview_rig(&rig);
        graph = constant_graph(0.25, NULL);
        canopy_alloc_fail_once(k);                                                       /* this allocation of the install fails, and only this one */
        status = canopy_engine_set_graph(rig.engine, graph);
        canopy_alloc_fail_once(-1);
        if (status != CANOPY_OK) {
            failed_installs++;
            CHECK_INT(canopy_engine_node_count(rig.engine), 0);
        } else if (canopy_preview_set_time(rig.engine, PREVIEW, 5) == CANOPY_ERR_MEMORY) {      /* installed, but the node has no resource */
            int32_t playing = -1;
            int64_t t = -1;
            without_resource++;
            CHECK_INT(canopy_preview_state(rig.engine, PREVIEW, &playing, &t), CANOPY_OK);
            CHECK_INT(playing, 0);
            CHECK_INT(t, 0);
            CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
            CHECK_INT(playing_of(rig.engine, PREVIEW), 0);
            message_of(rig.engine, PREVIEW, message, sizeof message);
            CHECK(strcmp(message, "out of memory") == 0);
            CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "pause"), CANOPY_OK);
            CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "device"), CANOPY_OK);
            CHECK_INT(canopy_preview_warning(rig.engine, PREVIEW, NULL, 0, NULL), CANOPY_OK);
            CHECK_INT(canopy_preview_prepare(rig.engine, PREVIEW, 1), CANOPY_ERR_MEMORY);
            CHECK_INT(canopy_engine_service_count(rig.engine), 0);
        }
        canopy_graph_free(graph);
        rig_close(&rig);
    }
    CHECK(failed_installs > 0);
    CHECK_INT(without_resource, 1);                                                      /* there is an allocation whose failure leaves exactly this state */
}

static void test_c_a_device_name_that_is_far_too_long_is_cut_in_the_message_and_still_plays_on_the_default(void)
{
    Rig rig;
    char name[601], message[400];
    memset(name, 'x', 600);
    name[600] = '\0';
    preview_rig(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, PREVIEW, "realtime_preview");
    rig_connect(&rig, 1, "out", PREVIEW, "left");
    CHECK_INT(canopy_graph_set_string(rig.graph, PREVIEW, "device", name), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK_INT(strlen(message), CANOPY_MESSAGE_BYTES - 1);                                /* cut to what a message can hold */
    CHECK(strncmp(message, "audio device not found: xxx", 27) == 0);
    CHECK(wait_for_time(rig.engine, PREVIEW, 40000000LL));
    rig_close(&rig);
}

static CanopyEngine *window_engine;
static CanopyGraph *window_graph;
static int window_calls;

static void window_hook(void)                                                          /* another thread's install, at the worst moment */
{
    window_calls++;
    canopy_engine_test_action_window(NULL);
    CHECK_INT(canopy_engine_set_graph(window_engine, window_graph), CANOPY_OK);
}

static void test_c_a_graph_installed_while_a_button_waits_for_the_exclusive_lock_is_the_one_the_button_acts_on(void)
{
    Rig rig;
    CanopyGraph *without, *renamed;
    char message[300];
    constant_rig(&rig, 0.25);
    without = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(without, 1, "test.const"), CANOPY_OK);
    renamed = constant_graph(0.25, "A different device");
    window_engine = rig.engine;
    /* 1. in the moment between letting go of the shared lock and taking the exclusive one the node is deleted: the press finds no node */
    window_graph = without;
    window_calls = 0;
    canopy_engine_test_action_window(window_hook);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_ERR_NODE);
    CHECK_INT(window_calls, 1);
    CHECK_INT(canopy_engine_service_count(rig.engine), 0);                              /* no device was opened for a node that is not there */
    /* 2. the node is there again in the moment, with another device setting: the press acts on that node, with its settings */
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    window_graph = renamed;
    window_calls = 0;
    canopy_engine_test_action_window(window_hook);
    CHECK_INT(canopy_engine_action(rig.engine, PREVIEW, "play"), CANOPY_OK);
    CHECK_INT(window_calls, 1);
    canopy_engine_test_action_window(NULL);
    CHECK_INT(playing_of(rig.engine, PREVIEW), 1);
    message_of(rig.engine, PREVIEW, message, sizeof message);
    CHECK(strstr(message, "A different device") != NULL);
    canopy_graph_free(without);
    canopy_graph_free(renamed);
    rig_close(&rig);
}

void register_test_preview(void)
{
    RUN(test_c_the_preview_node_type_is_built_in_and_described_as_the_design_says);
    RUN(test_c_the_preview_sends_left_plus_center_to_the_left_channel_and_right_plus_center_to_the_right_channel_exactly);
    RUN(test_c_unconnected_preview_inlets_play_their_knobs);
    RUN(test_c_the_preview_clips_sums_beyond_full_scale_and_plays_nan_as_silence);
    RUN(test_c_the_preview_asks_the_graph_for_exactly_the_frames_it_is_about_to_play_and_the_time_moves_on_by_that_many);
    RUN(test_c_a_seek_during_a_callback_wins_over_the_advance);
    RUN(test_c_a_paused_preview_plays_silence_asks_the_graph_nothing_and_stands_still);
    RUN(test_c_a_callback_for_more_than_65536_frames_asks_in_chunks_that_tile_exactly);
    RUN(test_c_a_source_that_fails_is_silence_for_its_channel_only);
    RUN(test_c_a_deleted_preview_plays_silence_and_stands_still_and_comes_back_when_it_is_added_again);
    RUN(test_c_the_next_callback_runs_an_edited_graph);
    RUN(test_c_the_callback_allocates_nothing);
    RUN(test_c_times_at_the_ends_of_the_range_never_overflow);
    RUN(test_c_state_set_time_and_warning_refuse_what_is_not_a_preview_node_and_report_unknown_nodes);
    RUN(test_c_the_playback_time_is_set_exactly_for_whole_milliseconds_and_rounded_to_a_frame_otherwise);
    RUN(test_c_the_warning_names_the_nodes_that_feed_the_preview_and_are_not_realtime_safe);
    RUN(test_c_the_warning_text_is_copied_with_the_usual_protocol_and_a_loop_does_not_hang_it);
    RUN(test_c_the_audio_backend_is_one_of_two_and_the_device_list_is_copied_with_the_usual_protocol);
    RUN(test_c_play_moves_the_time_in_real_time_pause_stops_it_and_play_goes_on_from_there);
    RUN(test_c_pressing_play_twice_opens_one_device_and_a_good_play_leaves_no_message);
    RUN(test_c_a_device_that_does_not_exist_falls_back_to_the_default_says_so_and_plays);
    RUN(test_c_the_device_action_switches_to_the_device_the_setting_names_and_keeps_the_state);
    RUN(test_c_a_device_that_stops_by_itself_pauses_the_node_says_so_and_play_starts_it_again);
    RUN(test_c_deleting_the_preview_node_closes_its_device_once_the_audio_thread_has_moved_on);
    RUN(test_c_freeing_the_engine_closes_a_playing_preview_and_one_whose_device_has_stopped_behind_newer_graphs);
    RUN(test_c_graph_edits_installed_while_the_preview_plays_are_run_by_the_audio_thread_one_after_the_other);
    RUN(test_c_running_out_of_memory_while_pressing_play_leaves_the_node_paused_with_a_message_and_leaks_nothing);
    RUN(test_c_a_device_that_cannot_be_opened_leaves_the_node_paused_with_nothing_half_made_and_says_why);
    RUN(test_c_running_out_of_memory_while_switching_device_leaves_the_node_paused_with_a_message_and_leaks_nothing);
    RUN(test_c_the_audio_thread_goes_on_while_others_hold_the_engines_locks);
    RUN(test_c_the_audio_thread_allocates_nothing_while_playing);
    RUN(test_c_two_preview_nodes_play_on_devices_of_their_own_and_are_paused_and_moved_separately);
    RUN(test_c_a_graph_installed_while_a_button_waits_for_the_exclusive_lock_is_the_one_the_button_acts_on);
    RUN(test_c_buttons_pressed_while_another_thread_installs_graphs_neither_deadlock_nor_use_a_graph_that_was_freed);
    RUN(test_c_a_preview_whose_shared_resource_could_not_be_made_says_so_and_nothing_crashes);
    RUN(test_c_a_device_name_that_is_far_too_long_is_cut_in_the_message_and_still_plays_on_the_default);
}
