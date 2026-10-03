/* Tests: the graph description, compiling and installing it, engine and instance lifecycle, knobs, settings, actions
   (docs/canopy_design.md sections 6, 8, 12, 14 and 16). */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "support.h"

/* ---- a node type with a setting of every kind and the internal sampling rate: it reads them all when queried ---- */

static const CanopyOutletDesc OUT_ONE[] = {{"out", "Out"}};
static const char *const MODES[] = {"low", "mid", "high"};
static const CanopySettingDesc SETTINGS_ALL[] = {
    {"count", CANOPY_SETTING_INT, 7, 0.0, NULL, 0, NULL},                  /* 0 */
    {"ratio", CANOPY_SETTING_FLOAT, 0, 1.5, NULL, 0, NULL},                /* 1 */
    {"label", CANOPY_SETTING_STRING, 0, 0.0, "abc", 0, NULL},              /* 2 */
    {"file", CANOPY_SETTING_PATH, 0, 0.0, NULL, 0, NULL},                  /* 3 */
    {"mode", CANOPY_SETTING_CHOICE, 1, 0.0, NULL, 3, MODES},               /* 4 */
};                                                                          /* 5: internal_sampling_rate, added by the registry */

static struct {
    int64_t count, mode, rate;
    double ratio;
    char label[64], file[64];
    int64_t int_of_float, int_of_string, int_low, int_high;
    double float_of_int, float_low, float_high;
    char string_of_int[16], string_low[16], string_high[16];
    int64_t choice_as_int;
    int reads;
} reading;

static float settings_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)outlet; (void)t;
    reading.count = canopy_ctx_int(ctx, 0);
    reading.ratio = canopy_ctx_float(ctx, 1);
    strncpy(reading.label, canopy_ctx_string(ctx, 2), sizeof reading.label - 1);
    strncpy(reading.file, canopy_ctx_string(ctx, 3), sizeof reading.file - 1);
    reading.mode = canopy_ctx_int(ctx, 4);
    reading.rate = canopy_ctx_int(ctx, 5);
    reading.int_of_float = canopy_ctx_int(ctx, 1);                         /* the wrong kind... */
    reading.int_of_string = canopy_ctx_int(ctx, 2);
    reading.float_of_int = canopy_ctx_float(ctx, 0);
    strncpy(reading.string_of_int, canopy_ctx_string(ctx, 0), sizeof reading.string_of_int - 1);
    reading.choice_as_int = canopy_ctx_int(ctx, 4);
    reading.int_low = canopy_ctx_int(ctx, -1);                             /* ...and indexes that do not exist */
    reading.int_high = canopy_ctx_int(ctx, 6);
    reading.float_low = canopy_ctx_float(ctx, -1);
    reading.float_high = canopy_ctx_float(ctx, 99);
    strncpy(reading.string_low, canopy_ctx_string(ctx, -1), sizeof reading.string_low - 1);
    strncpy(reading.string_high, canopy_ctx_string(ctx, 99), sizeof reading.string_high - 1);
    reading.reads++;
    return 0.0f;
}

static CanopyNodeType settings_type(void)
{
    CanopyNodeType type = support_base_type("test.settings", "Settings");
    type.flags = CANOPY_FLAG_HAS_INTERNAL_RATE;
    type.n_outlets = 1; type.outlets = OUT_ONE;
    type.n_settings = 5; type.settings = SETTINGS_ALL;
    type.handlers.query_at = settings_at;
    return type;
}

static void read_settings(Rig *rig, int64_t sink)
{
    memset(&reading, 0, sizeof reading);
    (void)canopy_instance_inlet_at(rig->instance, sink, 0, 0);
    CHECK_INT(reading.reads, 1);
}

static void test_c_settings_take_their_defaults_and_the_registry_added_internal_rate(void)
{
    Rig rig;
    CanopyNodeType type = settings_type();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.settings");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    read_settings(&rig, 2);
    CHECK_INT(reading.count, 7);
    CHECK(reading.ratio == 1.5);
    CHECK(strcmp(reading.label, "abc") == 0);
    CHECK(strcmp(reading.file, "") == 0);                                   /* a NULL default string reads as empty */
    CHECK_INT(reading.mode, 1);
    CHECK_INT(reading.rate, 48000);
    rig_close(&rig);
}

static void test_c_settings_set_in_the_graph_are_read_through_the_typed_getters(void)
{
    Rig rig;
    CanopyNodeType type = settings_type();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.settings");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "count", -123456789012LL), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "ratio", -2.25), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "label", "hello world"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "file", "C:/music/a.wav"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "mode", 2), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "internal_sampling_rate", 44100), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "count", 42), CANOPY_OK);          /* setting again keeps the last value */
    rig_install(&rig);
    read_settings(&rig, 2);
    CHECK_INT(reading.count, 42);
    CHECK(reading.ratio == -2.25);
    CHECK(strcmp(reading.label, "hello world") == 0);
    CHECK(strcmp(reading.file, "C:/music/a.wav") == 0);
    CHECK_INT(reading.mode, 2);
    CHECK_INT(reading.rate, 44100);
    rig_close(&rig);
}

static void test_c_a_getter_of_the_wrong_kind_or_with_a_bad_index_gives_zero_or_empty(void)
{
    Rig rig;
    CanopyNodeType type = settings_type();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.settings");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "label", "text"), CANOPY_OK);
    rig_install(&rig);
    read_settings(&rig, 2);
    CHECK_INT(reading.int_of_float, 0);                                     /* canopy_ctx_int on a FLOAT */
    CHECK_INT(reading.int_of_string, 0);                                    /* canopy_ctx_int on a STRING */
    CHECK(reading.float_of_int == 0.0);                                     /* canopy_ctx_float on an INT */
    CHECK(strcmp(reading.string_of_int, "") == 0);                          /* canopy_ctx_string on an INT */
    CHECK_INT(reading.choice_as_int, 1);                                    /* a CHOICE reads as its index through canopy_ctx_int */
    CHECK_INT(reading.int_low, 0);
    CHECK_INT(reading.int_high, 0);
    CHECK(reading.float_low == 0.0 && reading.float_high == 0.0);
    CHECK(strcmp(reading.string_low, "") == 0 && strcmp(reading.string_high, "") == 0);
    rig_close(&rig);
}

/* ---- compile faults ---- */

typedef struct {
    const char *what;
    const char *needle;                                                      /* what the message must name: a node ID, a key... */
    const char *phrase;                                                      /* and a phrase that says what is wrong */
} Fault;

/* describes a graph with one fault; node 1 is a test.const, node 2 a test.sink, node 4 a test.settings unless the case says otherwise */
static void describe_fault(CanopyGraph *g, int which)
{
    CHECK_INT(canopy_graph_add_node(g, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 4, "test.settings"), CANOPY_OK);
    switch (which) {
    case 0: canopy_graph_add_node(g, 1, "test.sink"); break;
    case 1: canopy_graph_add_node(g, 5, "no.such.type"); break;
    case 2: canopy_graph_set_float(g, 77, "value", 1.0); break;
    case 3: canopy_graph_set_float(g, 1, "nope", 1.0); break;
    case 4: canopy_graph_set_int(g, 1, "value", 1); break;                         /* an INT call for a FLOAT setting */
    case 5: canopy_graph_set_string(g, 1, "value", "x"); break;
    case 6: canopy_graph_set_float(g, 1, "value", INFINITY); break;
    case 7: canopy_graph_set_float(g, 1, "value", (double)NAN); break;
    case 8: canopy_graph_set_knob(g, 78, "in0", 0.5f); break;
    case 9: canopy_graph_set_knob(g, 2, "nope", 0.5f); break;
    case 10: canopy_graph_set_knob(g, 2, "in0", 1.5f); break;
    case 11: canopy_graph_set_knob(g, 2, "in0", NAN); break;
    case 12: canopy_graph_connect(g, 79, "out", 2, "in0"); break;
    case 13: canopy_graph_connect(g, 1, "out", 80, "in0"); break;
    case 14: canopy_graph_connect(g, 1, "nope", 2, "in0"); break;
    case 15: canopy_graph_connect(g, 1, "out", 2, "nope"); break;
    case 16:                                                                        /* two outlets into one inlet */
        canopy_graph_add_node(g, 3, "test.const");
        canopy_graph_connect(g, 1, "out", 2, "in0");
        canopy_graph_connect(g, 3, "out", 2, "in0");
        break;
    case 17:                                                                        /* the same connection twice */
        canopy_graph_connect(g, 1, "out", 2, "in0");
        canopy_graph_connect(g, 1, "out", 2, "in0");
        break;
    case 18: canopy_graph_set_int(g, 4, "mode", 3); break;                          /* a CHOICE index out of range */
    case 19: canopy_graph_set_int(g, 4, "mode", -1); break;
    case 20: canopy_graph_set_string(g, 4, "mode", "low"); break;                   /* a CHOICE is set by index */
    case 21: canopy_graph_set_int(g, 4, "internal_sampling_rate", 0); break;
    case 22: canopy_graph_set_int(g, 4, "internal_sampling_rate", 384001); break;
    case 23: canopy_graph_set_int(g, 4, "internal_sampling_rate", -48000); break;
    case 24: canopy_graph_set_float(g, 4, "internal_sampling_rate", 44100.0); break;
    case 25: canopy_graph_set_float(g, 4, "count", 1.0); break;                     /* a FLOAT call for an INT setting */
    case 26: canopy_graph_set_knob(g, 1, "in", 0.0f); break;                        /* node 1 has no inlets */
    case 27: canopy_graph_set_int(g, 1, "internal_sampling_rate", 48000); break;    /* node 1 has no such setting */
    case 28: canopy_graph_set_float(g, 4, "ratio", -INFINITY); break;
    case 29: canopy_graph_set_int(g, 4, "label", 5); break;                         /* an INT call for a STRING setting */
    default: break;
    }
}

static const Fault FAULTS[] = {
    {"duplicate node id", "1", "more than once"},
    {"unknown node type", "no.such.type", "unknown node type"},
    {"setting on an unknown node", "77", "no node"},
    {"unknown setting key", "nope", "no setting"},
    {"INT call for a FLOAT setting", "value", "cannot be set"},
    {"STRING call for a FLOAT setting", "value", "cannot be set"},
    {"infinite float", "value", "finite"},
    {"NaN float", "value", "finite"},
    {"knob on an unknown node", "78", "no node"},
    {"knob on an unknown inlet", "nope", "no inlet"},
    {"knob above 1", "in0", "from -1 to 1"},
    {"knob NaN", "in0", "from -1 to 1"},
    {"connection from an unknown node", "79", "no node"},
    {"connection to an unknown node", "80", "no node"},
    {"connection from an unknown outlet", "nope", "no outlet"},
    {"connection to an unknown inlet", "nope", "no inlet"},
    {"two outlets into one inlet", "in0", "already connected"},
    {"the same connection twice", "in0", "already connected"},
    {"choice index too high", "mode", "choice"},
    {"choice index negative", "mode", "choice"},
    {"choice set by string", "mode", "cannot be set"},
    {"internal rate 0", "internal_sampling_rate", "1 to 384000"},
    {"internal rate 384001", "internal_sampling_rate", "1 to 384000"},
    {"internal rate negative", "internal_sampling_rate", "1 to 384000"},
    {"internal rate as float", "internal_sampling_rate", "cannot be set"},
    {"FLOAT call for an INT setting", "count", "cannot be set"},
    {"knob on a node without inlets", "in", "no inlet"},
    {"internal rate on a type without the flag", "internal_sampling_rate", "no setting"},
    {"-infinity float", "ratio", "finite"},
    {"INT call for a STRING setting", "label", "cannot be set"},
};

static void test_c_every_fault_in_a_graph_is_refused_with_a_message_and_installs_nothing(void)
{
    size_t which;
    for (which = 0; which < sizeof FAULTS / sizeof FAULTS[0]; which++) {
        Rig rig;
        CanopyNodeType type = settings_type();
        int32_t status;
        rig_open(&rig);
        support_add_type(rig.registry, &type);
        describe_fault(rig.graph, (int)which);
        status = canopy_engine_set_graph(rig.engine, rig.graph);
        if (status != CANOPY_ERR_GRAPH || strstr(canopy_engine_last_error(rig.engine), FAULTS[which].needle) == NULL ||
            strstr(canopy_engine_last_error(rig.engine), FAULTS[which].phrase) == NULL) {
            ctest_current_failed = 1;
            printf("    fault %zu (%s): status %d, message \"%s\", expected CANOPY_ERR_GRAPH naming \"%s\" and saying \"%s\"\n", which,
                   FAULTS[which].what, (int)status, canopy_engine_last_error(rig.engine), FAULTS[which].needle, FAULTS[which].phrase);
        }
        CHECK_INT(canopy_engine_node_count(rig.engine), 0);
        CHECK(canopy_engine_new_instance(rig.engine) == NULL);              /* nothing was installed */
        rig_close(&rig);
    }
}

static void test_c_the_base_description_of_the_fault_table_compiles_so_each_refusal_comes_from_its_own_line(void)
{
    /* guards the table above: the same description without its fault line compiles, so a refusal is caused by that line alone */
    Rig rig;
    CanopyNodeType type = settings_type();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    describe_fault(rig.graph, -1);                                          /* the three base nodes and nothing else */
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK_INT(canopy_engine_node_count(rig.engine), 3);
    CHECK(strlen(canopy_engine_last_error(rig.engine)) == 0);
    rig_close(&rig);
}

static void test_c_valid_values_at_the_edges_of_their_ranges_compile(void)
{
    Rig rig;
    CanopyNodeType type = settings_type();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 4, "test.settings");
    rig_node(&rig, 2, "test.sink");
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "internal_sampling_rate", 1), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "mode", 0), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(rig.graph, 2, "in0", -1.0f), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(rig.graph, 2, "in1", 1.0f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "internal_sampling_rate", 384000), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "mode", 2), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    rig_close(&rig);
}

static void test_c_loops_and_self_connections_are_not_a_compile_fault(void)
{
    Rig rig;
    rig_open(&rig);
    rig_node(&rig, 1, "test.shift");
    rig_node(&rig, 2, "test.shift");
    rig_node(&rig, 3, "test.gain");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 1, "in");                                   /* a loop through two nodes */
    rig_connect(&rig, 3, "out", 3, "in");                                   /* a node into itself */
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK_INT(canopy_engine_node_count(rig.engine), 3);
    rig_close(&rig);
}

static void test_c_an_empty_graph_compiles_and_has_an_instance_that_answers_nothing(void)
{
    Rig rig;
    float out[4] = {1, 2, 3, 4};
    rig_open(&rig);
    rig_install(&rig);
    CHECK_INT(canopy_engine_node_count(rig.engine), 0);
    CHECK_INT(canopy_instance_arena_floats(rig.instance), 0);
    CHECK(canopy_instance_inlet_at(rig.instance, 1, 0, 0) == 0.0f);
    CHECK_INT(canopy_instance_inlet_span(rig.instance, 1, 0, 0, 10, 4, out), CANOPY_ERR_NODE);
    CHECK(out[0] == 0.0f && out[3] == 0.0f);
    rig_close(&rig);
}

static void test_c_a_failed_compile_leaves_the_installed_graph_and_its_instances_working(void)
{
    Rig rig;
    CanopyGraph *broken;
    rig_open(&rig);
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.75), CANOPY_OK);
    rig_install(&rig);
    CHECK(canopy_instance_inlet_at(rig.instance, 2, 0, 5) == 0.75f);
    broken = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(broken, 1, "no.such.type"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, broken), CANOPY_ERR_GRAPH);
    CHECK(strstr(canopy_engine_last_error(rig.engine), "no.such.type") != NULL);
    CHECK_INT(canopy_engine_node_count(rig.engine), 2);                       /* the first graph is still the installed one */
    CHECK(canopy_instance_inlet_at(rig.instance, 2, 0, 5) == 0.75f);
    {
        CanopyInstance *another = canopy_engine_new_instance(rig.engine);   /* and a new instance gets that graph */
        CHECK(another != NULL);
        if (another) {
            CHECK(canopy_instance_inlet_at(another, 2, 0, 5) == 0.75f);
            canopy_instance_free(another);
        }
    }
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);   /* a good graph clears the message */
    CHECK(strlen(canopy_engine_last_error(rig.engine)) == 0);
    canopy_graph_free(broken);
    rig_close(&rig);
}

/* ---- knobs ---- */

static void test_c_knobs_start_at_the_default_or_the_description_and_report_a_generation_that_counts_writes(void)
{
    Rig rig;
    float value = -9.0f;
    uint64_t generation = 99;
    rig_open(&rig);
    rig_node(&rig, 1, "test.sink");
    CHECK_INT(canopy_graph_set_knob(rig.graph, 1, "in0", -0.5f), CANOPY_OK);      /* in0 asked for -0.5; in1 keeps its default 0.5 */
    rig_install(&rig);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 0, &value, &generation), CANOPY_OK);
    CHECK(value == -0.5f);
    CHECK_INT((long long)generation, 0);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 0.5f);
    CHECK_INT((long long)generation, 0);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 1, 0.25f), CANOPY_OK);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 0.25f);
    CHECK_INT((long long)generation, 1);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 1, 0.25f), CANOPY_OK);          /* writing the same value is still a write */
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 1, &value, &generation), CANOPY_OK);
    CHECK_INT((long long)generation, 2);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 0, &value, &generation), CANOPY_OK);    /* the other knob is untouched */
    CHECK(value == -0.5f);
    CHECK_INT((long long)generation, 0);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 0, NULL, NULL), CANOPY_OK);     /* both outputs are optional */
    rig_close(&rig);
}

static void test_c_set_knob_refuses_bad_values_and_unknown_targets_and_changes_nothing(void)
{
    Rig rig;
    float value = 0.0f;
    uint64_t generation = 0;
    rig_open(&rig);
    rig_node(&rig, 1, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, 1.0f), CANOPY_OK);           /* the limits are allowed */
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, -1.0f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, 1.0001f), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, -1.0001f), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, NAN), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, INFINITY), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 0, &value, &generation), CANOPY_OK);
    CHECK(value == -1.0f);                                                          /* the last good write stands */
    CHECK_INT((long long)generation, 2);                                            /* and the refused ones did not count */
    CHECK_INT(canopy_engine_set_knob(rig.engine, 5, 0, 0.0f), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 2, 0.0f), CANOPY_ERR_PORT);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, -1, 0.0f), CANOPY_ERR_PORT);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 5, 0, &value, &generation), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 2, &value, &generation), CANOPY_ERR_PORT);
    CHECK_INT(canopy_engine_set_knob(NULL, 1, 0, 0.0f), CANOPY_ERR_ARGUMENT);
    rig_close(&rig);
}

static void test_c_installing_another_graph_keeps_knobs_by_node_id_and_the_description_wins(void)
{
    Rig rig;
    CanopyGraph *second;
    CanopyInstance *old_instance;
    float value = 0.0f;
    uint64_t generation = 0;
    rig_open(&rig);
    second = canopy_graph_new();
    rig_node(&rig, 2, "test.sink");
    rig_install(&rig);                                                              /* knob in1 starts at its default 0.5, generation 0 */
    old_instance = rig.instance;
    rig.instance = NULL;
    CHECK_INT(canopy_graph_add_node(second, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 3, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(second, 2, "in1", 0.75f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(canopy_engine_node_count(rig.engine), 2);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 2, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 0.75f);                                                          /* the description replaced the slot's value... */
    CHECK_INT((long long)generation, 1);                                            /* ...and that counted as a write */
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);              /* the same description again: nothing differs */
    CHECK_INT(canopy_engine_get_knob(rig.engine, 2, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 0.75f);
    CHECK_INT((long long)generation, 1);                                            /* so no spurious generation bump */
    CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 1, 0.1f), CANOPY_OK);           /* a host write... */
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);              /* ...is overwritten by the description */
    CHECK_INT(canopy_engine_get_knob(rig.engine, 2, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 0.75f);
    CHECK_INT((long long)generation, 3);
    /* the instance made on the first graph shares the knob slot: it sees the current position */
    CHECK(canopy_instance_inlet_at(old_instance, 2, 1, 0) == 0.75f);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 1, -0.5f), CANOPY_OK);
    CHECK(canopy_instance_inlet_at(old_instance, 2, 1, 0) == -0.5f);
    canopy_instance_free(old_instance);
    canopy_graph_free(second);
    rig_close(&rig);
}

static void test_c_a_node_id_that_comes_back_with_another_type_gets_knobs_of_its_own(void)
{
    Rig rig;
    CanopyGraph *as_gain;
    float value = 0.0f;
    uint64_t generation = 99;
    rig_open(&rig);
    as_gain = canopy_graph_new();
    rig_node(&rig, 1, "test.sink");                                           /* node 1 as a sink: in1 starts at 0.5 */
    CHECK_INT(canopy_graph_add_node(as_gain, 1, "test.gain"), CANOPY_OK);     /* node 1 as a gain: its second inlet starts at 1.0 */
    rig_install(&rig);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 1, -0.25f), CANOPY_OK);   /* the sink's knob moves: generation 1 */
    CHECK_INT(canopy_engine_set_graph(rig.engine, as_gain), CANOPY_OK);
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 1.0f);                                                     /* a knob of the new type, not the sink's slot taken over */
    CHECK_INT((long long)generation, 0);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);     /* and back to the sink: its own slot is found again */
    CHECK_INT(canopy_engine_get_knob(rig.engine, 1, 1, &value, &generation), CANOPY_OK);
    CHECK(value == 0.5f);                                                     /* the description wins over the -0.25 */
    CHECK_INT((long long)generation, 2);                                      /* 1 (the move) + 1 (the description's write): the slot persisted */
    canopy_graph_free(as_gain);
    rig_close(&rig);
}

/* ---- lifecycle: shared resources, instance state, actions, and the contexts of the handlers that run outside a query ---- */

static int life_shared_created, life_shared_destroyed, life_state_created, life_state_destroyed, life_actions, life_setup_failures;
static char life_last_action[40];

static void check_setup_context(CanopyCtx *ctx)
{
    float buffer[4] = {9.0f, 9.0f, 9.0f, 9.0f};
    if (canopy_inlet_at(ctx, 0, 5) != 0.0f) life_setup_failures++;
    if (canopy_inlet_span(ctx, 0, 0, 10, 4, buffer) != CANOPY_ERR_ARGUMENT) life_setup_failures++;
    if (buffer[0] != 0.0f || buffer[1] != 0.0f || buffer[2] != 0.0f || buffer[3] != 0.0f) life_setup_failures++;
    if (canopy_scratch(ctx, 4) != NULL) life_setup_failures++;
}

static const CanopySettingDesc LIFE_SETTINGS[] = {{"seed", CANOPY_SETTING_INT, 7, 0.0, NULL, 0, NULL}};

static void *life_create_shared(CanopyCtx *ctx)
{
    int *shared = (int *)malloc(sizeof(int));
    check_setup_context(ctx);
    if (canopy_ctx_shared(ctx) != NULL || canopy_ctx_state(ctx) != NULL) life_setup_failures++;     /* nothing exists yet */
    *shared = (int)canopy_ctx_int(ctx, 0);                  /* the settings are there: the shared resource starts from the seed */
    life_shared_created++;
    return shared;
}

static void life_destroy_shared(CanopyCtx *ctx, void *shared)
{
    check_setup_context(ctx);
    if (canopy_ctx_shared(ctx) != shared) life_setup_failures++;
    free(shared);
    life_shared_destroyed++;
}

static void *life_create_instance(CanopyCtx *ctx)
{
    int *state = (int *)malloc(sizeof(int));
    check_setup_context(ctx);
    if (canopy_ctx_state(ctx) != NULL) life_setup_failures++;
    if (canopy_ctx_shared(ctx) == NULL) life_setup_failures++;                                       /* the shared resource exists by now */
    *state = 3;
    life_state_created++;
    return state;
}

static void life_destroy_instance(CanopyCtx *ctx, void *state)
{
    check_setup_context(ctx);
    if (canopy_ctx_state(ctx) != state) life_setup_failures++;
    if (canopy_ctx_shared(ctx) == NULL) life_setup_failures++;
    free(state);
    life_state_destroyed++;
}

static float life_query(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    int *shared = (int *)canopy_ctx_shared(ctx);
    int *state = (int *)canopy_ctx_state(ctx);
    (void)outlet; (void)t;
    if (!shared || !state) return -1.0f;
    (*shared)++;
    (*state)++;
    return (float)(*shared * 1000 + *state);
}

static void life_action(CanopyCtx *ctx, const char *action)
{
    check_setup_context(ctx);
    if (canopy_ctx_shared(ctx) == NULL) life_setup_failures++;
    strncpy(life_last_action, action, sizeof life_last_action - 1);
    life_actions++;
}

static CanopyNodeType life_type(void)
{
    CanopyNodeType type = support_base_type("test.life", "Life");
    type.n_outlets = 1; type.outlets = OUT_ONE;
    type.n_settings = 1; type.settings = LIFE_SETTINGS;
    type.scratch_buffers = 1;           /* so that "no scratch outside a query" is refused for that reason, not because none was declared */
    type.handlers.create_shared = life_create_shared;
    type.handlers.destroy_shared = life_destroy_shared;
    type.handlers.create_instance = life_create_instance;
    type.handlers.destroy_instance = life_destroy_instance;
    type.handlers.query_at = life_query;
    type.handlers.on_action = life_action;
    return type;
}

static void reset_life(void)
{
    life_shared_created = life_shared_destroyed = life_state_created = life_state_destroyed = life_actions = life_setup_failures = 0;
    memset(life_last_action, 0, sizeof life_last_action);
}

static void test_c_shared_resources_are_made_once_per_node_and_instance_state_once_per_instance(void)
{
    Rig rig;
    CanopyNodeType type = life_type();
    CanopyInstance *second;
    reset_life();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.life");
    rig_node(&rig, 2, "test.life");
    rig_node(&rig, 3, "test.sink");
    rig_connect(&rig, 1, "out", 3, "in0");
    rig_connect(&rig, 2, "out", 3, "in1");
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "seed", 20), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(life_shared_created, 2);                                        /* one per node ID, made when the graph is installed */
    CHECK_INT(life_state_created, 2);                                         /* one per node, for the one instance */
    second = canopy_engine_new_instance(rig.engine);
    CHECK(second != NULL);
    CHECK_INT(life_shared_created, 2);                                        /* a new instance makes no new shared resources... */
    CHECK_INT(life_state_created, 4);                                         /* ...only new instance state */
    /* node 1 through the first instance: shared counter 7 -> 8, state counter 3 -> 4 */
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 3, 0, 0), 8004);
    /* the second instance shares the node's resource (8 -> 9) but has its own state (3 -> 4) */
    CHECK_INT(canopy_instance_inlet_at(second, 3, 0, 0), 9004);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 3, 0, 0), 10005);        /* the first instance's own state goes on counting */
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 3, 1, 0), 21004);        /* node 2 has resources and state of its own (its seed is 20) */
    canopy_instance_free(second);
    CHECK_INT(life_state_destroyed, 2);                                       /* one instance's states are destroyed with it */
    CHECK_INT(life_shared_destroyed, 0);
    canopy_instance_free(rig.instance);
    rig.instance = NULL;
    CHECK_INT(life_state_destroyed, 4);
    CHECK_INT(life_shared_destroyed, 0);                                      /* shared resources outlive their instances... */
    rig_close(&rig);
    CHECK_INT(life_shared_destroyed, 2);                                      /* ...and go with the engine */
    CHECK_INT(life_setup_failures, 0);
}

static void test_c_installing_the_same_graph_again_keeps_each_nodes_shared_resource_and_a_new_node_gets_one(void)
{
    Rig rig;
    CanopyNodeType type = life_type();
    reset_life();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.life");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    CHECK_INT(life_shared_created, 1);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 0), 8004);        /* the shared counter goes 7 -> 8 */
    rig_install(&rig);                                                        /* the same graph again, and a fresh instance */
    CHECK_INT(life_shared_created, 1);                                        /* no second resource... */
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 0), 9004);         /* ...the very same one: its counter goes on (9), the state is new (4) */
    rig_node(&rig, 3, "test.life");                                           /* a new node joins the description */
    rig_install(&rig);
    CHECK_INT(life_shared_created, 2);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 0), 10004);
    CHECK_INT(life_shared_destroyed, 0);                                      /* nothing is destroyed before the engine is */
    rig_close(&rig);
    CHECK_INT(life_shared_destroyed, 2);
    CHECK_INT(life_setup_failures, 0);
}

static void test_c_the_engine_cannot_be_freed_while_an_instance_exists(void)
{
    Rig rig;
    CanopyNodeType type = life_type();
    reset_life();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.life");
    rig_install(&rig);
    CHECK_INT(canopy_engine_free(rig.engine), CANOPY_ERR_BUSY);
    CHECK_INT(life_shared_destroyed, 0);                                      /* nothing was destroyed by the refused call */
    canopy_instance_free(rig.instance);
    rig.instance = NULL;
    rig_close(&rig);                                                          /* now it works */
    CHECK_INT(life_shared_destroyed, 1);
    CHECK_INT(life_setup_failures, 0);
}

static void test_c_actions_reach_the_node_types_on_action_handler(void)
{
    Rig rig;
    CanopyNodeType type = life_type();
    reset_life();
    rig_open(&rig);
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.life");
    rig_node(&rig, 2, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "open"), CANOPY_OK);
    CHECK_INT(life_actions, 1);
    CHECK(strcmp(life_last_action, "open") == 0);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "play"), CANOPY_OK);
    CHECK(strcmp(life_last_action, "play") == 0);
    CHECK_INT(canopy_engine_action(rig.engine, 9, "open"), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_action(rig.engine, 1, NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_action(rig.engine, 2, "open"), CANOPY_OK);          /* a node type without on_action ignores it */
    CHECK_INT(life_actions, 2);
    rig_close(&rig);
    CHECK_INT(life_setup_failures, 0);
}

static void test_c_an_instance_made_before_another_graph_was_installed_adopts_it_when_a_node_changes_type_and_the_old_node_goes_when_unused(void)
{
    Rig rig;
    CanopyNodeType type = life_type();
    CanopyGraph *second;
    reset_life();
    rig_open(&rig);
    second = canopy_graph_new();
    support_add_type(rig.registry, &type);
    rig_node(&rig, 1, "test.life");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    CHECK_INT(canopy_instance_inlet_at(rig.instance, 2, 0, 0), 8004);
    CHECK_INT(canopy_graph_add_node(second, 1, "test.const"), CANOPY_OK);       /* node 1 is now another type */
    CHECK_INT(canopy_graph_add_node(second, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 1, "out", 2, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(second, 1, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(life_shared_destroyed, 0);                                         /* the old instance has not moved on: the old node, resource and state live */
    {
        CanopyInstance *fresh = canopy_engine_new_instance(rig.engine);
        CHECK(fresh != NULL);
        if (fresh) {
            CHECK(canopy_instance_inlet_at(fresh, 2, 0, 0) == 0.5f);            /* a new instance runs the new graph at once */
            canopy_instance_free(fresh);
        }
    }
    CHECK(canopy_instance_inlet_at(rig.instance, 2, 0, 0) == 0.5f);             /* the old instance adopts it at its next query: node 1 is a constant now */
    CHECK_INT(life_shared_destroyed, 0);                                         /* (a query frees nothing) */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(life_shared_destroyed, 1);                                         /* nobody can use the life node now: its resource and state are freed */
    CHECK_INT(life_state_destroyed, 1);
    canopy_graph_free(second);
    rig_close(&rig);
    CHECK_INT(life_shared_destroyed, life_shared_created);
    CHECK_INT(life_setup_failures, 0);
}

static void test_c_the_functions_refuse_null_arguments_without_crashing(void)
{
    CanopyRegistry *registry = support_registry();
    CanopyGraph *graph = canopy_graph_new();
    CanopyEngine *engine = canopy_engine_new(registry);
    float out[2] = {1.0f, 1.0f};
    CHECK_INT(canopy_graph_add_node(NULL, 1, "test.const"), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_add_node(graph, 1, NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_set_int(NULL, 1, "k", 1), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_set_int(graph, 1, NULL, 1), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_set_float(graph, 1, NULL, 1.0), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_set_string(graph, 1, "k", NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_set_string(graph, 1, NULL, "v"), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_set_knob(graph, 1, NULL, 0.0f), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_connect(graph, 1, NULL, 2, "in"), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_connect(graph, 1, "out", 2, NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_graph_connect(NULL, 1, "out", 2, "in"), CANOPY_ERR_ARGUMENT);
    canopy_graph_free(NULL);
    CHECK(canopy_engine_new(NULL) == NULL);
    CHECK_INT(canopy_engine_set_graph(NULL, graph), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_graph(engine, NULL), CANOPY_ERR_ARGUMENT);
    CHECK(canopy_engine_last_error(NULL) != NULL && strlen(canopy_engine_last_error(NULL)) == 0);
    CHECK_INT(canopy_engine_node_count(NULL), 0);
    CHECK_INT(canopy_engine_get_knob(NULL, 1, 0, NULL, NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_action(NULL, 1, "a"), CANOPY_ERR_ARGUMENT);
    CHECK(canopy_engine_new_instance(NULL) == NULL);
    canopy_instance_free(NULL);
    CHECK_INT(canopy_instance_arena_floats(NULL), 0);
    CHECK(canopy_instance_inlet_at(NULL, 1, 0, 0) == 0.0f);
    CHECK_INT(canopy_instance_inlet_span(NULL, 1, 0, 0, 10, 2, out), CANOPY_ERR_ARGUMENT);
    CHECK(out[0] == 0.0f && out[1] == 0.0f);                                  /* the output is zero-filled even then */
    CHECK_INT(canopy_engine_free(NULL), CANOPY_OK);
    CHECK_INT(canopy_engine_free(engine), CANOPY_OK);
    canopy_graph_free(graph);
    canopy_registry_free(registry);
}

/* ---- running out of memory at every possible point ---- */

/* builds, installs and queries a graph, doing everything that allocates; stops at the first failure and frees what exists. 1 = all went well. */
static int scenario(CanopyRegistry *registry)
{
    CanopyGraph *graph = canopy_graph_new();
    CanopyEngine *engine = NULL;
    CanopyInstance *instance = NULL;
    int ok = 0;
    float out[8];
    if (!graph) return 0;
    if (canopy_graph_add_node(graph, 1, "test.life") != CANOPY_OK) goto done;
    if (canopy_graph_add_node(graph, 2, "test.gain") != CANOPY_OK) goto done;
    if (canopy_graph_add_node(graph, 3, "test.sink") != CANOPY_OK) goto done;
    if (canopy_graph_add_node(graph, 4, "test.const") != CANOPY_OK) goto done;
    if (canopy_graph_add_node(graph, 5, "test.settings") != CANOPY_OK) goto done;
    if (canopy_graph_set_float(graph, 4, "value", 2.0) != CANOPY_OK) goto done;
    if (canopy_graph_set_string(graph, 5, "label", "some longer label text") != CANOPY_OK) goto done;
    if (canopy_graph_set_string(graph, 5, "file", "C:/a/b/c.wav") != CANOPY_OK) goto done;
    if (canopy_graph_set_int(graph, 5, "mode", 1) != CANOPY_OK) goto done;
    if (canopy_graph_set_knob(graph, 2, "gain", 0.5f) != CANOPY_OK) goto done;
    if (canopy_graph_connect(graph, 4, "out", 2, "in") != CANOPY_OK) goto done;
    if (canopy_graph_connect(graph, 2, "out", 3, "in0") != CANOPY_OK) goto done;
    if (canopy_graph_connect(graph, 1, "out", 3, "in1") != CANOPY_OK) goto done;
    engine = canopy_engine_new(registry);
    if (!engine) goto done;
    if (canopy_engine_set_graph(engine, graph) != CANOPY_OK) goto done;
    if (canopy_engine_set_graph(engine, graph) != CANOPY_OK) goto done;       /* installing twice exercises the existing records */
    instance = canopy_engine_new_instance(engine);
    if (!instance) goto done;
    if (canopy_instance_inlet_span(instance, 3, 0, 0, 80, 8, out) != CANOPY_OK) goto done;
    ok = out[0] == 1.0f;
done:
    if (instance) canopy_instance_free(instance);
    if (engine && canopy_engine_free(engine) != CANOPY_OK) ok = 0;
    canopy_graph_free(graph);
    return ok;
}

static void test_c_running_out_of_memory_at_any_point_fails_cleanly_and_leaks_nothing(void)
{
    CanopyNodeType life = life_type(), settings = settings_type();
    CanopyRegistry *registry = support_registry();
    int64_t live;
    int64_t fail_at;
    int failures = 0, clean_runs = 0;
    support_add_type(registry, &life);
    support_add_type(registry, &settings);
    live = canopy_alloc_live();
    for (fail_at = 0; fail_at < 2000 && clean_runs < 3; fail_at++) {
        int ok;
        reset_life();
        canopy_alloc_fail_after(fail_at);
        ok = scenario(registry);
        canopy_alloc_fail_after(-1);
        if (ok) clean_runs++; else failures++;
        if (canopy_alloc_live() != live || life_shared_created != life_shared_destroyed || life_state_created != life_state_destroyed ||
            life_setup_failures != 0) {
            ctest_current_failed = 1;
            printf("    out of memory after %lld allocations: live %lld (expected %lld), shared %d/%d, state %d/%d, setup failures %d\n",
                   (long long)fail_at, (long long)canopy_alloc_live(), (long long)live, life_shared_created, life_shared_destroyed,
                   life_state_created, life_state_destroyed, life_setup_failures);
            break;
        }
    }
    CHECK(failures > 50);                                   /* there really were many different failure points... */
    CHECK_INT(clean_runs, 3);                               /* ...and the sweep ended when the scenario no longer reached one */
    CHECK_HEAP();
    canopy_registry_free(registry);
}

void register_test_graph(void)
{
    RUN(test_c_settings_take_their_defaults_and_the_registry_added_internal_rate);
    RUN(test_c_settings_set_in_the_graph_are_read_through_the_typed_getters);
    RUN(test_c_a_getter_of_the_wrong_kind_or_with_a_bad_index_gives_zero_or_empty);
    RUN(test_c_every_fault_in_a_graph_is_refused_with_a_message_and_installs_nothing);
    RUN(test_c_the_base_description_of_the_fault_table_compiles_so_each_refusal_comes_from_its_own_line);
    RUN(test_c_valid_values_at_the_edges_of_their_ranges_compile);
    RUN(test_c_loops_and_self_connections_are_not_a_compile_fault);
    RUN(test_c_an_empty_graph_compiles_and_has_an_instance_that_answers_nothing);
    RUN(test_c_a_failed_compile_leaves_the_installed_graph_and_its_instances_working);
    RUN(test_c_knobs_start_at_the_default_or_the_description_and_report_a_generation_that_counts_writes);
    RUN(test_c_set_knob_refuses_bad_values_and_unknown_targets_and_changes_nothing);
    RUN(test_c_installing_another_graph_keeps_knobs_by_node_id_and_the_description_wins);
    RUN(test_c_a_node_id_that_comes_back_with_another_type_gets_knobs_of_its_own);
    RUN(test_c_shared_resources_are_made_once_per_node_and_instance_state_once_per_instance);
    RUN(test_c_installing_the_same_graph_again_keeps_each_nodes_shared_resource_and_a_new_node_gets_one);
    RUN(test_c_the_engine_cannot_be_freed_while_an_instance_exists);
    RUN(test_c_actions_reach_the_node_types_on_action_handler);
    RUN(test_c_an_instance_made_before_another_graph_was_installed_adopts_it_when_a_node_changes_type_and_the_old_node_goes_when_unused);
    RUN(test_c_the_functions_refuse_null_arguments_without_crashing);
    RUN(test_c_running_out_of_memory_at_any_point_fails_cleanly_and_leaks_nothing);
}
