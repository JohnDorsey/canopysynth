/* Tests: the boundary nodes and the host calls that use them (design section 10): writing a boundary inlet by name, reading through a boundary
   outlet by name, unique non-empty names, listing, and what a value belongs to. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <process.h>
#include "support.h"

static void set_name(CanopyGraph *g, int64_t node, const char *name)
{
    CHECK_INT(canopy_graph_set_string(g, node, "name", name), CANOPY_OK);
}

/* inlet 1 named in_name -> outlet 2 named out_name */
static void pair(Rig *rig, const char *in_name, const char *out_name)
{
    rig_open(rig);
    rig_node(rig, 1, "boundary_inlet");
    rig_node(rig, 2, "boundary_outlet");
    rig_connect(rig, 1, "out", 2, "in");
    set_name(rig->graph, 1, in_name);
    set_name(rig->graph, 2, out_name);
    rig_install(rig);
}

static void test_c_the_boundary_node_types_are_built_in_and_in_every_new_registry(void)
{
    CanopyRegistry *registry = canopy_registry_new();
    const CanopyNodeType *in = canopy_registry_find(registry, "boundary_inlet"), *out = canopy_registry_find(registry, "boundary_outlet");
    CHECK(registry != NULL && in != NULL && out != NULL);
    if (in && out) {
        CHECK(in->n_inlets == 0 && in->n_outlets == 1 && strcmp(in->outlets[0].key, "out") == 0);
        CHECK(out->n_inlets == 1 && out->n_outlets == 0 && strcmp(out->inlets[0].key, "in") == 0 && out->inlets[0].default_knob == 0.0f);
        CHECK(in->n_settings == 1 && out->n_settings == 1 && strcmp(in->settings[0].key, "name") == 0 && strcmp(out->settings[0].key, "name") == 0);
        CHECK(in->settings[0].kind == CANOPY_SETTING_STRING && strcmp(in->settings[0].default_string, "") == 0);
        CHECK((in->flags & CANOPY_FLAG_BOUNDARY_SLOT) && (in->flags & CANOPY_FLAG_BOUNDARY_NODE) && (in->flags & CANOPY_FLAG_REALTIME_SAFE));
        CHECK(!(out->flags & CANOPY_FLAG_BOUNDARY_SLOT) && (out->flags & CANOPY_FLAG_BOUNDARY_NODE) && (out->flags & CANOPY_FLAG_REALTIME_SAFE));
        CHECK(in->n_widgets == 1 && in->widgets[0].kind == CANOPY_WIDGET_TEXT && strcmp(in->widgets[0].setting, "name") == 0);
        CHECK(out->n_widgets == 1 && out->widgets[0].kind == CANOPY_WIDGET_TEXT);
        CHECK(in->scratch_buffers == 0 && out->scratch_buffers == 0);
    }
    canopy_registry_free(registry);
    registry = canopy_registry_new_empty();
    CHECK(canopy_registry_count(registry) == 0);
    canopy_registry_free(registry);
}

static void test_c_a_boundary_inlet_starts_at_zero_and_gives_what_the_host_wrote_for_any_time_and_span(void)
{
    Rig rig;
    Guarded g = guarded_new(100);
    static const int64_t times[] = {0, -5, 123456789012345LL, INT64_MAX, INT64_MIN};
    int i;
    pair(&rig, "intensity", "song");
    CHECK(canopy_instance_read_at(rig.instance, "song", 77) == 0.0f);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "intensity", 0.7f), CANOPY_OK);
    for (i = 0; i < 5; i++) CHECK(canopy_instance_read_at(rig.instance, "song", times[i]) == 0.7f);
    CHECK_INT(canopy_instance_read_span(rig.instance, "song", 0, 1000000, 100, g.data), CANOPY_OK);
    for (i = 0; i < 100; i++) CHECK(g.data[i] == 0.7f);
    guarded_reset(&g);
    CHECK_INT(canopy_instance_read_span(rig.instance, "song", 5000, -5000, 100, g.data), CANOPY_OK);     /* a reversed span: the same value */
    for (i = 0; i < 100; i++) CHECK(g.data[i] == 0.7f);
    CHECK(guarded_guards_intact(&g));
    guarded_free(&g);
    rig_close(&rig);
}

static void test_c_a_boundary_inlet_accepts_any_float_and_clamps_nothing(void)
{
    Rig rig;
    static const float values[] = {1.0e30f, -1.0e30f, INFINITY, -INFINITY, -0.0f, 2.5f, -7.0f, 1.0e-40f};
    float span[4];
    int i;
    pair(&rig, "x", "y");
    for (i = 0; i < 8; i++) {
        CHECK_INT(canopy_engine_set_boundary(rig.engine, "x", values[i]), CANOPY_OK);
        CHECK(float_bits(canopy_instance_read_at(rig.instance, "y", 0)) == float_bits(values[i]));
        CHECK_INT(canopy_instance_read_span(rig.instance, "y", 0, 40, 4, span), CANOPY_OK);
        CHECK(float_bits(span[0]) == float_bits(values[i]) && float_bits(span[3]) == float_bits(values[i]));
    }
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "x", NAN), CANOPY_OK);
    CHECK(isnan(canopy_instance_read_at(rig.instance, "y", 0)));
    rig_close(&rig);
}

static void test_c_a_boundary_inlet_feeds_the_graph_and_a_boundary_outlet_reads_what_comes_out(void)
{
    Rig rig;
    float span[8];
    int i;
    rig_open(&rig);
    rig_node(&rig, 1, "boundary_inlet");
    rig_node(&rig, 2, "test.gain");
    rig_node(&rig, 3, "boundary_outlet");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 3, "in");
    set_name(rig.graph, 1, "level");
    set_name(rig.graph, 3, "scaled");
    CHECK_INT(canopy_graph_set_knob(rig.graph, 2, "gain", 0.5f), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "level", 0.5f), CANOPY_OK);
    CHECK(canopy_instance_read_at(rig.instance, "scaled", 999) == 0.25f);
    CHECK_INT(canopy_instance_read_span(rig.instance, "scaled", 0, 80, 8, span), CANOPY_OK);
    for (i = 0; i < 8; i++) CHECK(span[i] == 0.25f);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "level", 40.0f), CANOPY_OK);          /* beyond -1..1 on the way through the graph too */
    CHECK(canopy_instance_read_at(rig.instance, "scaled", 0) == 20.0f);
    rig_close(&rig);
}

static void test_c_an_unconnected_boundary_outlet_gives_its_knob(void)
{
    Rig rig;
    float span[8];
    int i;
    rig_open(&rig);
    rig_node(&rig, 2, "boundary_outlet");
    set_name(rig.graph, 2, "free");
    rig_install(&rig);
    CHECK(canopy_instance_read_at(rig.instance, "free", 5) == 0.0f);                       /* the inlet's default knob position */
    CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 0, 0.25f), CANOPY_OK);
    CHECK(canopy_instance_read_at(rig.instance, "free", -5) == 0.25f);
    CHECK_INT(canopy_instance_read_span(rig.instance, "free", 0, 8, 8, span), CANOPY_OK);
    for (i = 0; i < 8; i++) CHECK(span[i] == 0.25f);
    rig_close(&rig);
}

static void test_c_unknown_names_and_the_wrong_kind_are_refused_with_the_documented_statuses(void)
{
    Rig rig;
    Guarded g = guarded_new(16);
    pair(&rig, "in_name", "out_name");
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "nope", 1.0f), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "out_name", 1.0f), CANOPY_ERR_NODE);   /* a boundary outlet cannot be written */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "In_name", 1.0f), CANOPY_ERR_NODE);    /* names are case-sensitive */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "in_name ", 1.0f), CANOPY_ERR_NODE);   /* and compared byte for byte */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, NULL, 1.0f), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_boundary(NULL, "in_name", 1.0f), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "in_name", 0.5f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "in", 1.0f), CANOPY_ERR_NODE);         /* a start of a name is not the name... */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "in_name_and_more", 1.0f), CANOPY_ERR_NODE);   /* ...nor is a name with more after it */
    CHECK(canopy_instance_read_at(rig.instance, "out", 0) == 0.0f && canopy_instance_read_at(rig.instance, "out_name_x", 0) == 0.0f);
    CHECK(canopy_instance_read_at(rig.instance, "out_name", 0) == 0.5f);
    CHECK(canopy_instance_read_at(rig.instance, "nope", 0) == 0.0f);
    CHECK(canopy_instance_read_at(rig.instance, "in_name", 0) == 0.0f);                    /* a boundary inlet cannot be read, whatever it holds */
    CHECK(canopy_instance_read_at(rig.instance, NULL, 0) == 0.0f);
    CHECK(canopy_instance_read_at(NULL, "out_name", 0) == 0.0f);
    CHECK_INT(canopy_instance_read_span(rig.instance, "nope", 0, 16, 16, g.data), CANOPY_ERR_NODE);
    CHECK(guarded_all_zero(&g));
    guarded_reset(&g);
    CHECK_INT(canopy_instance_read_span(rig.instance, "in_name", 0, 16, 16, g.data), CANOPY_ERR_NODE);
    CHECK(guarded_all_zero(&g));
    guarded_reset(&g);
    CHECK_INT(canopy_instance_read_span(rig.instance, NULL, 0, 16, 16, g.data), CANOPY_ERR_ARGUMENT);
    CHECK(guarded_all_zero(&g));
    guarded_reset(&g);
    CHECK_INT(canopy_instance_read_span(NULL, "out_name", 0, 16, 16, g.data), CANOPY_ERR_ARGUMENT);
    CHECK(guarded_all_zero(&g));
    guarded_reset(&g);
    CHECK_INT(canopy_instance_read_span(rig.instance, "out_name", 0, 16, 0, g.data), CANOPY_ERR_N);          /* the checks of every span request, in order */
    CHECK_INT(guarded_unwritten(&g), 16);
    CHECK_INT(canopy_instance_read_span(rig.instance, "out_name", 0, 16, 16, NULL), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_instance_read_span(rig.instance, "out_name", -2, INT64_MAX, 16, g.data), CANOPY_ERR_OVERFLOW);
    CHECK(guarded_all_zero(&g));
    CHECK(guarded_guards_intact(&g));
    guarded_free(&g);
    rig_close(&rig);
}

/* the graph of a node 1 (boundary inlet), 2 (outlet), 3 (inlet), 4 (outlet) with the given names (NULL: left unnamed) */
static CanopyGraph *four(const char *n1, const char *n2, const char *n3, const char *n4)
{
    CanopyGraph *g = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(g, 1, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 2, "boundary_outlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 3, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 4, "boundary_outlet"), CANOPY_OK);
    if (n1) set_name(g, 1, n1);
    if (n2) set_name(g, 2, n2);
    if (n3) set_name(g, 3, n3);
    if (n4) set_name(g, 4, n4);
    return g;
}

static void test_c_an_empty_or_repeated_boundary_name_is_a_compile_fault_and_the_old_graph_stays(void)
{
    Rig rig;
    CanopyGraph *bad;
    static const char *const cases[][4] = {
        {"a", "b", "c", NULL},          /* node 4 has no name */
        {"a", "b", "c", ""},            /* or an empty one */
        {"a", "b", "a", "d"},           /* two inlets with one name */
        {"a", "b", "c", "b"},           /* two outlets */
        {"a", "b", "c", "a"},           /* an inlet and an outlet */
        {"a", "a", "c", "d"},           /* (the other pair) */
    };
    static const char *const needles[] = {"node 4", "node 4", "\"a\"", "\"b\"", "\"a\"", "\"a\""};
    int i;
    pair(&rig, "keep", "kept");
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "keep", 0.5f), CANOPY_OK);
    for (i = 0; i < 6; i++) {
        bad = four(cases[i][0], cases[i][1], cases[i][2], cases[i][3]);
        CHECK_INT(canopy_engine_set_graph(rig.engine, bad), CANOPY_ERR_GRAPH);
        CHECK(strstr(canopy_engine_last_error(rig.engine), "boundary") != NULL);
        CHECK(strstr(canopy_engine_last_error(rig.engine), needles[i]) != NULL);
        if (strstr(canopy_engine_last_error(rig.engine), needles[i]) == NULL) printf("    case %d: the message is: %s\n", i, canopy_engine_last_error(rig.engine));
        CHECK(canopy_instance_read_at(rig.instance, "kept", 0) == 0.5f);                  /* the installed graph keeps working */
        CHECK_INT(canopy_engine_boundary_count(rig.engine), 2);
        canopy_graph_free(bad);
    }
    bad = four("a", "b", "c", "d");                                                       /* and the neighbour that is fine */
    CHECK_INT(canopy_engine_set_graph(rig.engine, bad), CANOPY_OK);
    CHECK_INT(canopy_engine_boundary_count(rig.engine), 4);
    canopy_graph_free(bad);
    rig_close(&rig);
}

static void test_c_boundary_names_are_any_non_empty_text_compared_byte_for_byte(void)
{
    Rig rig;
    char longest[1001];
    CanopyGraph *g;
    int32_t length = 0;
    char buffer[2000];
    memset(longest, 'z', 1000);
    longest[1000] = '\0';
    rig_open(&rig);
    g = four("Song", "song", "so ng", "\xC3\xA9 \xE2\x99\xAA");                             /* case, a space, UTF-8 */
    CHECK_INT(canopy_engine_set_graph(rig.engine, g), CANOPY_OK);
    canopy_graph_free(g);
    CHECK_INT(canopy_engine_boundary_count(rig.engine), 4);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "Song", 0.25f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "so ng", 0.5f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "song", 0.5f), CANOPY_ERR_NODE);      /* "song" is an outlet */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "\xC3\xA9 \xE2\x99\xAA", 0.5f), CANOPY_ERR_NODE);   /* also an outlet */
    g = four(longest, "b", "c", "d");
    CHECK_INT(canopy_engine_set_graph(rig.engine, g), CANOPY_OK);
    canopy_graph_free(g);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, longest, 1.0f), CANOPY_OK);
    CHECK_INT(canopy_engine_boundary_count(rig.engine), 4);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 3, buffer, (int32_t)sizeof buffer, &length, NULL, NULL), CANOPY_OK);   /* "z..." sorts last */
    CHECK_INT(length, 1000);
    CHECK(strcmp(buffer, longest) == 0);
    rig_close(&rig);
}

static void test_c_the_boundary_nodes_are_listed_sorted_by_name_with_kind_and_node_id(void)
{
    Rig rig;
    CanopyGraph *g;
    char name[16];
    int32_t length = -1, kind = -1;
    int64_t id = -1;
    rig_open(&rig);
    CHECK_INT(canopy_engine_boundary_count(rig.engine), 0);                                 /* no graph yet */
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 0, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_ERR_INDEX);
    CHECK_INT(canopy_engine_boundary_count(NULL), 0);
    g = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(g, 5, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 9, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 2, "boundary_outlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, 7, "test.const"), CANOPY_OK);                        /* not a boundary node */
    set_name(g, 5, "zeta");
    set_name(g, 9, "alpha");
    set_name(g, 2, "Mid");
    CHECK_INT(canopy_engine_set_graph(rig.engine, g), CANOPY_OK);
    canopy_graph_free(g);
    CHECK_INT(canopy_engine_boundary_count(rig.engine), 3);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 0, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_OK);          /* byte order: capitals first */
    CHECK(strcmp(name, "Mid") == 0 && length == 3 && kind == CANOPY_BOUNDARY_OUTLET && id == 2);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 1, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_OK);
    CHECK(strcmp(name, "alpha") == 0 && length == 5 && kind == CANOPY_BOUNDARY_INLET && id == 9);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 2, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_OK);
    CHECK(strcmp(name, "zeta") == 0 && length == 4 && kind == CANOPY_BOUNDARY_INLET && id == 5);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 3, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_ERR_INDEX);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, -1, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_ERR_INDEX);
    /* a buffer that is too small: cut and NUL-terminated, the full length reported; no buffer at all: only the length */
    memset(name, 'q', sizeof name);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 1, name, 3, &length, NULL, NULL), CANOPY_OK);
    CHECK(strcmp(name, "al") == 0 && length == 5 && name[3] == 'q');
    length = -1;
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 2, NULL, 0, &length, NULL, NULL), CANOPY_OK);
    CHECK_INT(length, 4);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 2, NULL, 0, NULL, NULL, NULL), CANOPY_OK);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 2, NULL, 5, &length, &kind, &id), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_boundary_at(rig.engine, 2, name, -1, &length, &kind, &id), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_boundary_at(NULL, 0, name, (int32_t)sizeof name, &length, &kind, &id), CANOPY_ERR_ARGUMENT);
    rig_close(&rig);
}

static void test_c_a_boundary_value_belongs_to_the_node_so_it_survives_renaming_and_is_lost_with_the_node(void)
{
    Rig rig;
    CanopyGraph *renamed, *without;
    pair(&rig, "a", "out");
    renamed = canopy_graph_new();
    without = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(renamed, 1, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(renamed, 2, "boundary_outlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(renamed, 1, "out", 2, "in"), CANOPY_OK);
    set_name(renamed, 1, "b");
    set_name(renamed, 2, "out");
    CHECK_INT(canopy_graph_add_node(without, 2, "boundary_outlet"), CANOPY_OK);
    set_name(without, 2, "out");
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "a", 0.7f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, renamed), CANOPY_OK);
    CHECK(canopy_instance_read_at(rig.instance, "out", 0) == 0.7f);                         /* the node is the same node: its value stays */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "a", 1.0f), CANOPY_ERR_NODE);          /* but the old name is gone */
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "b", 0.9f), CANOPY_OK);
    CHECK(canopy_instance_read_at(rig.instance, "out", 0) == 0.9f);
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);                     /* the node leaves... */
    CHECK(canopy_instance_read_at(rig.instance, "out", 0) == 0.0f);                         /* (the outlet's inlet is a knob now) */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);                   /* ...and comes back as a new node: 0.0 */
    CHECK(canopy_instance_read_at(rig.instance, "out", 0) == 0.0f);
    canopy_graph_free(renamed);
    canopy_graph_free(without);
    rig_close(&rig);
}

static void test_c_two_boundary_inlets_keep_values_of_their_own_and_an_instance_adopts_a_new_graph_before_looking_the_name_up(void)
{
    Rig rig;
    CanopyGraph *second;
    rig_open(&rig);
    second = canopy_graph_new();
    rig_node(&rig, 1, "boundary_inlet");
    rig_node(&rig, 2, "boundary_inlet");
    rig_node(&rig, 3, "boundary_outlet");
    rig_node(&rig, 4, "boundary_outlet");
    rig_connect(&rig, 1, "out", 3, "in");
    rig_connect(&rig, 2, "out", 4, "in");
    set_name(rig.graph, 1, "one");
    set_name(rig.graph, 2, "two");
    set_name(rig.graph, 3, "three");
    set_name(rig.graph, 4, "four");
    rig_install(&rig);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "one", 0.1f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "two", 0.2f), CANOPY_OK);
    CHECK(canopy_instance_read_at(rig.instance, "three", 0) == 0.1f && canopy_instance_read_at(rig.instance, "four", 0) == 0.2f);
    /* the second graph swaps the wiring and names a new outlet; the instance has not been asked since the install */
    CHECK_INT(canopy_graph_add_node(second, 1, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 2, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 3, "boundary_outlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 5, "boundary_outlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 2, "out", 3, "in"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 1, "out", 5, "in"), CANOPY_OK);
    set_name(second, 1, "one");
    set_name(second, 2, "two");
    set_name(second, 3, "three");
    set_name(second, 5, "five");
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK(canopy_instance_read_at(rig.instance, "five", 0) == 0.1f);                        /* a name that only the new graph has */
    CHECK(canopy_instance_read_at(rig.instance, "three", 0) == 0.2f);
    CHECK(canopy_instance_read_at(rig.instance, "four", 0) == 0.0f);                        /* and one that it dropped */
    canopy_graph_free(second);
    rig_close(&rig);
}

static void test_c_a_span_read_is_the_first_query_after_an_install_and_still_sees_the_new_graph(void)
{
    Rig rig;
    CanopyGraph *second;
    float span[4];
    pair(&rig, "in", "old");
    second = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(second, 1, "boundary_inlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 2, "boundary_outlet"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 1, "out", 2, "in"), CANOPY_OK);
    set_name(second, 1, "in");
    set_name(second, 2, "new");
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "in", 0.5f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(canopy_instance_read_span(rig.instance, "new", 0, 4, 4, span), CANOPY_OK);      /* the instance has not queried since the install */
    CHECK(span[0] == 0.5f && span[3] == 0.5f);
    CHECK_INT(canopy_instance_graph_serial(rig.instance), canopy_engine_graph_serial(rig.engine));
    CHECK_INT(canopy_instance_read_span(rig.instance, "old", 0, 4, 4, span), CANOPY_ERR_NODE);   /* and the name of the old graph is gone */
    canopy_graph_free(second);
    rig_close(&rig);
}

static void test_c_every_write_by_name_changes_the_stamp_of_what_is_downstream(void)
{
    Rig rig;
    uint64_t first, second, third;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "boundary_inlet");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    set_name(rig.graph, 1, "x");
    rig_install(&rig);
    (void)canopy_instance_inlet_at(rig.instance, 9, 0, 0);
    first = support_stamps[0];
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "x", 0.5f), CANOPY_OK);
    (void)canopy_instance_inlet_at(rig.instance, 9, 0, 0);
    second = support_stamps[0];
    CHECK_INT(canopy_engine_set_boundary(rig.engine, "x", 0.5f), CANOPY_OK);                  /* the same value again is still a write */
    (void)canopy_instance_inlet_at(rig.instance, 9, 0, 0);
    third = support_stamps[0];
    CHECK(first != 0 && second != first && third != second && third != first);
    rig_close(&rig);
}

/* ---- threads: a host writes while other threads read; every value read is one that was written, in order ---- */

typedef struct {
    CanopyEngine *engine;
    volatile LONG *stop;
    volatile LONG reads, bad;
} Watcher;

static unsigned __stdcall watcher_main(void *argument)
{
    Watcher *watcher = (Watcher *)argument;
    CanopyInstance *instance = canopy_engine_new_instance(watcher->engine);
    float last = 0.0f, span[16];
    int i;
    if (!instance) {
        InterlockedIncrement(&watcher->bad);
        return 0;
    }
    while (!*watcher->stop) {
        float now = canopy_instance_read_at(instance, "out", 0);
        if (now < last) InterlockedIncrement(&watcher->bad);                               /* the writer only counts up: a value read never goes back */
        last = now;
        if (canopy_instance_read_span(instance, "out", 0, 160, 16, span) != CANOPY_OK) InterlockedIncrement(&watcher->bad);
        for (i = 1; i < 16; i++)
            if (span[i] != span[0]) InterlockedIncrement(&watcher->bad);                   /* one span, one value */
        if (span[0] < last) InterlockedIncrement(&watcher->bad);
        last = span[0] > last ? span[0] : last;
        InterlockedIncrement(&watcher->reads);
    }
    canopy_instance_free(instance);
    return 0;
}

static void test_c_a_host_write_is_seen_whole_by_readers_in_other_threads_and_never_goes_back(void)
{
    enum { WATCHERS = 3, WRITES = 3000 };
    Rig rig;
    volatile LONG stop = 0;
    Watcher watchers[WATCHERS];
    HANDLE handles[WATCHERS];
    long long bad = 0;
    int i, w;
    pair(&rig, "in", "out");
    for (w = 0; w < WATCHERS; w++) {
        watchers[w].engine = rig.engine;
        watchers[w].stop = &stop;
        watchers[w].reads = watchers[w].bad = 0;
        handles[w] = (HANDLE)_beginthreadex(NULL, 0, watcher_main, &watchers[w], 0, NULL);
    }
    for (i = 1; i <= WRITES; i++) {
        CHECK_INT(canopy_engine_set_boundary(rig.engine, "in", (float)i), CANOPY_OK);
        if (i % 50 == 0) {                                                                  /* let every watcher read between the writes */
            LONG before[WATCHERS];
            ULONGLONG deadline = GetTickCount64() + 5000;
            int waiting = 1;
            for (w = 0; w < WATCHERS; w++) before[w] = watchers[w].reads;
            while (waiting && GetTickCount64() < deadline) {
                waiting = 0;
                for (w = 0; w < WATCHERS; w++)
                    if (watchers[w].reads <= before[w]) waiting = 1;
                if (waiting) Sleep(0);
            }
            CHECK(!waiting);
            if (waiting) break;
        }
    }
    InterlockedExchange(&stop, 1);
    WaitForMultipleObjects(WATCHERS, handles, TRUE, INFINITE);
    for (w = 0; w < WATCHERS; w++) {
        bad += watchers[w].bad;
        CloseHandle(handles[w]);
    }
    CHECK_INT(bad, 0);
    CHECK(canopy_instance_read_at(rig.instance, "out", 0) == (float)WRITES);                /* a read that starts after the last write sees it */
    rig_close(&rig);
}

void register_test_boundary(void)
{
    RUN(test_c_the_boundary_node_types_are_built_in_and_in_every_new_registry);
    RUN(test_c_a_boundary_inlet_starts_at_zero_and_gives_what_the_host_wrote_for_any_time_and_span);
    RUN(test_c_a_boundary_inlet_accepts_any_float_and_clamps_nothing);
    RUN(test_c_a_boundary_inlet_feeds_the_graph_and_a_boundary_outlet_reads_what_comes_out);
    RUN(test_c_an_unconnected_boundary_outlet_gives_its_knob);
    RUN(test_c_unknown_names_and_the_wrong_kind_are_refused_with_the_documented_statuses);
    RUN(test_c_an_empty_or_repeated_boundary_name_is_a_compile_fault_and_the_old_graph_stays);
    RUN(test_c_boundary_names_are_any_non_empty_text_compared_byte_for_byte);
    RUN(test_c_the_boundary_nodes_are_listed_sorted_by_name_with_kind_and_node_id);
    RUN(test_c_a_boundary_value_belongs_to_the_node_so_it_survives_renaming_and_is_lost_with_the_node);
    RUN(test_c_two_boundary_inlets_keep_values_of_their_own_and_an_instance_adopts_a_new_graph_before_looking_the_name_up);
    RUN(test_c_a_span_read_is_the_first_query_after_an_install_and_still_sees_the_new_graph);
    RUN(test_c_every_write_by_name_changes_the_stamp_of_what_is_downstream);
    RUN(test_c_a_host_write_is_seen_whole_by_readers_in_other_threads_and_never_goes_back);
}
