/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Tests: broken and hostile WAV files (plan step 13). The file node reads a file with dr_wav, which the library does not control, so what a file
   node does with damaged input is checked by throwing a lot of it at it: 11 valid files (PCM at 8, 16, 24 and 32 bits, 32-bit float, mono, stereo,
   three and six channels, and the extensible layout) are each damaged many times in one of 12 ways (flipped header bytes, header fields set to the edges of
   their range, truncation, extra and reordered chunks, a data size that claims too much or too little, a changed magic, random garbage), written to a
   file, and opened by pressing the node's button; then the node is queried through guarded buffers. Whatever the file, the node may refuse it (with a
   message) or play it, but it must not crash, write outside a buffer, leak, or answer a query with anything but a full span. Under the debug heap and
   AddressSanitizer a bad read or write inside dr_wav or the loader is reported at the line. The unmodified files are loaded first, to be sure the checks
   see real data, and so are the same files with other chunks put before and after the data, as real programs write them. CANOPY_FUZZ_ITERATIONS sets how
   many damaged files each valid one gets (100 by default; a soak uses many more). */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "support.h"

/* ---- a small random generator (xorshift64*), so that a failure can be repeated ---- */

static uint64_t rng_state = 0x5EED5EED12345ULL;

static uint64_t rng_next(void)
{
    rng_state ^= rng_state >> 12;
    rng_state ^= rng_state << 25;
    rng_state ^= rng_state >> 27;
    return rng_state * 0x2545F4914F6CDD1DULL;
}

static uint32_t below(uint32_t n)
{
    return n ? (uint32_t)(rng_next() >> 33) % n : 0;
}

/* ---- the bytes of a file ---- */

typedef struct {
    unsigned char *data;
    size_t size, capacity;
} Bytes;

static void bytes_put(Bytes *b, const void *source, size_t n)
{
    if (b->size + n > b->capacity) {
        b->capacity = (b->size + n) * 2 + 64;
        b->data = (unsigned char *)realloc(b->data, b->capacity);
    }
    memcpy(b->data + b->size, source, n);
    b->size += n;
}

static void put16(Bytes *b, uint32_t v)
{
    unsigned char x[2] = {(unsigned char)v, (unsigned char)(v >> 8)};
    bytes_put(b, x, 2);
}

static void put32(Bytes *b, uint32_t v)
{
    unsigned char x[4] = {(unsigned char)v, (unsigned char)(v >> 8), (unsigned char)(v >> 16), (unsigned char)(v >> 24)};
    bytes_put(b, x, 4);
}

static void poke32(Bytes *b, size_t offset, uint32_t v)
{
    if (offset + 4 <= b->size) {
        b->data[offset] = (unsigned char)v;
        b->data[offset + 1] = (unsigned char)(v >> 8);
        b->data[offset + 2] = (unsigned char)(v >> 16);
        b->data[offset + 3] = (unsigned char)(v >> 24);
    }
}

typedef struct {
    const char *name;
    int tag, channels, bits, rate, extensible, frames;
} Base;

static const Base BASES[] = {
    {"PCM 8-bit mono", 1, 1, 8, 8000, 0, 700},
    {"PCM 16-bit mono", 1, 1, 16, 44100, 0, 900},
    {"PCM 16-bit stereo", 1, 2, 16, 48000, 0, 600},
    {"PCM 24-bit stereo", 1, 2, 24, 22050, 0, 500},
    {"PCM 32-bit stereo", 1, 2, 32, 96000, 0, 400},
    {"float 32-bit mono", 3, 1, 32, 8000, 0, 600},
    {"float 32-bit stereo", 3, 2, 32, 48000, 0, 400},
    {"PCM 16-bit, three channels", 1, 3, 16, 16000, 0, 300},
    {"PCM 16-bit, six channels", 1, 6, 16, 48000, 0, 200},
    {"extensible PCM 24-bit stereo", 1, 2, 24, 48000, 1, 400},
    {"extensible float 32-bit stereo", 3, 2, 32, 48000, 1, 400},
};
#define BASE_COUNT ((int)(sizeof BASES / sizeof BASES[0]))

/* The integer a sample of the valid files holds (the frame i, channel c), before it is stored at the file's bit depth. */
static int sample_step(int i, int c)
{
    return (i * 31 + c * 17) % 255 - 127;                       /* -127 .. 127 */
}

static float expected_value(const Base *base, int i, int c)
{
    int step = sample_step(i, c);
    switch (base->bits) {
    case 8: return (float)((double)(step + 127) / 255.0 * 2.0 - 1.0);       /* 8-bit PCM is unsigned: 0..255 maps to -1..1 (dr_wav's rule) */
    case 16: return (float)((double)(step * 250) / 32768.0);
    case 24: return (float)((double)(step * 60000) / 8388608.0);
    default: return base->tag == 3 ? (float)step / 127.0f : (float)((double)((int64_t)step * 16000000) / 2147483648.0);
    }
}

static void build_base(Bytes *b, const Base *base)
{
    int i, c, bytes = base->bits / 8;
    uint32_t data_bytes = (uint32_t)(base->frames * base->channels * bytes);
    uint32_t fmt_size = base->extensible ? 40u : 16u;
    unsigned char guid[16] = {0, 0, 0, 0, 0x00, 0x00, 0x10, 0x00, 0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71};      /* the sub-format: the format tag, then Microsoft's fixed tail */
    b->size = 0;
    guid[0] = (unsigned char)base->tag;
    bytes_put(b, "RIFF", 4);
    put32(b, 4 + (8 + fmt_size) + (8 + data_bytes));
    bytes_put(b, "WAVEfmt ", 8);
    put32(b, fmt_size);
    put16(b, base->extensible ? 0xFFFEu : (uint32_t)base->tag);
    put16(b, (uint32_t)base->channels);
    put32(b, (uint32_t)base->rate);
    put32(b, (uint32_t)(base->rate * base->channels * bytes));
    put16(b, (uint32_t)(base->channels * bytes));
    put16(b, (uint32_t)base->bits);
    if (base->extensible) {
        put16(b, 22);                                           /* cbSize: what follows */
        put16(b, (uint32_t)base->bits);                         /* valid bits per sample */
        put32(b, 3);                                            /* the channel mask */
        bytes_put(b, guid, 16);
    }
    bytes_put(b, "data", 4);
    put32(b, data_bytes);
    for (i = 0; i < base->frames; i++)
        for (c = 0; c < base->channels; c++) {
            int step = sample_step(i, c);
            if (base->bits == 8) {
                unsigned char v = (unsigned char)(step + 127);
                bytes_put(b, &v, 1);
            } else if (base->bits == 16) {
                put16(b, (uint32_t)(int16_t)(step * 250));
            } else if (base->bits == 24) {
                int32_t v = step * 60000;
                unsigned char top = (unsigned char)(v >> 16);
                put16(b, (uint32_t)v & 0xFFFFu);
                bytes_put(b, &top, 1);
            } else if (base->tag == 3) {
                float v = (float)step / 127.0f;
                bytes_put(b, &v, 4);
            } else {
                put32(b, (uint32_t)(int32_t)(step * 16000000));
            }
        }
}

/* ---- damage ---- */

static const uint32_t EDGES[] = {0, 1, 2, 3, 7, 8, 15, 16, 255, 256, 65535, 65536, 0x7FFFFFFFu, 0x80000000u, 0xFFFFFFFEu, 0xFFFFFFFFu};
#define EDGE_COUNT ((int)(sizeof EDGES / sizeof EDGES[0]))

static size_t find_tag(const Bytes *b, const char *tag)
{
    size_t i;
    for (i = 0; i + 4 <= b->size; i++)
        if (memcmp(b->data + i, tag, 4) == 0) return i;
    return b->size;
}

static const char *KINDS[] = {"flipped header bytes", "a header field at an edge", "truncated", "an extra chunk before the data", "a chunk tag changed",
                              "format fields at an edge", "a data size that claims too much or too little", "garbage in the samples", "pure garbage",
                              "the RIFF size changed", "another magic", "the extensible fields changed"};
#define KIND_COUNT ((int)(sizeof KINDS / sizeof KINDS[0]))

/* (Every random number is drawn in a statement of its own: the order in which a call's arguments are evaluated is not specified, and a fixed seed must
   give the same files in every build.) */
static void damage(Bytes *b, int kind)
{
    size_t i, at;
    int k;
    switch (kind) {
    case 0:                                                      /* a few header bytes flipped */
        for (k = 1 + (int)below(4); k > 0; k--) {
            size_t where = below((uint32_t)(b->size < 128 ? b->size : 128));
            b->data[where] = (unsigned char)rng_next();
        }
        break;
    case 1: {                                                    /* a 32-bit field somewhere in the header set to an edge value */
        size_t where = (size_t)below(30) * 4;
        uint32_t edge = EDGES[below(EDGE_COUNT)];
        poke32(b, where, edge);
        break;
    }
    case 2:                                                      /* cut off anywhere */
        b->size = below((uint32_t)b->size + 1);
        break;
    case 3: {                                                    /* a chunk of random size and content in front of the data */
        Bytes extra = {0};
        uint32_t claimed = below(4) == 0 ? EDGES[below(EDGE_COUNT)] : below(100), real = below(60);
        at = find_tag(b, "data");
        bytes_put(&extra, below(2) ? "LIST" : "junk", 4);
        put32(&extra, claimed);
        for (i = 0; i < real; i++) {
            unsigned char v = (unsigned char)rng_next();
            bytes_put(&extra, &v, 1);
        }
        if (at <= b->size) {
            Bytes joined = {0};
            bytes_put(&joined, b->data, at);
            bytes_put(&joined, extra.data, extra.size);
            bytes_put(&joined, b->data + at, b->size - at);
            free(b->data);
            *b = joined;
        }
        free(extra.data);
        break;
    }
    case 4: {                                                    /* a chunk tag spoiled: fmt or data not found, or found twice */
        uint32_t which = below(2), byte = below(4), bit = below(8);
        at = which ? find_tag(b, "fmt ") : find_tag(b, "data");
        if (at < b->size) b->data[at + byte] ^= (unsigned char)(1u << bit);
        break;
    }
    case 5: {                                                    /* the format fields: tag, channels, rate, bytes per second, block align, bits */
        uint32_t field = below(6), narrow = below(2), edge = EDGES[below(EDGE_COUNT)];
        at = 20 + (size_t)field * (narrow ? 2u : 4u);
        poke32(b, at & ~(size_t)1, edge);
        break;
    }
    case 6: {                                                    /* the size of the data chunk */
        uint32_t doubled = below(3) == 0, edge = EDGES[below(EDGE_COUNT)];
        at = find_tag(b, "data");
        if (at < b->size) poke32(b, at + 4, doubled ? (uint32_t)b->size * 2u : edge);
        break;
    }
    case 7:                                                      /* garbage in the samples: the file must still load */
        at = find_tag(b, "data") + 8;
        for (k = 1 + (int)below(40); k > 0 && at < b->size; k--) {
            size_t where = at + below((uint32_t)(b->size - at));
            b->data[where] = (unsigned char)rng_next();
        }
        break;
    case 8: {                                                    /* nothing like a WAV file (sometimes with the start of one) */
        uint32_t keep_the_start;
        b->size = below(300);
        for (i = 0; i < b->size; i++) b->data[i] = (unsigned char)rng_next();
        keep_the_start = below(2);
        if (b->size >= 12 && keep_the_start) {
            memcpy(b->data, "RIFF", 4);
            memcpy(b->data + 8, "WAVE", 4);
        }
        break;
    }
    case 9: {                                                    /* the size in the RIFF header */
        uint32_t edge = EDGES[below(EDGE_COUNT)];
        poke32(b, 4, edge);
        break;
    }
    case 10: {                                                   /* a magic dr_wav knows other layouts for: RF64, RIFX (big endian), Wave64, a lower case riff */
        static const char *MAGIC[] = {"RF64", "RIFX", "riff", "RIFF", "W64 ", "RIFF"};
        uint32_t magic = below(6), change_the_form = below(2), which_form = below(2);
        memcpy(b->data, MAGIC[magic], 4);
        if (change_the_form) memcpy(b->data + 8, which_form ? "WAVX" : "wave", 4);
        break;
    }
    default: {                                                   /* the extensible part: size, valid bits, mask, the sub-format GUID */
        uint32_t where = below(22);
        unsigned char value = (unsigned char)rng_next();
        at = 36 + (size_t)where;
        if (at < b->size) b->data[at] = value;
        break;
    }
    }
}

/* ---- the rig ---- */

static char fuzz_path[MAX_PATH + 64];

static int write_file(const Bytes *b)
{
    FILE *file = fopen(fuzz_path, "wb");
    if (!file) return 0;
    if (b->size) fwrite(b->data, 1, b->size, file);
    fclose(file);
    return 1;
}

/* file_read (1) -> sink (100): left to in0, right to in1 */
static void file_rig(Rig *rig)
{
    rig_open(rig);
    rig_node(rig, 1, "file_read");
    rig_node(rig, 100, "test.sink");
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "path", fuzz_path), CANOPY_OK);
    rig_connect(rig, 1, "left", 100, "in0");
    rig_connect(rig, 1, "right", 100, "in1");
    rig_install(rig);
}

static int problems;
#define PROBLEM(...) do { ctest_current_failed = 1; if (problems++ < 10) { printf("    "); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* Asks the node for spans and points of every kind through guarded buffers. Whatever file it holds, every span must be a full one. */
static void query_everything(CanopyInstance *instance, const char *what)
{
    static const int64_t SPANS[][2] = {{0, 1000000000LL}, {-500000000LL, 5000000000LL}, {2000000000LL, 0}, {123456789LL, 123456789LL},
                                       {4000000000000000000LL, 4000000000000100000LL}, {INT64_MIN / 2, INT64_MAX / 2}};
    static const int64_t COUNTS[] = {1, 64, 1000};
    int s, c, inlet;
    float point;
    for (s = 0; s < (int)(sizeof SPANS / sizeof SPANS[0]); s++)
        for (c = 0; c < 3; c++)
            for (inlet = 0; inlet < 2; inlet++) {
                Guarded g = guarded_new(COUNTS[c]);
                int32_t status = canopy_instance_inlet_span(instance, 100, inlet, SPANS[s][0], SPANS[s][1], COUNTS[c], g.data);
                if (status != CANOPY_OK) PROBLEM("%s: a span query failed with status %d", what, status);
                if (!guarded_guards_intact(&g)) PROBLEM("%s: a span query wrote outside its buffer", what);
                if (guarded_unwritten(&g) != 0) PROBLEM("%s: a span query left %lld floats unwritten", what, (long long)guarded_unwritten(&g));
                guarded_free(&g);
            }
    for (inlet = 0; inlet < 2; inlet++) {
        int64_t t;
        for (t = -1; t <= 5000000000LL; t = t < 0 ? 0 : (t == 0 ? 1 : t * 1000))
            if (canopy_instance_inlet_at(instance, 100, inlet, t, &point) != CANOPY_OK) PROBLEM("%s: a point query at %lld failed", what, (long long)t);
    }
}

/* The message of the file node (empty for a file that loaded). */
static int message_length(CanopyEngine *engine)
{
    char buffer[8];
    int32_t length = -1;
    CHECK_INT(canopy_engine_node_message(engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    return length;
}

static void test_c_every_valid_file_loads_and_gives_its_first_samples_exactly(void)
{
    int b;
    Bytes bytes = {0};
    problems = 0;
    for (b = 0; b < BASE_COUNT; b++) {
        Rig rig;
        float left = 9.0f, right = 9.0f;
        build_base(&bytes, &BASES[b]);
        CHECK(write_file(&bytes));
        file_rig(&rig);
        if (message_length(rig.engine) != 0) PROBLEM("%s: the valid file was refused", BASES[b].name);
        CHECK_INT(canopy_instance_inlet_at(rig.instance, 100, 0, 0, &left), CANOPY_OK);
        CHECK_INT(canopy_instance_inlet_at(rig.instance, 100, 1, 0, &right), CANOPY_OK);
        {
            float want_left = expected_value(&BASES[b], 0, 0), want_right = expected_value(&BASES[b], 0, BASES[b].channels > 1 ? 1 : 0);
            if (fabsf(left - want_left) > 1e-6f)                     /* (dr_wav converts 8 and 32 bits in float: a tolerance; this only shows that the file was read) */
                PROBLEM("%s: the first left sample is %.9g, expected %.9g", BASES[b].name, (double)left, (double)want_left);
            if (fabsf(right - want_right) > 1e-6f)
                PROBLEM("%s: the first right sample is %.9g, expected %.9g", BASES[b].name, (double)right, (double)want_right);
        }
        query_everything(rig.instance, BASES[b].name);
        rig_close(&rig);
    }
    free(bytes.data);
    remove(fuzz_path);
}

/* A whole chunk (tag, size, content, and a pad byte if the size is odd) put into the file at `at`. */
static void splice_chunk(Bytes *b, size_t at, const char *tag, uint32_t size)
{
    Bytes chunk = {0}, joined = {0};
    uint32_t i;
    bytes_put(&chunk, tag, 4);
    put32(&chunk, size);
    for (i = 0; i < size + (size & 1u); i++) {
        unsigned char v = (unsigned char)(i * 7 + 3);
        bytes_put(&chunk, &v, 1);
    }
    bytes_put(&joined, b->data, at);
    bytes_put(&joined, chunk.data, chunk.size);
    bytes_put(&joined, b->data + at, b->size - at);
    poke32(&joined, 4, (uint32_t)(joined.size - 8));              /* the RIFF size, kept right */
    free(b->data);
    *b = joined;
    free(chunk.data);
}

/* Files as real programs write them: a LIST chunk, a fact chunk, a chunk of odd size, before the data; another after it. They are valid, so each must load,
   and give the same samples as the file without them. */
static void test_c_valid_files_with_other_chunks_before_and_after_the_data_load_like_the_plain_file(void)
{
    static const struct { const char *tag; uint32_t size; int after; const char *what; } EXTRAS[] = {
        {"LIST", 26, 0, "a LIST chunk before the data"}, {"fact", 4, 0, "a fact chunk before the data"}, {"junk", 5, 0, "an odd-sized chunk before the data"},
        {"LIST", 40, 1, "a LIST chunk after the data"}, {"cue ", 7, 1, "an odd-sized chunk after the data"},
    };
    int b, e;
    Bytes bytes = {0};
    problems = 0;
    for (b = 0; b < BASE_COUNT; b++)
        for (e = 0; e < (int)(sizeof EXTRAS / sizeof EXTRAS[0]); e++) {
            Rig rig;
            float left = 9.0f, right = 9.0f, want_left = expected_value(&BASES[b], 0, 0);
            float want_right = expected_value(&BASES[b], 0, BASES[b].channels > 1 ? 1 : 0);
            build_base(&bytes, &BASES[b]);
            splice_chunk(&bytes, EXTRAS[e].after ? bytes.size : find_tag(&bytes, "data"), EXTRAS[e].tag, EXTRAS[e].size);
            CHECK(write_file(&bytes));
            file_rig(&rig);
            if (message_length(rig.engine) != 0) PROBLEM("%s with %s: the file was refused", BASES[b].name, EXTRAS[e].what);
            CHECK_INT(canopy_instance_inlet_at(rig.instance, 100, 0, 0, &left), CANOPY_OK);
            CHECK_INT(canopy_instance_inlet_at(rig.instance, 100, 1, 0, &right), CANOPY_OK);
            if (fabsf(left - want_left) > 1e-6f || fabsf(right - want_right) > 1e-6f)
                PROBLEM("%s with %s: the first samples are %.9g and %.9g, expected %.9g and %.9g", BASES[b].name, EXTRAS[e].what, (double)left, (double)right, (double)want_left, (double)want_right);
            rig_close(&rig);
        }
    free(bytes.data);
    remove(fuzz_path);
}

static void test_c_damaged_files_are_refused_or_played_and_never_crash_overrun_or_leak(void)
{
    const char *text = getenv("CANOPY_FUZZ_ITERATIONS");
    int iterations = text && atoi(text) > 0 ? atoi(text) : 100, b, i, loaded = 0, refused = 0, fresh_loaded = 0;
    int per_kind_loaded[KIND_COUNT] = {0}, per_kind_refused[KIND_COUNT] = {0};
    Bytes base = {0}, mutant = {0};
    Rig rig;
    problems = 0;
    rng_state = 0x5EED5EED12345ULL;
    for (b = 0; b < BASE_COUNT; b++) {
        build_base(&base, &BASES[b]);
        CHECK(write_file(&base));
        file_rig(&rig);
        for (i = 0; i < iterations; i++) {
            int kind = i % KIND_COUNT, was_empty;
            char what[160];
            mutant.size = 0;
            bytes_put(&mutant, base.data, base.size);
            damage(&mutant, kind);
            snprintf(what, sizeof what, "%s damaged by %s (round %d)", BASES[b].name, KINDS[kind], i);
            if (!write_file(&mutant)) {
                PROBLEM("%s: the file could not be written", what);
                continue;
            }
            CHECK_INT(canopy_engine_action(rig.engine, 1, "open"), CANOPY_OK);
            was_empty = message_length(rig.engine) == 0;
            if (was_empty) loaded++, per_kind_loaded[kind]++; else refused++, per_kind_refused[kind]++;
            if (getenv("CANOPY_FUZZ_TRACE")) {                   /* one line per file, to compare two runs (builds) of the same seed */
                char message[300];
                int32_t length = 0;
                message[0] = '\0';
                (void)canopy_engine_node_message(rig.engine, 1, message, sizeof message, &length);
                printf("fuzz %d %d %s %u %s\n", b, i, was_empty ? "loaded" : "refused", (unsigned)mutant.size, message);
            }
            query_everything(rig.instance, what);
            if (i % 40 == 39) {                                  /* now and then the file is read by a node that is new, as when a graph is loaded */
                Rig second;
                file_rig(&second);
                if (message_length(second.engine) == 0) fresh_loaded++;
                query_everything(second.instance, what);
                rig_close(&second);
            }
            if (problems > 10) break;
        }
        CHECK_HEAP();
        rig_close(&rig);
        if (problems > 10) break;
    }
    printf("wav fuzz: %d damaged files, %d loaded and %d refused (%d read by a new node as they were)\n", loaded + refused, loaded, refused, fresh_loaded);
    if (getenv("CANOPY_FUZZ_VERBOSE"))
        for (i = 0; i < KIND_COUNT; i++) printf("wav fuzz: %-48s %5d loaded %5d refused\n", KINDS[i], per_kind_loaded[i], per_kind_refused[i]);
    CHECK(loaded > (loaded + refused) / 8);                      /* the damage was neither all fatal... */
    CHECK(refused > (loaded + refused) / 8);                     /* ...nor all harmless: the fuzz reaches both the loader and the refusals */
    CHECK(per_kind_loaded[7] > 0 && per_kind_refused[8] > 0);    /* garbage in the samples loads; pure garbage is refused */
    free(base.data);
    free(mutant.data);
    remove(fuzz_path);
}

void register_test_wavfuzz(void)
{
    DWORD n = GetTempPathA(MAX_PATH, fuzz_path);
    snprintf(fuzz_path + n, 64, "canopy_wavfuzz_%lu.wav", (unsigned long)GetCurrentProcessId());
    RUN(test_c_every_valid_file_loads_and_gives_its_first_samples_exactly);
    RUN(test_c_valid_files_with_other_chunks_before_and_after_the_data_load_like_the_plain_file);
    RUN(test_c_damaged_files_are_refused_or_played_and_never_crash_overrun_or_leak);
}
