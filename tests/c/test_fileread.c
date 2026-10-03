/* Tests: the FileReadNode's life with other threads and with a failing allocator: replacing the file while three threads read it, running out of
   memory while loading, the stamp downstream, and that a query allocates nothing. (Which values it answers, for every file format, is checked
   against an independent model in tests/python/test_fileread.py.) */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <process.h>
#include "support.h"

/* A WAV file of 32-bit floats whose every sample (both channels) is `value`. */
static void write_constant_wav(const char *path, float value, int frames)
{
    FILE *file = fopen(path, "wb");
    uint32_t data_bytes = (uint32_t)frames * 8u, rate = 1000, riff = 36u + data_bytes, fmt = 16, block_rate = rate * 8u;
    uint16_t tag = 3, channels = 2, block = 8, bits = 32;
    int i;
    CHECK(file != NULL);
    if (!file) return;
    fwrite("RIFF", 1, 4, file); fwrite(&riff, 4, 1, file); fwrite("WAVEfmt ", 1, 8, file); fwrite(&fmt, 4, 1, file);
    fwrite(&tag, 2, 1, file); fwrite(&channels, 2, 1, file); fwrite(&rate, 4, 1, file); fwrite(&block_rate, 4, 1, file);
    fwrite(&block, 2, 1, file); fwrite(&bits, 2, 1, file);
    fwrite("data", 1, 4, file); fwrite(&data_bytes, 4, 1, file);
    for (i = 0; i < frames * 2; i++) fwrite(&value, 4, 1, file);
    fclose(file);
}

static const char *temp_path(void)
{
    static char path[MAX_PATH + 64];
    DWORD n = GetTempPathA(MAX_PATH, path);
    snprintf(path + n, 64, "canopy_c_test_%lu.wav", (unsigned long)GetCurrentProcessId());
    return path;
}

/* file_read (1) -> boundary outlets "l" (2) and "r" (3); with_stamp: left also feeds stamp (4) -> sink (9).in0 */
static void file_rig(Rig *rig, const char *path, int with_stamp)
{
    rig_open(rig);
    support_counters_reset();
    rig_node(rig, 1, "file_read");
    rig_node(rig, 2, "boundary_outlet");
    rig_node(rig, 3, "boundary_outlet");
    rig_connect(rig, 1, "left", 2, "in");
    rig_connect(rig, 1, "right", 3, "in");
    CHECK_INT(canopy_graph_set_string(rig->graph, 2, "name", "l"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig->graph, 3, "name", "r"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig->graph, 1, "path", path), CANOPY_OK);
    if (with_stamp) {
        rig_node(rig, 4, "test.stamp");
        rig_node(rig, 9, "test.sink");
        rig_connect(rig, 1, "left", 4, "in");
        rig_connect(rig, 4, "out", 9, "in0");
    }
    rig_install(rig);
}

static int message_length(Rig *rig)
{
    char buffer[8];
    int32_t length = -1;
    CHECK_INT(canopy_engine_node_message(rig->engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    return length;
}

typedef struct {
    CanopyEngine *engine;
    volatile LONG *stop;
    volatile LONG reads, bad;
} Reader;

static unsigned __stdcall reader_main(void *argument)
{
    Reader *reader = (Reader *)argument;
    CanopyInstance *instance = canopy_engine_new_instance(reader->engine);
    float span[64];
    int i;
    if (!instance) {
        InterlockedIncrement(&reader->bad);
        return 0;
    }
    while (!*reader->stop) {
        if (canopy_instance_read_span(instance, "l", 10000000, 150000000, 64, span) != CANOPY_OK) InterlockedIncrement(&reader->bad);
        for (i = 1; i < 64; i++)
            if (span[i] != span[0]) InterlockedIncrement(&reader->bad);                   /* one span, one file: never a mixture of two */
        if (span[0] != 0.25f && span[0] != 0.75f) InterlockedIncrement(&reader->bad);      /* and never memory that was freed */
        if (canopy_instance_read_at(instance, "r", 50000000) != span[0]) {
            /* (the file may have been replaced between the two reads) */
            float again = canopy_instance_read_at(instance, "r", 50000000);
            if (again != 0.25f && again != 0.75f) InterlockedIncrement(&reader->bad);
        }
        InterlockedIncrement(&reader->reads);
    }
    canopy_instance_free(instance);
    return 0;
}

static void test_c_replacing_the_file_while_other_threads_read_it_never_shows_a_mixture_or_freed_memory(void)
{
    enum { READERS = 3, OPENS = 300 };
    Rig rig;
    const char *path = temp_path();
    volatile LONG stop = 0;
    Reader readers[READERS];
    HANDLE handles[READERS];
    long long bad = 0;
    int i, r;
    write_constant_wav(path, 0.25f, 200);
    file_rig(&rig, path, 0);
    for (r = 0; r < READERS; r++) {
        readers[r].engine = rig.engine;
        readers[r].stop = &stop;
        readers[r].reads = readers[r].bad = 0;
        handles[r] = (HANDLE)_beginthreadex(NULL, 0, reader_main, &readers[r], 0, NULL);
    }
    for (i = 1; i <= OPENS; i++) {
        LONG before[READERS];
        ULONGLONG deadline = GetTickCount64() + 5000;
        int waiting = 1;
        write_constant_wav(path, i % 2 ? 0.75f : 0.25f, 200);
        CHECK_INT(canopy_engine_action(rig.engine, 1, "open"), CANOPY_OK);
        for (r = 0; r < READERS; r++) before[r] = readers[r].reads;
        while (waiting && GetTickCount64() < deadline) {                                    /* every reader reads between two replacements */
            waiting = 0;
            for (r = 0; r < READERS; r++)
                if (readers[r].reads <= before[r]) waiting = 1;
            if (waiting) Sleep(0);
        }
        CHECK(!waiting);
        if (waiting) break;
    }
    InterlockedExchange(&stop, 1);
    WaitForMultipleObjects(READERS, handles, TRUE, INFINITE);
    for (r = 0; r < READERS; r++) {
        bad += readers[r].bad;
        CloseHandle(handles[r]);
    }
    CHECK_INT(bad, 0);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(message_length(&rig), 0);
    rig_close(&rig);                                                                       /* (and every block of every file is back: no leak) */
    DeleteFileA(path);
}

static void test_c_running_out_of_memory_while_opening_keeps_the_old_file_says_why_and_leaks_nothing(void)
{
    int64_t fail_at;
    int failures = 0, successes = 0;
    const char *path = temp_path();
    for (fail_at = 0; fail_at < 400 && successes < 2; fail_at++) {
        Rig rig;
        float value;
        write_constant_wav(path, 0.25f, 50);
        file_rig(&rig, path, 0);
        write_constant_wav(path, 0.75f, 50);
        canopy_alloc_fail_after(fail_at);
        CHECK_INT(canopy_engine_action(rig.engine, 1, "open"), CANOPY_OK);
        canopy_alloc_fail_after(-1);
        value = canopy_instance_read_at(rig.instance, "l", 10000000);
        if (value == 0.75f) {
            successes++;
            CHECK_INT(message_length(&rig), 0);
        } else {
            failures++;
            CHECK(value == 0.25f);                                                         /* the old file is still there */
            CHECK(message_length(&rig) > 0);                                               /* and the node says why */
        }
        rig_close(&rig);                                                                   /* leak check against the baseline */
    }
    DeleteFileA(path);
    CHECK(failures >= 3);                                                                  /* (a load makes only a handful of allocations: each failed in turn) */
    CHECK_INT(successes, 2);
}

static void test_c_running_out_of_memory_while_a_graph_with_a_file_is_installed_leaks_nothing(void)
{
    int64_t fail_at;
    int installed = 0, refused = 0;
    const char *path = temp_path();
    write_constant_wav(path, 0.5f, 50);
    for (fail_at = 0; fail_at < 600 && installed < 2; fail_at++) {
        Rig rig;
        int32_t status;
        rig_open(&rig);
        rig_node(&rig, 1, "file_read");
        rig_node(&rig, 2, "boundary_outlet");
        rig_connect(&rig, 1, "left", 2, "in");
        CHECK_INT(canopy_graph_set_string(rig.graph, 2, "name", "l"), CANOPY_OK);
        CHECK_INT(canopy_graph_set_string(rig.graph, 1, "path", path), CANOPY_OK);
        canopy_alloc_fail_after(fail_at);
        status = canopy_engine_set_graph(rig.engine, rig.graph);
        canopy_alloc_fail_after(-1);
        if (status == CANOPY_OK) {
            CanopyInstance *instance = canopy_engine_new_instance(rig.engine);
            float value;
            installed++;
            CHECK(instance != NULL);
            value = instance ? canopy_instance_read_at(instance, "l", 10000000) : -1.0f;
            CHECK(value == 0.5f || value == 0.0f);                                         /* the file, or silence if it could not be loaded */
            if (instance) canopy_instance_free(instance);
        } else {
            refused++;
            CHECK_INT(status, CANOPY_ERR_MEMORY);
        }
        CHECK_INT(canopy_engine_free(rig.engine), CANOPY_OK);
        canopy_graph_free(rig.graph);
        canopy_registry_free(rig.registry);
        CHECK_INT(canopy_alloc_live(), rig.live_before);
        memset(&rig, 0, sizeof rig);
    }
    DeleteFileA(path);
    CHECK(refused > 5);
    CHECK_INT(installed, 2);
}

static void test_c_opening_a_file_changes_the_stamp_downstream_and_a_failed_open_does_not(void)
{
    Rig rig;
    const char *path = temp_path();
    uint64_t before, after, failed;
    write_constant_wav(path, 0.25f, 50);
    file_rig(&rig, path, 1);
    (void)canopy_instance_inlet_at(rig.instance, 9, 0, 0);
    before = support_stamps[0];
    write_constant_wav(path, 0.75f, 50);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "open"), CANOPY_OK);
    (void)canopy_instance_inlet_at(rig.instance, 9, 0, 0);
    after = support_stamps[0];
    CHECK(before != 0 && after != before);
    DeleteFileA(path);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "open"), CANOPY_OK);                     /* the file is gone: the open fails */
    CHECK(message_length(&rig) > 0);
    (void)canopy_instance_inlet_at(rig.instance, 9, 0, 0);
    failed = support_stamps[0];
    CHECK(failed == after);                                                                /* nothing changed, so nothing downstream is stale */
    rig_close(&rig);
}

static void test_c_the_file_node_type_is_built_in_with_its_path_button_and_two_outlets(void)
{
    CanopyRegistry *registry = canopy_registry_new();
    const CanopyNodeType *type = canopy_registry_find(registry, "file_read");
    CHECK(type != NULL);
    if (type) {
        CHECK(type->n_inlets == 0 && type->n_outlets == 2 && strcmp(type->outlets[0].key, "left") == 0 && strcmp(type->outlets[1].key, "right") == 0);
        CHECK(type->n_settings == 1 && strcmp(type->settings[0].key, "path") == 0 && type->settings[0].kind == CANOPY_SETTING_PATH);
        CHECK(type->settings[0].default_string != NULL && type->settings[0].default_string[0] == '\0');
        CHECK(type->n_widgets == 1 && type->widgets[0].kind == CANOPY_WIDGET_BUTTON && strcmp(type->widgets[0].action, "open") == 0);
        CHECK((type->flags & CANOPY_FLAG_REALTIME_SAFE) && !(type->flags & CANOPY_FLAG_HAS_INTERNAL_RATE));
        CHECK(type->handlers.create_shared && type->handlers.destroy_shared && type->handlers.on_action && type->handlers.query_at && type->handlers.query_span);
    }
    canopy_registry_free(registry);
}

static void test_c_queries_of_the_file_node_allocate_nothing(void)
{
    Rig rig;
    const char *path = temp_path();
    float span[256];
    int64_t before;
    int i;
    write_constant_wav(path, 0.25f, 100);
    file_rig(&rig, path, 0);
    (void)canopy_instance_read_at(rig.instance, "l", 0);
    before = canopy_alloc_total();
    for (i = 0; i < 50; i++) {
        (void)canopy_instance_read_at(rig.instance, "l", i * 1000003LL);
        CHECK_INT(canopy_instance_read_span(rig.instance, "r", -5000000, 120000000, 256, span), CANOPY_OK);
    }
    CHECK_INT(canopy_alloc_total(), before);
    rig_close(&rig);
    DeleteFileA(path);
}

void register_test_fileread(void)
{
    RUN(test_c_replacing_the_file_while_other_threads_read_it_never_shows_a_mixture_or_freed_memory);
    RUN(test_c_running_out_of_memory_while_opening_keeps_the_old_file_says_why_and_leaks_nothing);
    RUN(test_c_running_out_of_memory_while_a_graph_with_a_file_is_installed_leaks_nothing);
    RUN(test_c_opening_a_file_changes_the_stamp_downstream_and_a_failed_open_does_not);
    RUN(test_c_the_file_node_type_is_built_in_with_its_path_button_and_two_outlets);
    RUN(test_c_queries_of_the_file_node_allocate_nothing);
}
