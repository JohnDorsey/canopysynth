/* Tests: generation numbers and what a node that keeps history sees of them (design section 7): the upstream stamp, the boundary slot, shared
   resource and setting generations; and the hidden test filter, whose checkpoints must never be stale and must be used when they are not. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "support.h"

/* node 9 = test.sink; its inlets 0 and 1 read what the stamp nodes (tags 0 and 1) pass on */
static uint64_t read_stamp(Rig *rig, int32_t sink_inlet, int tag)
{
    support_stamps[tag] = 0;
    (void)canopy_instance_inlet_at(rig->instance, 9, sink_inlet, 0);
    return support_stamps[tag];
}

static void install_again(Rig *rig)                                        /* the description as it is now, to the same engine */
{
    int32_t status = canopy_engine_set_graph(rig->engine, rig->graph);
    CHECK_INT(status, CANOPY_OK);
    if (status != CANOPY_OK) printf("    engine says: %s\n", canopy_engine_last_error(rig->engine));
}

/* two separate chains: gain(1) -> stamp(2, tag 0) -> sink.in0 and gain(3) -> stamp(4, tag 1) -> sink.in1; every gain inlet is a knob */
static void two_chains(Rig *rig)
{
    rig_open(rig);
    support_counters_reset();
    rig_node(rig, 1, "test.gain");
    rig_node(rig, 2, "test.stamp");
    rig_node(rig, 3, "test.gain");
    rig_node(rig, 4, "test.stamp");
    rig_node(rig, 9, "test.sink");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 9, "in0");
    rig_connect(rig, 3, "out", 4, "in");
    rig_connect(rig, 4, "out", 9, "in1");
    CHECK_INT(canopy_graph_set_int(rig->graph, 4, "tag", 1), CANOPY_OK);
    rig_install(rig);
}

static void test_c_the_stamp_is_stable_while_nothing_upstream_changes_and_differs_between_nodes(void)
{
    Rig rig;
    uint64_t s0, s1;
    two_chains(&rig);
    s0 = read_stamp(&rig, 0, 0);
    s1 = read_stamp(&rig, 1, 1);
    CHECK(s0 != 0 && s1 != 0 && s0 != s1);                                  /* two identical-looking chains are still different sources */
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);    /* asking again changes nothing */
    {
        CanopyInstance *other = canopy_engine_new_instance(rig.engine);
        CHECK(other != NULL);
        if (other) {
            support_stamps[0] = 0;
            (void)canopy_instance_inlet_at(other, 9, 0, 0);
            CHECK(support_stamps[0] == s0);                                  /* another instance sees the same digest */
            canopy_instance_free(other);
        }
    }
    install_again(&rig);                                                     /* the very same description again */
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);
    rig_close(&rig);
}

static void test_c_the_context_functions_of_this_step_tolerate_a_null_context(void)
{
    CHECK(canopy_ctx_upstream_stamp(NULL) == 0);
    canopy_ctx_shared_changed(NULL);                                         /* nothing to change, and nothing to crash */
    CHECK(canopy_ctx_boundary_value(NULL) == 0.0f);
}

static void test_c_a_knob_move_changes_the_stamp_of_what_is_downstream_and_of_nothing_else(void)
{
    Rig rig;
    uint64_t s0, s1, s0b, s1b;
    two_chains(&rig);
    s0 = read_stamp(&rig, 0, 0);
    s1 = read_stamp(&rig, 1, 1);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 0, 0.3f), CANOPY_OK);    /* the free input knob of gain 1: upstream of stamp 2 only */
    s0b = read_stamp(&rig, 0, 0);
    s1b = read_stamp(&rig, 1, 1);
    CHECK(s0b != s0);
    CHECK(s1b == s1);
    s0 = s0b;
    CHECK_INT(canopy_engine_set_knob(rig.engine, 3, 1, 0.5f), CANOPY_OK);    /* the gain knob of gain 3: upstream of stamp 4 only */
    s0b = read_stamp(&rig, 0, 0);
    s1b = read_stamp(&rig, 1, 1);
    CHECK(s0b == s0);
    CHECK(s1b != s1);
    s1 = s1b;
    CHECK_INT(canopy_engine_set_knob(rig.engine, 3, 1, 0.5f), CANOPY_OK);    /* writing the same position is still a write */
    CHECK(read_stamp(&rig, 1, 1) != s1);
    s1 = read_stamp(&rig, 1, 1);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 0, 0.9f), CANOPY_OK);    /* the knob of a CONNECTED inlet is not a source: nothing reads it */
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 9, 1, -0.5f), CANOPY_OK);   /* the sink is downstream of both, not upstream of either */
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);
    rig_close(&rig);
}

static void test_c_the_stamp_sees_through_any_number_of_nodes_and_through_fan_in_and_out(void)
{
    Rig rig;
    uint64_t before, after;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "test.gain");               /* 1 -> 2 -> 3 -> stamp 6; 4 also feeds 3 (fan-in at the sum); 1 also feeds 5 (fan-out) */
    rig_node(&rig, 2, "test.shift");
    rig_node(&rig, 3, "test.sum");
    rig_node(&rig, 4, "test.gain");
    rig_node(&rig, 5, "test.shift");
    rig_node(&rig, 6, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 3, "a");
    rig_connect(&rig, 4, "out", 3, "b");
    rig_connect(&rig, 3, "out", 6, "in");
    rig_connect(&rig, 6, "out", 9, "in0");
    rig_connect(&rig, 1, "out", 5, "in");
    rig_install(&rig);
    before = read_stamp(&rig, 0, 0);
    CHECK_INT(canopy_engine_set_knob(rig.engine, 4, 0, 0.1f), CANOPY_OK);    /* a knob three nodes away, on the other branch */
    after = read_stamp(&rig, 0, 0);
    CHECK(after != before);
    before = after;
    CHECK_INT(canopy_engine_set_knob(rig.engine, 1, 1, 0.1f), CANOPY_OK);    /* a knob at the head of the long branch */
    after = read_stamp(&rig, 0, 0);
    CHECK(after != before);
    rig_close(&rig);
}

static void test_c_a_boundary_write_changes_the_stamp_downstream_and_accepts_any_float(void)
{
    Rig rig;
    uint64_t s0, s1, s0b;
    float read_back[4] = {0, 0, 0, 0}, wanted[4] = {1.0e30f, -1.0e30f, 0.0f, 0.0f};
    int i;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 5, "test_boundary");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 3, "test.gain");
    rig_node(&rig, 4, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 5, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    rig_connect(&rig, 3, "out", 4, "in");
    rig_connect(&rig, 4, "out", 9, "in1");
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "tag", 1), CANOPY_OK);
    rig_install(&rig);
    s0 = read_stamp(&rig, 0, 0);
    s1 = read_stamp(&rig, 1, 1);
    CHECK(canopy_instance_inlet_at(rig.instance, 9, 0, 0) == 0.0f);          /* a boundary value starts at 0 */
    CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 5, 0.7f), CANOPY_OK);
    CHECK(canopy_instance_inlet_at(rig.instance, 9, 0, 12345) == 0.7f);      /* the same value for any t */
    s0b = read_stamp(&rig, 0, 0);
    CHECK(s0b != s0);
    CHECK(read_stamp(&rig, 1, 1) == s1);                                     /* the other chain is untouched */
    CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 5, 0.7f), CANOPY_OK);
    CHECK(read_stamp(&rig, 0, 0) != s0b);                                    /* a write is a write */
    wanted[2] = INFINITY;
    wanted[3] = -0.0f;
    for (i = 0; i < 4; i++) {
        CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 5, wanted[i]), CANOPY_OK);      /* any float, not clamped to -1..1 */
        read_back[i] = canopy_instance_inlet_at(rig.instance, 9, 0, 0);
        CHECK(float_bits(read_back[i]) == float_bits(wanted[i]));
    }
    CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 5, NAN), CANOPY_OK);
    CHECK(isnan(canopy_instance_inlet_at(rig.instance, 9, 0, 0)));
    CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 77, 1.0f), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 3, 1.0f), CANOPY_ERR_ARGUMENT);   /* a gain has no boundary slot */
    CHECK_INT(canopy_engine_set_boundary_value(NULL, 5, 1.0f), CANOPY_ERR_ARGUMENT);
    rig_close(&rig);
}

static void test_c_a_setting_change_in_a_new_graph_changes_the_stamp_but_an_identical_or_unrelated_graph_does_not(void)
{
    Rig rig;
    uint64_t s0, s1;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 3, "test.const");
    rig_node(&rig, 4, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    rig_connect(&rig, 3, "out", 4, "in");
    rig_connect(&rig, 4, "out", 9, "in1");
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "tag", 1), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    s0 = read_stamp(&rig, 0, 0);
    s1 = read_stamp(&rig, 1, 1);
    install_again(&rig);
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);     /* nothing changed */
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.5), CANOPY_OK);   /* the same value set again is not a change */
    install_again(&rig);
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.75), CANOPY_OK);  /* an upstream node's setting */
    install_again(&rig);
    CHECK(read_stamp(&rig, 0, 0) != s0);
    CHECK(read_stamp(&rig, 1, 1) == s1);
    s0 = read_stamp(&rig, 0, 0);
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "salt", 5), CANOPY_OK);       /* the node's own setting, which nothing even reads */
    install_again(&rig);
    CHECK(read_stamp(&rig, 0, 0) != s0);
    CHECK(read_stamp(&rig, 1, 1) == s1);
    s0 = read_stamp(&rig, 0, 0);
    rig_node(&rig, 7, "test.const");                                           /* a node nothing is connected to, with a setting of its own */
    CHECK_INT(canopy_graph_set_float(rig.graph, 7, "value", 3.0), CANOPY_OK);
    install_again(&rig);
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);       /* an unrelated addition */
    CHECK_INT(canopy_graph_set_float(rig.graph, 7, "value", 4.0), CANOPY_OK);
    install_again(&rig);
    CHECK(read_stamp(&rig, 0, 0) == s0 && read_stamp(&rig, 1, 1) == s1);       /* and an unrelated setting change */
    rig_close(&rig);
}

static uint64_t last_stamp;

/* installs the description as it is now and says whether the stamp of node 2 (downstream of node 1) moved because of it */
static int stamp_moved_by_installing(Rig *rig)
{
    uint64_t before = last_stamp;
    install_again(rig);
    last_stamp = read_stamp(rig, 0, 0);
    return last_stamp != before;
}

static void test_c_a_setting_of_any_kind_moves_the_stamp_when_its_value_differs_in_any_way_and_not_when_it_is_only_installed_again(void)
{
    Rig rig;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "test.config");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    rig_install(&rig);
    last_stamp = read_stamp(&rig, 0, 0);
    CHECK(!stamp_moved_by_installing(&rig));
    /* a string: another text, the same text in a new copy (another address), a longer one, a shorter one */
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "text", "b"), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "text", "b"), CANOPY_OK);
    CHECK(!stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "text", "bb"), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "text", "b"), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    /* a path */
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "file", "one.wav"), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "file", "one.wav"), CANOPY_OK);
    CHECK(!stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_string(rig.graph, 1, "file", "two.wav"), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    /* a choice, up and down */
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "mode", 2), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "mode", 2), CANOPY_OK);
    CHECK(!stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "mode", 1), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    /* a float, up and down, and a change of the sign of zero alone, which is a change of bits and may be one of behaviour */
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "level", 0.5), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "level", 0.5), CANOPY_OK);
    CHECK(!stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "level", 0.25), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "level", 0.0), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "level", -0.0), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "level", -0.0), CANOPY_OK);
    CHECK(!stamp_moved_by_installing(&rig));
    /* an integer, up and down */
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "count", 3), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "count", 3), CANOPY_OK);
    CHECK(!stamp_moved_by_installing(&rig));
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "count", 2), CANOPY_OK);
    CHECK(stamp_moved_by_installing(&rig));
    rig_close(&rig);
}

static void test_c_one_setting_changed_again_and_again_gives_every_value_a_stamp_of_its_own_also_when_it_goes_back(void)
{
    static const int64_t counts[] = {0, 10, 11, 12, 11, 10, 0, 12};
    uint64_t stamps[8];
    Rig rig;
    int i, j;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "test.config");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    for (i = 0; i < 8; i++) {
        CHECK_INT(canopy_graph_set_int(rig.graph, 1, "count", counts[i]), CANOPY_OK);
        if (i == 0) rig_install(&rig); else install_again(&rig);
        stamps[i] = read_stamp(&rig, 0, 0);
    }
    /* a stamp tells the data that was used, and each change gets a new generation number: no two installs, whatever the value, share one */
    for (i = 0; i < 8; i++)
        for (j = i + 1; j < 8; j++) CHECK(stamps[i] != stamps[j]);
    rig_close(&rig);
}

static void test_c_a_shared_resource_change_changes_the_stamp_downstream_only(void)
{
    Rig rig;
    uint64_t s0, s1;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "test.source");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 3, "test.source");
    rig_node(&rig, 4, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    rig_connect(&rig, 3, "out", 4, "in");
    rig_connect(&rig, 4, "out", 9, "in1");
    CHECK_INT(canopy_graph_set_int(rig.graph, 4, "tag", 1), CANOPY_OK);
    rig_install(&rig);
    s0 = read_stamp(&rig, 0, 0);
    s1 = read_stamp(&rig, 1, 1);
    CHECK(canopy_instance_inlet_at(rig.instance, 9, 0, 0) == 1.0f);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "bump"), CANOPY_OK);        /* the "open a file" of a real node */
    CHECK(canopy_instance_inlet_at(rig.instance, 9, 0, 0) == 2.0f);
    CHECK(read_stamp(&rig, 0, 0) != s0);
    CHECK(read_stamp(&rig, 1, 1) == s1);
    rig_close(&rig);
    CHECK_INT(support_shared_destroyed, 2);
}

static void test_c_rewiring_changes_the_stamp_even_when_no_generation_number_does(void)
{
    Rig rig;
    CanopyGraph *rewired;
    uint64_t s_a, s_b;
    rig_open(&rig);
    support_counters_reset();
    rewired = canopy_graph_new();
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 5, "test.const");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    CHECK_INT(canopy_graph_add_node(rewired, 1, "test.const"), CANOPY_OK);    /* the same nodes, but the stamp node reads node 5 instead of node 1 */
    CHECK_INT(canopy_graph_add_node(rewired, 5, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(rewired, 2, "test.stamp"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(rewired, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(rewired, 5, "out", 2, "in"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(rewired, 2, "out", 9, "in0"), CANOPY_OK);
    rig_install(&rig);
    s_a = read_stamp(&rig, 0, 0);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rewired), CANOPY_OK);
    s_b = read_stamp(&rig, 0, 0);
    CHECK(s_b != s_a);                                                         /* both consts have the same settings and generation numbers */
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK(read_stamp(&rig, 0, 0) == s_a);                                      /* and back: the same sources again, the same stamp */
    canopy_graph_free(rewired);
    rig_close(&rig);
}

static void test_c_rewiring_to_the_other_outlet_of_the_same_node_changes_the_stamp(void)
{
    Rig rig;
    CanopyGraph *other;
    uint64_t s_a, s_b;
    rig_open(&rig);
    support_counters_reset();
    other = canopy_graph_new();
    rig_node(&rig, 1, "test.time");                                            /* two outlets, a and b, and no generation numbers of their own */
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "a", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    CHECK_INT(canopy_graph_add_node(other, 1, "test.time"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(other, 2, "test.stamp"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(other, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(other, 1, "b", 2, "in"), CANOPY_OK);        /* the same node, the other outlet: other data */
    CHECK_INT(canopy_graph_connect(other, 2, "out", 9, "in0"), CANOPY_OK);
    rig_install(&rig);
    s_a = read_stamp(&rig, 0, 0);
    CHECK_INT(canopy_engine_set_graph(rig.engine, other), CANOPY_OK);
    s_b = read_stamp(&rig, 0, 0);
    CHECK(s_b != s_a);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK(read_stamp(&rig, 0, 0) == s_a);
    canopy_graph_free(other);
    rig_close(&rig);
}

static void test_c_a_source_that_leaves_and_comes_back_keeps_the_stamp_only_while_its_data_is_the_same(void)
{
    Rig rig;
    CanopyGraph *without;
    uint64_t s_a;
    rig_open(&rig);
    support_counters_reset();
    without = canopy_graph_new();
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 9, "in0");
    CHECK_INT(canopy_graph_add_node(without, 2, "test.stamp"), CANOPY_OK);    /* the same graph without node 1: the stamp node's inlet is a knob */
    CHECK_INT(canopy_graph_add_node(without, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(without, 2, "out", 9, "in0"), CANOPY_OK);
    rig_install(&rig);
    s_a = read_stamp(&rig, 0, 0);
    /* the instance has not queried since: it still holds the first graph, so node 1's data still exists when the third graph brings it back */
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK(read_stamp(&rig, 0, 0) == s_a);                                      /* same node, same data: what was computed from it is still right */
    /* now let the instance run on a graph without node 1 and release the old one: node 1 comes back as a NEW source */
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);
    CHECK(read_stamp(&rig, 0, 0) != s_a);                                      /* (the inlet is a knob now) */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    CHECK(read_stamp(&rig, 0, 0) != s_a);                                      /* a node of that ID, but a new one: the old stamp is not honoured */
    canopy_graph_free(without);
    rig_close(&rig);
}

static void test_c_a_loop_does_not_stop_the_stamps_from_being_made(void)
{
    Rig rig;
    rig_open(&rig);
    support_counters_reset();
    rig_node(&rig, 1, "test.stamp");
    rig_node(&rig, 2, "test.stamp");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in");
    rig_connect(&rig, 2, "out", 1, "in");                                      /* a loop */
    rig_connect(&rig, 2, "out", 9, "in0");
    CHECK_INT(canopy_graph_set_int(rig.graph, 1, "pass", 0), CANOPY_OK);       /* these nodes do not ask upstream, so the loop is never run */
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "pass", 0), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "tag", 1), CANOPY_OK);
    rig_install(&rig);
    CHECK(read_stamp(&rig, 0, 1) != 0);
    CHECK(read_stamp(&rig, 0, 1) == support_stamps[1]);
    rig_close(&rig);
}

/* ---- the hidden filter ---- */

typedef struct {
    int64_t rate;
    float initial;
    float coef;
    float (*input)(int64_t t);
    float *y;                                  /* y[0 .. last] */
    int64_t last;
} Ref;

static int64_t grid_ns(int64_t k, int64_t rate)                                /* the time of grid sample k, rounded half up (k >= 0) */
{
    return (2 * k * 1000000000LL + rate) / (2 * rate);
}

static float const_half(int64_t t)
{
    (void)t;
    return 0.5f;
}

static Ref ref_make(int64_t rate, float initial, float coef, float (*input)(int64_t), int64_t last)
{
    Ref r;
    float y = initial, a = fminf(fmaxf((coef + 1.0f) * 0.5f, 0.0f), 1.0f);
    int64_t k;
    r.rate = rate; r.initial = initial; r.coef = coef; r.input = input; r.last = last;
    r.y = (float *)malloc((size_t)(last + 1) * sizeof(float));
    for (k = 0; k <= last; k++) {
        float x = input(grid_ns(k, rate)), difference = x - y, step = a * difference;
        y = y + step;
        r.y[k] = y;
    }
    return r;
}

static float ref_y(const Ref *r, int64_t k)
{
    return k < 0 ? r->initial : r->y[k];
}

static float ref_out(const Ref *r, int64_t t)
{
    int64_t k = 0;
    double fraction = 0.0;
    float y0, y1;
    CHECK_INT(canopy_ns_to_frame_fraction(t, r->rate, &k, &fraction), CANOPY_OK);
    if (k + 1 > r->last) return 12345.0f;                                    /* beyond the table: a test bug, made loud */
    y0 = ref_y(r, k);
    y1 = ref_y(r, k + 1);
    return (float)((double)y0 + fraction * ((double)y1 - (double)y0));
}

static void ref_free(Ref *r)
{
    free(r->y);
    r->y = NULL;
}

/* source(1) -> filter(2) -> sink(3); the filter at rate Hz with checkpoints every `seconds` seconds, the given initial value, and the
   coefficient either as the knob of its coef inlet or, if coef_from_node, from a test.const (node 4) with that value connected to it */
static void filter_rig_with(Rig *rig, const char *source_type, int64_t rate, int64_t seconds, float initial, float coef, int coef_from_node)
{
    rig_open(rig);
    support_counters_reset();
    rig_node(rig, 1, source_type);
    rig_node(rig, 2, "test_filter");
    rig_node(rig, 3, "test.sink");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in0");
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "internal_sampling_rate", rate), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "checkpoint_seconds", seconds), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig->graph, 2, "initial", (double)initial), CANOPY_OK);
    if (coef_from_node) {
        rig_node(rig, 4, "test.const");
        rig_connect(rig, 4, "out", 2, "coef");
        CHECK_INT(canopy_graph_set_float(rig->graph, 4, "value", (double)coef), CANOPY_OK);
    } else {
        CHECK_INT(canopy_graph_set_knob(rig->graph, 2, "coef", coef), CANOPY_OK);
    }
    rig_install(rig);
}

static void filter_rig(Rig *rig, int64_t rate, int64_t seconds, float initial, float coef)      /* the source is test.saw */
{
    filter_rig_with(rig, "test.saw", rate, seconds, initial, coef, 0);
}

static uint32_t lcg_state;

static uint32_t lcg(void)
{
    lcg_state = lcg_state * 1664525u + 1013904223u;
    return lcg_state >> 8;
}

static int64_t random_time(int64_t low, int64_t high)                           /* a time in [low, high) ns */
{
    return low + (int64_t)(((uint64_t)lcg() * 16777216u + lcg()) % (uint64_t)(high - low));
}

static void test_c_the_filter_matches_a_plain_recomputation_at_random_times_in_any_order(void)
{
    Rig rig;
    Ref ref = ref_make(200, 0.25f, 0.2f, support_saw, 3200);
    int q;
    filter_rig(&rig, 200, 2, 0.25f, 0.2f);
    lcg_state = 12345;
    for (q = 0; q < 500; q++) {
        int64_t t = random_time(-2000000000LL, 15000000000LL);
        float got = canopy_instance_inlet_at(rig.instance, 3, 0, t);
        if (float_bits(got) != float_bits(ref_out(&ref, t))) {
            ctest_current_failed = 1;
            printf("    query %d at t=%lld ns: got %g, a plain recomputation says %g\n", q, (long long)t, got, ref_out(&ref, t));
            break;
        }
    }
    CHECK(canopy_instance_inlet_at(rig.instance, 3, 0, -5000000000LL) == 0.25f);       /* before t = 0 it is the initial value */
    ref_free(&ref);
    rig_close(&rig);
}

static void test_c_spans_of_any_density_and_direction_agree_with_the_plain_recomputation_and_with_point_queries(void)
{
    Rig rig;
    Ref ref = ref_make(200, -0.5f, -0.4f, support_saw, 3200);
    int q;
    filter_rig(&rig, 200, 2, -0.5f, -0.4f);
    lcg_state = 777;
    for (q = 0; q < 60; q++) {
        int64_t t0 = random_time(-1000000000LL, 14000000000LL), t1 = random_time(-1000000000LL, 14000000000LL);
        int64_t n = 1 + (int64_t)(lcg() % 300), i;
        Guarded g = guarded_new(n);
        if (q % 7 == 0) t1 = t0;
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 3, 0, t0, t1, n, g.data), CANOPY_OK);
        CHECK(guarded_guards_intact(&g));
        for (i = 0; i < n; i++) {
            int64_t t = 0;
            CHECK_INT(canopy_sample_time(t0, t1, n, i, &t), CANOPY_OK);
            if (float_bits(g.data[i]) != float_bits(ref_out(&ref, t)) ||
                float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, t)) != float_bits(g.data[i])) {
                ctest_current_failed = 1;
                printf("    span %d (t0=%lld t1=%lld n=%lld) sample %lld: %g, plain recomputation %g\n", q, (long long)t0, (long long)t1,
                       (long long)n, (long long)i, g.data[i], ref_out(&ref, t));
                break;
            }
        }
        guarded_free(&g);
    }
    ref_free(&ref);
    rig_close(&rig);
}

static void test_c_two_instances_answer_alike_whatever_each_was_asked_before(void)
{
    Rig rig;
    CanopyInstance *other;
    int q;
    filter_rig(&rig, 200, 2, 0.0f, 0.0f);
    other = canopy_engine_new_instance(rig.engine);
    CHECK(other != NULL);
    lcg_state = 4242;
    for (q = 0; other && q < 120; q++) {
        int64_t t = random_time(0, 12000000000LL);
        float a, b;
        (void)canopy_instance_inlet_at(rig.instance, 3, 0, random_time(0, 12000000000LL));    /* the first has been asked other things */
        a = canopy_instance_inlet_at(rig.instance, 3, 0, t);
        b = canopy_instance_inlet_at(other, 3, 0, t);                                         /* the second asks cold */
        if (float_bits(a) != float_bits(b)) {
            ctest_current_failed = 1;
            printf("    at t=%lld ns two instances disagree: %g and %g\n", (long long)t, a, b);
            break;
        }
    }
    if (other) canopy_instance_free(other);
    rig_close(&rig);
}

/* counter(1, tag 0) -> filter(2) -> sink(3): every step of the filter asks the counter once, so the counter counts steps */
static void counted_filter_rig(Rig *rig, int tag_offset)
{
    rig_open(rig);
    support_counters_reset();
    rig_node(rig, 1, "test.counter");
    rig_node(rig, 2, "test_filter");
    rig_node(rig, 3, "test.sink");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in0");
    CHECK_INT(canopy_graph_set_float(rig->graph, 1, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 1, "tag", tag_offset), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "internal_sampling_rate", 200), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "checkpoint_seconds", 2), CANOPY_OK);      /* a checkpoint every 400 samples */
    rig_install(rig);
}

static int steps_for(Rig *rig, int64_t k)                         /* answers a query at grid sample k exactly and says how many inputs it read */
{
    int before = support_counts[0];
    (void)canopy_instance_inlet_at(rig->instance, 3, 0, grid_ns(k, 200));
    return support_counts[0] - before;
}

static void test_c_checkpoints_are_used_so_that_an_earlier_or_repeated_query_does_not_start_from_zero(void)
{
    Rig rig;
    Ref ref = ref_make(200, 0.0f, 0.0f, const_half, 3200);
    int steps;
    counted_filter_rig(&rig, 0);
    steps = steps_for(&rig, 1050);
    CHECK(steps >= 1051 && steps <= 1100);                             /* the first query renders from t = 0 */
    CHECK_INT(steps_for(&rig, 1050), 0);                               /* asking again costs nothing */
    steps = steps_for(&rig, 1010);
    CHECK(steps > 0 && steps <= 402);                                  /* earlier: from the checkpoint at sample 799, not from 0 */
    CHECK(steps_for(&rig, 1011) <= 2);                                 /* the next sample: from where the last one stopped */
    steps = steps_for(&rig, 10);
    CHECK(steps > 0 && steps <= 13);                                   /* the start again: from the first checkpoint (the initial value) */
    steps = steps_for(&rig, 2000);
    CHECK(steps >= 1190 && steps <= 1210);                             /* ahead: from the last checkpoint made (sample 799) */
    CHECK(float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, grid_ns(2000, 200))) == float_bits(ref_out(&ref, grid_ns(2000, 200))));
    CHECK(float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, grid_ns(1050, 200))) == float_bits(ref_out(&ref, grid_ns(1050, 200))));
    ref_free(&ref);
    rig_close(&rig);
}

/* two filters, each with its own counter and its own free coef knob: counters tag 0 and 1 */
static void two_filters(Rig *rig)
{
    rig_open(rig);
    support_counters_reset();
    rig_node(rig, 1, "test.counter");
    rig_node(rig, 2, "test_filter");
    rig_node(rig, 4, "test.counter");
    rig_node(rig, 5, "test_filter");
    rig_node(rig, 3, "test.sink");
    rig_connect(rig, 1, "out", 2, "in");
    rig_connect(rig, 2, "out", 3, "in0");
    rig_connect(rig, 4, "out", 5, "in");
    rig_connect(rig, 5, "out", 3, "in1");
    CHECK_INT(canopy_graph_set_float(rig->graph, 1, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig->graph, 4, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 4, "tag", 1), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 2, "internal_sampling_rate", 200), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rig->graph, 5, "internal_sampling_rate", 200), CANOPY_OK);
    rig_install(rig);
}

static void query_both(Rig *rig, int64_t k)
{
    (void)canopy_instance_inlet_at(rig->instance, 3, 0, grid_ns(k, 200));
    (void)canopy_instance_inlet_at(rig->instance, 3, 1, grid_ns(k, 200));
}

static void test_c_an_edit_upstream_of_one_filter_makes_that_filter_forget_and_not_the_other(void)
{
    Rig rig;
    Ref changed = ref_make(200, 0.0f, 0.5f, const_half, 3200);
    float got;
    two_filters(&rig);
    query_both(&rig, 1000);
    CHECK(support_counts[0] >= 1000 && support_counts[1] >= 1000);
    support_counts[0] = support_counts[1] = 0;
    query_both(&rig, 1000);
    CHECK(support_counts[0] == 0 && support_counts[1] == 0);                  /* both remember */
    CHECK_INT(canopy_engine_set_knob(rig.engine, 2, 1, 0.5f), CANOPY_OK);     /* the coef knob of filter 2 only */
    query_both(&rig, 1000);
    CHECK(support_counts[0] >= 1000);                                         /* filter 2 starts again... */
    CHECK_INT(support_counts[1], 0);                                          /* ...and filter 5 does not notice */
    got = canopy_instance_inlet_at(rig.instance, 3, 0, grid_ns(1000, 200));
    CHECK(float_bits(got) == float_bits(ref_out(&changed, grid_ns(1000, 200))));       /* and it is right, not stale */
    ref_free(&changed);
    rig_close(&rig);
}

/* a filter fed a constant: the plain recomputation for any rate, initial value, coefficient and constant, at time t */
static float const_value;

static float const_input(int64_t t)
{
    (void)t;
    return const_value;
}

static float expected_const(int64_t rate, float initial, float coef, float value, int64_t t)
{
    int64_t k = 0;
    double fraction = 0.0;
    Ref r;
    float out;
    CHECK_INT(canopy_ns_to_frame_fraction(t, rate, &k, &fraction), CANOPY_OK);
    const_value = value;
    r = ref_make(rate, initial, coef, const_input, k + 2);
    out = ref_out(&r, t);
    ref_free(&r);
    return out;
}

static void test_c_a_setting_upstream_or_of_the_filter_itself_changed_by_a_new_graph_makes_the_filter_forget(void)
{
    Rig rig;
    int64_t t = grid_ns(900, 200) + 1234567;                  /* between two samples of the grid */
    float first, second;
    int before;
    counted_filter_rig(&rig, 0);
    first = canopy_instance_inlet_at(rig.instance, 3, 0, t);
    CHECK(float_bits(first) == float_bits(expected_const(200, 0.0f, 0.0f, 0.5f, t)));
    /* a setting of a node upstream */
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.9), CANOPY_OK);
    install_again(&rig);
    before = support_counts[0];
    second = canopy_instance_inlet_at(rig.instance, 3, 0, t);
    CHECK(support_counts[0] - before >= 900);                  /* it started again... */
    CHECK(float_bits(second) == float_bits(expected_const(200, 0.0f, 0.0f, 0.9f, t)));   /* ...and the answer is the new one, not a stale one */
    CHECK(float_bits(second) != float_bits(first));
    /* the filter's own setting: its initial value */
    CHECK_INT(canopy_graph_set_float(rig.graph, 2, "initial", 0.5), CANOPY_OK);
    install_again(&rig);
    before = support_counts[0];
    second = canopy_instance_inlet_at(rig.instance, 3, 0, t);
    CHECK(support_counts[0] - before >= 900);
    CHECK(float_bits(second) == float_bits(expected_const(200, 0.5f, 0.0f, 0.9f, t)));
    /* its internal sampling rate */
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "internal_sampling_rate", 100), CANOPY_OK);
    install_again(&rig);
    before = support_counts[0];
    second = canopy_instance_inlet_at(rig.instance, 3, 0, t);
    CHECK(support_counts[0] - before >= 400);
    CHECK(float_bits(second) == float_bits(expected_const(100, 0.5f, 0.0f, 0.9f, t)));
    /* its checkpoint interval: the answer does not change, but what was stored was stored for another interval */
    CHECK_INT(canopy_graph_set_int(rig.graph, 2, "checkpoint_seconds", 5), CANOPY_OK);
    install_again(&rig);
    before = support_counts[0];
    first = canopy_instance_inlet_at(rig.instance, 3, 0, t);
    CHECK(support_counts[0] - before >= 400);
    CHECK(float_bits(first) == float_bits(second));
    rig_close(&rig);
}

static void test_c_a_boundary_write_and_a_shared_resource_change_make_the_filter_forget(void)
{
    Rig rig;
    int64_t t = grid_ns(900, 200) + 1234567;
    int pass;
    for (pass = 0; pass < 2; pass++) {
        const char *source_type = pass == 0 ? "test_boundary" : "test.source";
        rig_open(&rig);
        support_counters_reset();
        rig_node(&rig, 1, source_type);
        rig_node(&rig, 2, "test_filter");
        rig_node(&rig, 3, "test.sink");
        rig_connect(&rig, 1, "out", 2, "in");
        rig_connect(&rig, 2, "out", 3, "in0");
        CHECK_INT(canopy_graph_set_int(rig.graph, 2, "internal_sampling_rate", 200), CANOPY_OK);
        CHECK_INT(canopy_graph_set_int(rig.graph, 2, "checkpoint_seconds", 2), CANOPY_OK);
        rig_install(&rig);
        if (pass == 0) {
            CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 1, 0.25f), CANOPY_OK);
            CHECK(float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, t)) == float_bits(expected_const(200, 0.0f, 0.0f, 0.25f, t)));
            CHECK_INT(canopy_engine_set_boundary_value(rig.engine, 1, 0.75f), CANOPY_OK);
            CHECK(float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, t)) == float_bits(expected_const(200, 0.0f, 0.0f, 0.75f, t)));
        } else {
            CHECK(float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, t)) == float_bits(expected_const(200, 0.0f, 0.0f, 1.0f, t)));
            CHECK_INT(canopy_engine_action(rig.engine, 1, "bump"), CANOPY_OK);
            CHECK(float_bits(canopy_instance_inlet_at(rig.instance, 3, 0, t)) == float_bits(expected_const(200, 0.0f, 0.0f, 2.0f, t)));
        }
        rig_close(&rig);
    }
}

static void test_c_installing_a_graph_that_changes_nothing_upstream_keeps_what_the_filter_has_computed(void)
{
    Rig rig;
    CanopyGraph *rewired;
    int before;
    counted_filter_rig(&rig, 0);
    rewired = canopy_graph_new();
    (void)steps_for(&rig, 1000);
    rig_node(&rig, 7, "test.const");                           /* an unrelated node joins */
    install_again(&rig);
    before = support_counts[0];
    (void)canopy_instance_inlet_at(rig.instance, 3, 0, grid_ns(1000, 200));
    CHECK_INT(support_counts[0] - before, 0);                  /* the instance adopted the new graph, and the filter's state came along intact */
    CHECK_INT(canopy_instance_graph_serial(rig.instance), canopy_engine_graph_serial(rig.engine));
    /* now the same filter, but fed by another counter: a different source upstream */
    CHECK_INT(canopy_graph_add_node(rewired, 1, "test.counter"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(rewired, 4, "test.counter"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(rewired, 2, "test_filter"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(rewired, 3, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rewired, 1, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rewired, 4, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rewired, 4, "tag", 1), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rewired, 2, "internal_sampling_rate", 200), CANOPY_OK);
    CHECK_INT(canopy_graph_set_int(rewired, 2, "checkpoint_seconds", 2), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(rewired, 4, "out", 2, "in"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(rewired, 2, "out", 3, "in0"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rewired), CANOPY_OK);
    before = support_counts[1];
    (void)canopy_instance_inlet_at(rig.instance, 3, 0, grid_ns(1000, 200));
    CHECK(support_counts[1] - before >= 1000);                 /* started again, reading the new counter */
    canopy_graph_free(rewired);
    rig_close(&rig);
}

static void test_c_the_filter_works_at_the_lowest_and_highest_internal_rates_and_with_a_zero_checkpoint_interval(void)
{
    static const int64_t rates[] = {1, 384000};
    int r, q;
    for (r = 0; r < 2; r++) {
        Rig rig;
        int64_t rate = rates[r];
        int64_t last = r == 0 ? 40 : 7700;
        int64_t span_ns = r == 0 ? 30000000000LL : 20000000LL;
        Ref ref = ref_make(rate, 0.1f, -0.3f, support_saw, last);
        filter_rig(&rig, rate, r == 0 ? 1 : 0, 0.1f, -0.3f);               /* a checkpoint interval of 0 seconds counts as 1 */
        lcg_state = 99 + (uint32_t)r;
        for (q = 0; q < 80; q++) {
            int64_t t = random_time(-span_ns / 10, span_ns);
            float got = canopy_instance_inlet_at(rig.instance, 3, 0, t);
            if (float_bits(got) != float_bits(ref_out(&ref, t))) {
                ctest_current_failed = 1;
                printf("    rate %lld, t=%lld ns: got %g, plain recomputation %g\n", (long long)rate, (long long)t, got, ref_out(&ref, t));
                break;
            }
        }
        ref_free(&ref);
        rig_close(&rig);
    }
}

static void test_c_a_checkpoint_interval_of_any_size_is_limited_so_that_nothing_overflows(void)
{
    /* INT64_MAX seconds times 384000 Hz wraps to an interval of -384000 samples: harmless during the first second, wrong after it (a negative
       checkpoint index), so the queries here run past one second of the highest rate: 460800 samples in 1.2 s */
    static const int64_t seconds[] = {INT64_MAX, 1000000000000LL, 3600001, 3600000};
    enum { LAST = 460810, TIMES = 40 };
    int s, q, k;
    for (s = 0; s < 4; s++) {
        Rig rig;
        Ref ref = ref_make(384000, 0.1f, -0.3f, support_saw, LAST);
        int64_t times[TIMES];
        filter_rig(&rig, 384000, seconds[s], 0.1f, -0.3f);
        lcg_state = 555 + (uint32_t)s;
        for (q = 0; q < TIMES; q++) times[q] = random_time(0, 1200000000LL);
        for (q = 1; q < TIMES; q++)                                              /* in order, so that the filter renders the 460800 samples once */
            for (k = q; k > 0 && times[k - 1] > times[k]; k--) {
                int64_t swap = times[k];
                times[k] = times[k - 1];
                times[k - 1] = swap;
            }
        for (q = 0; q < TIMES; q++) {
            float got = canopy_instance_inlet_at(rig.instance, 3, 0, times[q]);
            if (float_bits(got) != float_bits(ref_out(&ref, times[q]))) {
                ctest_current_failed = 1;
                printf("    checkpoint_seconds %lld, t=%lld ns: got %g, plain recomputation %g\n", (long long)seconds[s], (long long)times[q], got,
                       ref_out(&ref, times[q]));
                break;
            }
        }
        ref_free(&ref);
        rig_close(&rig);
    }
}

/* a source that moves by 0.001 with every nanosecond, so that an input read one nanosecond off changes the answer by far more than the
   float's resolution (with the saw it hides in the rounding): checks the grid times the filter asks at, to the nanosecond */
static void test_c_the_filter_reads_its_input_at_grid_times_rounded_half_up_to_the_nanosecond(void)
{
    static const int64_t rates[] = {1024, 7, 48000, 384000};              /* 1024: every odd sample falls exactly half a nanosecond between two */
    static const int64_t lasts[] = {260, 25, 1000, 1950};
    int r, q;
    for (r = 0; r < 4; r++) {
        Rig rig;
        int64_t rate = rates[r], last = lasts[r], k;
        Ref ref = ref_make(rate, 0.1f, 0.3f, support_jitter, last);
        filter_rig_with(&rig, "test.jitter", rate, 1, 0.1f, 0.3f, 0);
        for (k = 0; k + 2 < last; k++) {                                       /* exactly at every grid time... */
            int64_t t = grid_ns(k, rate);
            float got = canopy_instance_inlet_at(rig.instance, 3, 0, t);
            if (float_bits(got) != float_bits(ref_out(&ref, t))) {
                ctest_current_failed = 1;
                printf("    rate %lld, sample %lld (t=%lld ns): got %g, plain recomputation %g\n", (long long)rate, (long long)k, (long long)t,
                       got, ref_out(&ref, t));
                break;
            }
        }
        lcg_state = 31 + (uint32_t)r;
        for (q = 0; q < 40; q++) {                                             /* ...and in between */
            int64_t t = random_time(0, grid_ns(last - 3, rate));
            float got = canopy_instance_inlet_at(rig.instance, 3, 0, t);
            if (float_bits(got) != float_bits(ref_out(&ref, t))) {
                ctest_current_failed = 1;
                printf("    rate %lld, t=%lld ns: got %g, plain recomputation %g\n", (long long)rate, (long long)t, got, ref_out(&ref, t));
                break;
            }
        }
        ref_free(&ref);
        rig_close(&rig);
    }
}

static void test_c_a_coefficient_outside_the_range_of_a_knob_is_limited_to_what_the_filter_allows(void)
{
    static const float coefs[] = {3.0f, -3.0f};
    int c;
    for (c = 0; c < 2; c++) {
        Rig rig;
        int64_t k;
        Ref ref = ref_make(200, 0.25f, coefs[c], support_saw, 400);
        filter_rig_with(&rig, "test.saw", 200, 2, 0.25f, coefs[c], 1);         /* the coefficient comes from a connected node: not limited to -1..1 */
        for (k = 0; k < 300; k++) {
            int64_t t = grid_ns(k, 200);
            float got = canopy_instance_inlet_at(rig.instance, 3, 0, t);
            CHECK(float_bits(got) == float_bits(ref_out(&ref, t)));
            if (c == 0) CHECK(fabsf(got - support_saw(t)) < 3.0e-7f);          /* (3 + 1) / 2 = 2 is limited to 1: the output follows the input */
            else CHECK(got == 0.25f);                                          /* (-3 + 1) / 2 = -1 is limited to 0: it never leaves the initial value */
        }
        ref_free(&ref);
        rig_close(&rig);
    }
}

void register_test_state(void)
{
    RUN(test_c_the_stamp_is_stable_while_nothing_upstream_changes_and_differs_between_nodes);
    RUN(test_c_the_context_functions_of_this_step_tolerate_a_null_context);
    RUN(test_c_a_knob_move_changes_the_stamp_of_what_is_downstream_and_of_nothing_else);
    RUN(test_c_the_stamp_sees_through_any_number_of_nodes_and_through_fan_in_and_out);
    RUN(test_c_a_boundary_write_changes_the_stamp_downstream_and_accepts_any_float);
    RUN(test_c_a_setting_change_in_a_new_graph_changes_the_stamp_but_an_identical_or_unrelated_graph_does_not);
    RUN(test_c_a_setting_of_any_kind_moves_the_stamp_when_its_value_differs_in_any_way_and_not_when_it_is_only_installed_again);
    RUN(test_c_one_setting_changed_again_and_again_gives_every_value_a_stamp_of_its_own_also_when_it_goes_back);
    RUN(test_c_a_shared_resource_change_changes_the_stamp_downstream_only);
    RUN(test_c_rewiring_changes_the_stamp_even_when_no_generation_number_does);
    RUN(test_c_rewiring_to_the_other_outlet_of_the_same_node_changes_the_stamp);
    RUN(test_c_a_source_that_leaves_and_comes_back_keeps_the_stamp_only_while_its_data_is_the_same);
    RUN(test_c_a_loop_does_not_stop_the_stamps_from_being_made);
    RUN(test_c_the_filter_matches_a_plain_recomputation_at_random_times_in_any_order);
    RUN(test_c_spans_of_any_density_and_direction_agree_with_the_plain_recomputation_and_with_point_queries);
    RUN(test_c_two_instances_answer_alike_whatever_each_was_asked_before);
    RUN(test_c_checkpoints_are_used_so_that_an_earlier_or_repeated_query_does_not_start_from_zero);
    RUN(test_c_an_edit_upstream_of_one_filter_makes_that_filter_forget_and_not_the_other);
    RUN(test_c_a_setting_upstream_or_of_the_filter_itself_changed_by_a_new_graph_makes_the_filter_forget);
    RUN(test_c_a_boundary_write_and_a_shared_resource_change_make_the_filter_forget);
    RUN(test_c_installing_a_graph_that_changes_nothing_upstream_keeps_what_the_filter_has_computed);
    RUN(test_c_the_filter_works_at_the_lowest_and_highest_internal_rates_and_with_a_zero_checkpoint_interval);
    RUN(test_c_a_checkpoint_interval_of_any_size_is_limited_so_that_nothing_overflows);
    RUN(test_c_the_filter_reads_its_input_at_grid_times_rounded_half_up_to_the_nanosecond);
    RUN(test_c_a_coefficient_outside_the_range_of_a_knob_is_limited_to_what_the_filter_allows);
}
