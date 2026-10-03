/* The FileReadNode (design sections 11 and 16): a .wav file held whole in memory, answering point and span queries on two outlets.
     Formats      PCM 8, 16, 24 and 32 bits and 32-bit float, read with dr_wav and converted to float32 (8-bit PCM is unsigned, as in WAV). Anything
                  else is refused with a message. Mono feeds both outlets; with more than two channels the first two are used.
     Time         Frame k of the file is at k / (the file's sample rate) seconds, the file starting at t = 0. A point query between two frames is
                  the linear interpolation of them (the position between them exact, as for the hidden filter); the file covers t = 0 to the time
                  of its last frame, and everything outside that is silence. A span query is the point query at each sample time of the span, so
                  a span denser or sparser than the file's own density is resampled by linear interpolation (decimating aliases: accepted).
     Loading      The path is the text setting `path` (absolute). The file is read when the node first appears in an installed graph and whenever
                  the action "open" is pressed (using the path of the installed graph), never otherwise. A new file replaces the old one with an
                  atomic pointer swap; the old samples go to canopy_ctx_retire(). A file that cannot be used leaves the old one in place and puts a
                  message on the node (canopy_ctx_set_message); a success clears the message and calls canopy_ctx_shared_changed(). Nothing is
                  loaded, allocated or freed by a query. */
#include <stdio.h>
#include <string.h>
#include "canopy_core.h"

#pragma warning(push, 0)
#pragma warning(disable: 4701 4703)          /* (a warning that is raised at the end of a function ignores the level)  */
#define DR_WAV_IMPLEMENTATION
#include "../third_party/dr_wav.h"
#pragma warning(pop)

typedef struct {
    int64_t frames;
    uint32_t rate;
    float *left, *right;                 /* inside `block`; the same array for a mono file */
    float *block;
} FileData;

typedef struct {
    _Atomic(FileData *) data;            /* NULL: no file (silence) */
} FileShared;

enum { SETTING_PATH = 0 };

/* ---- allocation for dr_wav: through canopy_alloc, so that the tests count and fail it ---- */

static void *wav_malloc(size_t size, void *user)
{
    (void)user;
    return canopy_alloc(size);
}

static void wav_free(void *block, void *user)
{
    (void)user;
    canopy_free(block);
}

static const drwav_allocation_callbacks WAV_ALLOCATION = {NULL, wav_malloc, NULL, wav_free};

static void data_release(void *block)
{
    FileData *data = (FileData *)block;
    canopy_free(data->block);
    canopy_free(data);
}

/* ---- loading ---- */

static int absolute_path(const char *path)
{
    return (path[0] && path[1] == ':') || (path[0] == '\\' && path[1] == '\\') || (path[0] == '/' && path[1] == '/');
}

/* Reads the file into *out. On failure returns 0 with the reason in `why`. */
static int load_file(const char *path, FileData **out, char *why, size_t why_size)
{
    wchar_t *wide = NULL;
    int wide_size;
    DWORD attributes;
    drwav wav;
    FileData *data = NULL;
    float *buffer = NULL;
    uint64_t frames, got = 0;
    uint32_t stored;
    int ok = 0, channels;
    *out = NULL;
    if (!absolute_path(path)) {
        snprintf(why, why_size, "the path must be absolute (version 1 has no relative paths): %s", path);
        return 0;
    }
    wide_size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (wide_size > 0) wide = (wchar_t *)canopy_alloc((size_t)wide_size * sizeof *wide);
    if (wide_size <= 0 || !wide || MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, wide_size) <= 0) {
        snprintf(why, why_size, wide_size <= 0 ? "the path is not valid text: %s" : "out of memory", path);
        canopy_free(wide);
        return 0;
    }
    attributes = GetFileAttributesW(wide);
    if (attributes == INVALID_FILE_ATTRIBUTES) {
        snprintf(why, why_size, "file not found: %s", path);
        goto done;
    }
    if (attributes & FILE_ATTRIBUTE_DIRECTORY) {
        snprintf(why, why_size, "not a file: %s", path);
        goto done;
    }
    if (!drwav_init_file_w(&wav, wide, &WAV_ALLOCATION)) {
        snprintf(why, why_size, "not a WAV file, or damaged: %s", path);
        goto done;
    }
    if (!((wav.translatedFormatTag == DR_WAVE_FORMAT_PCM && (wav.bitsPerSample == 8 || wav.bitsPerSample == 16 || wav.bitsPerSample == 24 ||
                                                              wav.bitsPerSample == 32)) ||
          (wav.translatedFormatTag == DR_WAVE_FORMAT_IEEE_FLOAT && wav.bitsPerSample == 32)) ||
        wav.channels < 1) {
        snprintf(why, why_size, "format not supported (format %u, %u bits, %u channels); accepted: PCM 8, 16, 24 and 32 bits and 32-bit float",
                 (unsigned)wav.translatedFormatTag, (unsigned)wav.bitsPerSample, (unsigned)wav.channels);
        drwav_uninit(&wav);
        goto done;
    }
    if (wav.sampleRate < 1 || wav.sampleRate > CANOPY_MAX_HELPER_RATE) {
        snprintf(why, why_size, "the sample rate %u Hz is not supported", (unsigned)wav.sampleRate);
        drwav_uninit(&wav);
        goto done;
    }
    channels = wav.channels;
    stored = channels == 1 ? 1u : 2u;
    frames = wav.totalPCMFrameCount;
    if (frames > (uint64_t)INT64_MAX / 16u) {
        snprintf(why, why_size, "the file is too long: %s", path);
        drwav_uninit(&wav);
        goto done;
    }
    {
        uint64_t chunk = 262144u / (uint64_t)channels;
        if (chunk < 1) chunk = 1;
        if (chunk > 4096) chunk = 4096;
        data = (FileData *)canopy_alloc(sizeof *data);
        if (data) data->block = (float *)canopy_alloc((size_t)((frames ? frames : 1) * stored) * sizeof(float));
        buffer = (float *)canopy_alloc((size_t)(chunk * (uint64_t)channels) * sizeof(float));
        if (!data || !data->block || !buffer) {
            snprintf(why, why_size, "out of memory loading %s", path);
            drwav_uninit(&wav);
            goto done;
        }
        data->left = data->block;
        data->right = stored == 2 ? data->block + frames : data->block;
        while (got < frames) {
            uint64_t want = frames - got < chunk ? frames - got : chunk, read = drwav_read_pcm_frames_f32(&wav, want, buffer), i;
            if (read == 0) break;
            for (i = 0; i < read; i++) {
                data->left[got + i] = buffer[i * (uint64_t)channels];
                if (stored == 2) data->right[got + i] = buffer[i * (uint64_t)channels + 1];
            }
            got += read;
        }
        data->frames = (int64_t)got;                     /* (a file shorter than its header says is used as far as it goes) */
        data->rate = wav.sampleRate;
    }
    drwav_uninit(&wav);
    ok = 1;
done:
    canopy_free(wide);
    canopy_free(buffer);
    if (ok) {
        *out = data;
    } else if (data) {
        data_release(data);
    }
    return ok;
}

/* ---- the node ---- */

static void *file_create_shared(CanopyCtx *ctx)
{
    FileShared *shared = (FileShared *)canopy_alloc(sizeof *shared);
    const char *path = canopy_ctx_string(ctx, SETTING_PATH);
    if (shared && path[0]) {
        FileData *data;
        char why[600];
        if (load_file(path, &data, why, sizeof why)) atomic_store(&shared->data, data);
        else canopy_ctx_set_message(ctx, why);           /* the node is silent and flagged */
    }
    return shared;
}

static void file_destroy_shared(CanopyCtx *ctx, void *shared_pointer)
{
    FileShared *shared = (FileShared *)shared_pointer;
    FileData *data = atomic_load(&shared->data);
    (void)ctx;
    if (data) data_release(data);                        /* (no graph has the node any more: no query can be reading it) */
    canopy_free(shared);
}

static void file_action(CanopyCtx *ctx, const char *action)
{
    FileShared *shared = (FileShared *)canopy_ctx_shared(ctx);
    const char *path = canopy_ctx_string(ctx, SETTING_PATH);
    FileData *fresh, *old;
    char why[600];
    if (strcmp(action, "open") != 0) return;
    if (!shared) {
        canopy_ctx_set_message(ctx, "out of memory");
        return;
    }
    if (path[0] == '\0') {
        canopy_ctx_set_message(ctx, "no file chosen");
        return;
    }
    if (!load_file(path, &fresh, why, sizeof why)) {
        canopy_ctx_set_message(ctx, why);                /* the old file stays */
        return;
    }
    old = atomic_exchange(&shared->data, fresh);
    canopy_ctx_set_message(ctx, "");
    canopy_ctx_shared_changed(ctx);
    if (old) canopy_ctx_retire(ctx, old, data_release);
}

/* The value of one channel at time t (0 outside the file). */
static float sample_at(const FileData *data, int right, int64_t t)
{
    const float *samples = right ? data->right : data->left;
    int64_t k = 0;
    double fraction = 0.0, a, b;
    if (data->frames == 0 || canopy_ns_to_frame_fraction(t, data->rate, &k, &fraction) != CANOPY_OK) return 0.0f;
    if (k < 0 || k > data->frames - 1) return 0.0f;
    if (k == data->frames - 1) return fraction == 0.0 ? samples[k] : 0.0f;
    a = (double)samples[k];
    b = (double)samples[k + 1];
    return (float)(a + fraction * (b - a));
}

static float file_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    FileShared *shared = (FileShared *)canopy_ctx_shared(ctx);
    FileData *data = shared ? atomic_load(&shared->data) : NULL;
    return data ? sample_at(data, outlet == 1, t) : 0.0f;
}

static int32_t file_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    FileShared *shared = (FileShared *)canopy_ctx_shared(ctx);
    FileData *data = shared ? atomic_load(&shared->data) : NULL;       /* one file for the whole span */
    CanopySpanPlan plan;
    int64_t i;
    int32_t status = canopy_span_plan(t0, t1, n, &plan);
    if (status != CANOPY_OK) return status;
    for (i = 0; i < n; i++) out[i] = data ? sample_at(data, outlet == 1, canopy_span_plan_time(&plan, i)) : 0.0f;
    return CANOPY_OK;
}

static const CanopyOutletDesc FILE_OUTLETS[] = {{"left", "Left"}, {"right", "Right"}};
static const CanopySettingDesc FILE_SETTINGS[] = {{"path", CANOPY_SETTING_PATH, 0, 0.0, "", 0, NULL}};
static const CanopyWidgetDesc FILE_WIDGETS[] = {{CANOPY_WIDGET_BUTTON, "Open...", NULL, "open", 0, NULL}};

int32_t canopy_fileread_register_type(CanopyRegistry *registry)
{
    CanopyNodeType type;
    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = (uint32_t)sizeof type;
    type.key = "file_read";
    type.name = "File read";
    type.type_version = 1;
    type.flags = CANOPY_FLAG_REALTIME_SAFE;
    type.n_outlets = 2; type.outlets = FILE_OUTLETS;
    type.n_settings = 1; type.settings = FILE_SETTINGS;
    type.n_widgets = 1; type.widgets = FILE_WIDGETS;
    type.handlers.create_shared = file_create_shared;
    type.handlers.destroy_shared = file_destroy_shared;
    type.handlers.query_at = file_at;
    type.handlers.query_span = file_span;
    type.handlers.on_action = file_action;
    return canopy_registry_register_builtin(registry, &type);
}
