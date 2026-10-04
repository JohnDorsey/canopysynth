/* Tests: compile-and-swap (design section 8): an instance adopts a newly installed graph at the start of its next query, state is carried
   over by node ID, nothing is allocated or freed by a query, and what is no longer used is freed by the editing thread. */
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <process.h>
#include "support.h"
#include "../../src/canopy_core.h"                  /* the engine's own lock, which the lock test holds itself */

static float read_inlet(CanopyInstance *instance, int64_t sink, int32_t inlet)
{
    return host_inlet_at(instance, sink, inlet, 0);
}

static void test_c_an_instance_adopts_a_newly_installed_graph_at_its_next_query_and_not_before(void)
{
    Rig rig;
    CanopyGraph *second;
    rig_open(&rig);
    second = canopy_graph_new();
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    CHECK(read_inlet(rig.instance, 2, 0) == 0.5f);
    CHECK_INT(canopy_graph_add_node(second, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 3, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 1, "out", 2, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 3, "out", 2, "in1"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(second, 1, "value", 0.75), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(second, 3, "value", 9.0), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(canopy_engine_graph_serial(rig.engine), 2);
    CHECK_INT(canopy_instance_graph_serial(rig.instance), 1);                /* installing did not touch the running instance */
    CHECK(read_inlet(rig.instance, 2, 0) == 0.75f);                          /* its next query runs the new graph */
    CHECK_INT(canopy_instance_graph_serial(rig.instance), 2);
    CHECK(read_inlet(rig.instance, 2, 1) == 9.0f);                           /* including the node that is new */
    canopy_graph_free(second);
    rig_close(&rig);
}

/* node 1 (and 2) are test.state, read through sink 9: in0 <- 1, in1 <- 2 (or 3, 4) */
static void describe_states(CanopyGraph *g, int64_t a, int64_t b)
{
    CHECK_INT(canopy_graph_add_node(g, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, a, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g, b, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(g, a, "out", 9, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(g, b, "out", 9, "in1"), CANOPY_OK);
}

static void test_c_adopting_allocates_and_frees_nothing_the_editing_thread_has_done_it_all_beforehand(void)
{
    Rig rig;
    CanopyGraph *second;
    int64_t live, total;
    support_counters_reset();
    rig_open(&rig);
    second = canopy_graph_new();
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    rig_install(&rig);
    CHECK_INT(canopy_graph_add_node(second, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 3, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 1, "out", 2, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 3, "out", 2, "in1"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(support_state_created, 1);                                     /* the new node's state was made at install, by this thread */
    live = canopy_alloc_live();
    total = canopy_alloc_total();
    CHECK(read_inlet(rig.instance, 2, 1) == 4.0f);                           /* this query adopts the graph... */
    CHECK_INT(canopy_instance_graph_serial(rig.instance), 2);
    CHECK_INT(canopy_alloc_total(), total);                                  /* ...without allocating... */
    CHECK_INT(canopy_alloc_live(), live);                                    /* ...or freeing anything */
    CHECK(read_inlet(rig.instance, 2, 1) == 5.0f);
    CHECK_INT(canopy_alloc_total(), total);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);                         /* the editing thread then frees the old graph and old table */
    CHECK(canopy_alloc_live() < live);
    canopy_graph_free(second);
    rig_close(&rig);
    CHECK_INT(support_state_destroyed, support_state_created);
}

static void test_c_state_is_carried_over_by_node_id_new_nodes_start_fresh_and_state_of_removed_nodes_is_destroyed_later(void)
{
    Rig rig;
    CanopyGraph *second;
    support_counters_reset();
    rig_open(&rig);
    second = canopy_graph_new();
    describe_states(rig.graph, 1, 2);
    rig_install(&rig);
    CHECK(read_inlet(rig.instance, 9, 0) == 4.0f);
    CHECK(read_inlet(rig.instance, 9, 0) == 5.0f);
    CHECK(read_inlet(rig.instance, 9, 1) == 4.0f);
    describe_states(second, 1, 3);                                           /* node 2 goes, node 3 comes */
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK_INT(support_state_created, 3);
    CHECK_INT(support_state_destroyed, 0);                                   /* node 2's state is still in the instance */
    CHECK(read_inlet(rig.instance, 9, 0) == 6.0f);                           /* node 1: the same state, carried over (5 -> 6) */
    CHECK(read_inlet(rig.instance, 9, 1) == 4.0f);                           /* node 3: a fresh one */
    CHECK_INT(support_state_destroyed, 0);                                   /* a query destroys nothing */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(support_state_destroyed, 1);                                   /* now node 2's state is gone */
    canopy_graph_free(second);
    rig_close(&rig);
    CHECK_INT(support_state_created, 3);
    CHECK_INT(support_state_destroyed, 3);
}

static void test_c_a_node_whose_type_changes_gets_fresh_state_and_the_old_state_is_destroyed(void)
{
    Rig rig;
    CanopyGraph *as_const, *as_state_again;
    support_counters_reset();
    rig_open(&rig);
    as_const = canopy_graph_new();
    as_state_again = canopy_graph_new();
    describe_states(rig.graph, 1, 2);
    rig_install(&rig);
    CHECK(read_inlet(rig.instance, 9, 0) == 4.0f);
    CHECK(read_inlet(rig.instance, 9, 0) == 5.0f);
    CHECK_INT(canopy_graph_add_node(as_const, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(as_const, 1, "test.const"), CANOPY_OK);     /* node 1 is another type now */
    CHECK_INT(canopy_graph_add_node(as_const, 2, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(as_const, 1, "value", 7.0), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(as_const, 1, "out", 9, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(as_const, 2, "out", 9, "in1"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, as_const), CANOPY_OK);
    CHECK(read_inlet(rig.instance, 9, 0) == 7.0f);
    CHECK(read_inlet(rig.instance, 9, 1) == 4.0f);                           /* node 2 kept its state (it had not been asked before: 3 + 1) */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(support_state_destroyed, 1);                                   /* the state of node 1 as a state node */
    describe_states(as_state_again, 1, 2);                                   /* and back to a state node: a fresh state, 4 again */
    CHECK_INT(canopy_engine_set_graph(rig.engine, as_state_again), CANOPY_OK);
    CHECK(read_inlet(rig.instance, 9, 0) == 4.0f);
    canopy_graph_free(as_const);
    canopy_graph_free(as_state_again);
    rig_close(&rig);
    CHECK_INT(support_state_destroyed, support_state_created);
}

static void test_c_several_installs_before_one_query_are_all_applied_in_order(void)
{
    Rig rig;
    CanopyGraph *g2, *g3;
    support_counters_reset();
    rig_open(&rig);
    g2 = canopy_graph_new();
    g3 = canopy_graph_new();
    describe_states(rig.graph, 1, 2);
    describe_states(g2, 1, 4);
    describe_states(g3, 1, 3);
    rig_install(&rig);
    CHECK(read_inlet(rig.instance, 9, 0) == 4.0f);
    CHECK_INT(canopy_engine_set_graph(rig.engine, g2), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, g3), CANOPY_OK);
    CHECK_INT(canopy_engine_graph_serial(rig.engine), 3);
    CHECK_INT(canopy_instance_graph_serial(rig.instance), 1);
    CHECK_INT(support_state_created, 4);                                     /* 1, 2 at the start; 4 for the second graph; 3 for the third */
    CHECK(read_inlet(rig.instance, 9, 0) == 5.0f);                           /* one query goes through both steps: node 1 carried through both */
    CHECK_INT(canopy_instance_graph_serial(rig.instance), 3);
    CHECK(read_inlet(rig.instance, 9, 1) == 4.0f);                           /* node 3 */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(support_state_destroyed, 2);                                   /* node 2 (first graph only) and node 4 (the second graph only) */
    canopy_graph_free(g2);
    canopy_graph_free(g3);
    rig_close(&rig);
    CHECK_INT(support_state_destroyed, 4);
}

static void test_c_a_bigger_arena_is_prepared_at_install_and_the_old_one_freed_when_collected(void)
{
    Rig rig;
    CanopyGraph *chain;
    int64_t live;
    rig_open(&rig);
    chain = canopy_graph_new();
    rig_node(&rig, 1, "test.gain");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_knob(rig.graph, 1, "in", 0.5f), CANOPY_OK);
    rig_install(&rig);
    CHECK_INT(canopy_instance_arena_floats(rig.instance), CANOPY_MAX_N);
    CHECK_INT(canopy_graph_add_node(chain, 1, "test.gain"), CANOPY_OK);          /* gain 4 -> gain 3 -> gain 1: three buffers held at once */
    CHECK_INT(canopy_graph_add_node(chain, 3, "test.gain"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(chain, 4, "test.gain"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(chain, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(chain, 3, "out", 1, "in"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(chain, 4, "out", 3, "in"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(chain, 1, "out", 2, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(chain, 4, "in", 0.5f), CANOPY_OK);
    CHECK_INT(canopy_graph_set_knob(chain, 4, "gain", 0.5f), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, chain), CANOPY_OK);
    CHECK_INT(canopy_instance_arena_floats(rig.instance), CANOPY_MAX_N);        /* not yet */
    {
        Guarded g = guarded_new(8);
        const float expected[8] = {0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f};
        int64_t total = canopy_alloc_total();
        live = canopy_alloc_live();
        CHECK_INT(canopy_instance_inlet_span(rig.instance, 2, 0, 0, 80, 8, g.data), CANOPY_OK);
        CHECK(guarded_equals(&g, expected));                                     /* the three-deep chain, with its scratch, works at once */
        CHECK_INT(canopy_instance_arena_floats(rig.instance), 3LL * CANOPY_MAX_N);
        CHECK_INT(canopy_alloc_total(), total);                                  /* the arena was allocated by the editing thread */
        CHECK_INT(canopy_alloc_live(), live);
        guarded_free(&g);
    }
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK(canopy_alloc_live() < live);                                           /* the small arena and the old graph are gone */
    canopy_graph_free(chain);
    rig_close(&rig);
}

static void test_c_an_instance_that_never_queries_keeps_old_graphs_alive_until_it_adopts_or_is_freed(void)
{
    Rig rig;
    CanopyGraph *g2, *g3, *g4;
    CanopyInstance *idle;
    support_counters_reset();
    rig_open(&rig);
    g2 = canopy_graph_new();
    g3 = canopy_graph_new();
    g4 = canopy_graph_new();
    rig_node(&rig, 1, "test.source");                                            /* has a shared resource, and is gone from the second graph on */
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 9, "in0");
    rig_install(&rig);
    idle = canopy_engine_new_instance(rig.engine);
    CHECK(idle != NULL);
    CHECK_INT(canopy_graph_add_node(g2, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g3, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g3, 5, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(g4, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, g2), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, g3), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, g4), CANOPY_OK);
    CHECK(read_inlet(rig.instance, 9, 1) == 0.5f);                               /* the first instance has moved on (the knob of a bare sink) */
    CHECK_INT(canopy_engine_collect(rig.engine), 4);                             /* the idle one still needs graph 1 and the steps from it */
    CHECK_INT(support_shared_destroyed, 0);                                      /* so the shared resource of node 1 lives */
    CHECK_INT(canopy_instance_graph_serial(idle), 1);
    CHECK(read_inlet(idle, 9, 1) == 0.5f);                                       /* it adopts all three steps at its first query */
    CHECK_INT(canopy_instance_graph_serial(idle), 4);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(support_shared_destroyed, 1);                                      /* and only now is the resource of the removed node freed */
    canopy_instance_free(idle);
    canopy_graph_free(g2);
    canopy_graph_free(g3);
    canopy_graph_free(g4);
    rig_close(&rig);
}

static void test_c_freeing_an_instance_with_installs_it_never_adopted_destroys_the_state_prepared_for_it(void)
{
    Rig rig;
    CanopyGraph *g2, *g3;
    CanopyInstance *other;
    support_counters_reset();
    rig_open(&rig);
    g2 = canopy_graph_new();
    g3 = canopy_graph_new();
    describe_states(rig.graph, 1, 2);
    describe_states(g2, 1, 3);
    describe_states(g3, 4, 3);
    rig_install(&rig);
    other = canopy_engine_new_instance(rig.engine);
    CHECK(other != NULL);
    CHECK_INT(support_state_created, 4);                                         /* two instances, two states each */
    CHECK_INT(canopy_engine_set_graph(rig.engine, g2), CANOPY_OK);               /* a fresh state for node 3 in each instance */
    CHECK_INT(canopy_engine_set_graph(rig.engine, g3), CANOPY_OK);               /* and for node 4 */
    CHECK_INT(support_state_created, 8);
    canopy_instance_free(other);                                                 /* never queried: 2 + 1 + 1 states are all destroyed */
    CHECK_INT(support_state_destroyed, 4);
    CHECK(read_inlet(rig.instance, 9, 1) == 4.0f);
    canopy_graph_free(g2);
    canopy_graph_free(g3);
    rig_close(&rig);
    CHECK_INT(support_state_destroyed, support_state_created);
}

static void test_c_instances_adopt_independently_and_the_engine_waits_for_all_of_them_to_be_freed(void)
{
    Rig rig;
    CanopyGraph *second;
    CanopyInstance *a, *b;
    rig_open(&rig);
    second = canopy_graph_new();
    rig_node(&rig, 1, "test.const");
    rig_node(&rig, 2, "test.sink");
    rig_connect(&rig, 1, "out", 2, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    a = rig.instance;
    rig.instance = NULL;
    b = canopy_engine_new_instance(rig.engine);
    CHECK(b != NULL);
    CHECK_INT(canopy_graph_add_node(second, 1, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(second, 2, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(second, 1, "out", 2, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(second, 1, "value", 0.25), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    CHECK(read_inlet(a, 2, 0) == 0.25f);
    CHECK_INT(canopy_instance_graph_serial(b), 1);                                /* b has not been asked: it still runs the first graph */
    CHECK_INT(canopy_engine_free(rig.engine), CANOPY_ERR_BUSY);
    canopy_instance_free(a);
    CHECK_INT(canopy_engine_free(rig.engine), CANOPY_ERR_BUSY);
    CHECK(read_inlet(b, 2, 0) == 0.25f);
    canopy_instance_free(b);
    canopy_graph_free(second);
    rig_close(&rig);
}

static void test_c_the_serial_and_collect_functions_tolerate_null_and_an_empty_engine(void)
{
    Rig rig;
    CHECK_INT(canopy_engine_graph_serial(NULL), 0);
    CHECK_INT(canopy_instance_graph_serial(NULL), 0);
    CHECK_INT(canopy_engine_collect(NULL), 0);
    rig_open(&rig);
    CHECK_INT(canopy_engine_graph_serial(rig.engine), 0);
    CHECK_INT(canopy_engine_collect(rig.engine), 0);
    rig_close(&rig);
}

/* ---- a shared resource goes with the last graph that has its node ---- */

static void test_c_the_shared_resource_of_a_removed_node_is_freed_once_no_instance_can_still_use_it(void)
{
    Rig rig;
    CanopyGraph *without;
    support_counters_reset();
    rig_open(&rig);
    without = canopy_graph_new();
    rig_node(&rig, 1, "test.source");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 9, "in0");
    rig_install(&rig);
    CHECK(read_inlet(rig.instance, 9, 0) == 1.0f);
    CHECK_INT(canopy_graph_add_node(without, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);
    CHECK_INT(support_shared_destroyed, 0);                                       /* the instance still runs the graph with the node */
    CHECK(read_inlet(rig.instance, 9, 1) == 0.5f);                                /* adopted: the sink is bare now */
    CHECK_INT(support_shared_destroyed, 0);                                       /* a query frees nothing */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(support_shared_destroyed, 1);                                       /* the editing thread does */
    canopy_graph_free(without);
    rig_close(&rig);
    CHECK_INT(support_shared_destroyed, 1);                                       /* and never twice */
}

/* installing a graph and freeing an instance both reclaim at once what no instance can use any more (no call of collect is needed) */
static void test_c_installing_and_freeing_an_instance_both_reclaim_what_no_instance_can_use_any_more(void)
{
    Rig rig;
    CanopyGraph *b, *c, *d;
    CanopyInstance *idle;
    support_counters_reset();
    rig_open(&rig);
    b = canopy_graph_new();
    c = canopy_graph_new();
    d = canopy_graph_new();
    rig_node(&rig, 1, "test.source");                                              /* A: two sources with a shared resource each... */
    rig_node(&rig, 2, "test.source");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 9, "in0");
    rig_connect(&rig, 2, "out", 9, "in1");
    CHECK_INT(canopy_graph_add_node(b, 2, "test.source"), CANOPY_OK);              /* B: ...without the first */
    CHECK_INT(canopy_graph_add_node(b, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(b, 2, "out", 9, "in1"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(c, 9, "test.sink"), CANOPY_OK);                /* C: without either */
    CHECK_INT(canopy_graph_add_node(d, 9, "test.sink"), CANOPY_OK);                /* D: the same with something new */
    CHECK_INT(canopy_graph_add_node(d, 5, "test.const"), CANOPY_OK);
    rig_install(&rig);
    idle = canopy_engine_new_instance(rig.engine);
    CHECK(idle != NULL);
    CHECK(read_inlet(rig.instance, 9, 1) == 1.0f);
    CHECK_INT(canopy_engine_set_graph(rig.engine, b), CANOPY_OK);
    CHECK(read_inlet(rig.instance, 9, 1) == 1.0f);                                 /* the first instance runs B, the idle one still runs A */
    CHECK_INT(support_shared_destroyed, 0);
    canopy_instance_free(idle);                                                    /* A has no user left: it goes now, and the first source's resource */
    CHECK_INT(support_shared_destroyed, 1);
    CHECK_INT(canopy_engine_set_graph(rig.engine, c), CANOPY_OK);                  /* the first instance has not seen C yet: B stays */
    CHECK_INT(support_shared_destroyed, 1);
    CHECK(read_inlet(rig.instance, 9, 1) == 0.5f);                                 /* it runs C now (a bare sink) */
    CHECK_INT(canopy_engine_set_graph(rig.engine, d), CANOPY_OK);                  /* installing D frees B at once, and the second source's resource */
    CHECK_INT(support_shared_destroyed, 2);
    canopy_graph_free(b);
    canopy_graph_free(c);
    canopy_graph_free(d);
    rig_close(&rig);
    CHECK_INT(support_shared_destroyed, 2);
}

/* ---- running out of memory while installing, with instances that have unadopted installs ---- */

static int adoption_scenario(CanopyRegistry *registry, CanopyGraph *a, CanopyGraph *b, int *serial_problems)
{
    CanopyEngine *engine = canopy_engine_new(registry);
    CanopyInstance *busy = NULL, *idle = NULL;
    int ok = 0;
    if (!engine) return 0;
    if (canopy_engine_set_graph(engine, a) != CANOPY_OK) goto done;
    busy = canopy_engine_new_instance(engine);
    idle = canopy_engine_new_instance(engine);
    if (!busy || !idle) goto done;
    if (host_inlet_at(busy, 9, 0, 0) != 0.5f) (*serial_problems)++;
    if (canopy_engine_set_graph(engine, b) != CANOPY_OK) {
        /* a failed install changes nothing: the old graph is still the installed one and both instances still answer from it */
        if (canopy_engine_graph_serial(engine) != 1) (*serial_problems)++;
        if (strstr(canopy_engine_last_error(engine), "out of memory") == NULL) (*serial_problems)++;          /* and says why */
        if (host_inlet_at(busy, 9, 0, 0) != 0.5f || host_inlet_at(idle, 9, 0, 0) != 0.5f) (*serial_problems)++;
        goto done;
    }
    if (host_inlet_at(busy, 9, 0, 0) != 0.75f) (*serial_problems)++;       /* adopts b */
    if (canopy_engine_set_graph(engine, a) != CANOPY_OK) goto done;                  /* the idle one has two unadopted installs now */
    (void)canopy_engine_collect(engine);
    if (host_inlet_at(idle, 9, 0, 0) != 0.5f) (*serial_problems)++;       /* it adopts both steps at once, ending on a */
    ok = 1;
done:
    if (busy) canopy_instance_free(busy);
    if (idle) canopy_instance_free(idle);
    if (canopy_engine_free(engine) != CANOPY_OK) ok = 0;
    return ok;
}

static void test_c_running_out_of_memory_while_installing_changes_nothing_and_leaks_nothing(void)
{
    CanopyRegistry *registry = support_registry();
    CanopyGraph *a = canopy_graph_new(), *b = canopy_graph_new();
    int64_t live, fail_at;
    int failures = 0, clean_runs = 0, serial_problems = 0;
    /* a: shared source 1, state 2, const 3 = 0.5 -> sink in0, state 2 -> sink in1; b: source 1 kept, state 4 instead of 2, const 3 = 0.75,
       and a gain 5 (a scratch buffer, so every instance needs a bigger arena for b) */
    CHECK_INT(canopy_graph_add_node(a, 1, "test.source"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(a, 2, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(a, 3, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(a, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(a, 3, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(a, 3, "out", 9, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(a, 2, "out", 9, "in1"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 1, "test.source"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 4, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 3, "test.const"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 5, "test.gain"), CANOPY_OK);                  /* holds a scratch buffer: b needs a bigger arena than a, for each instance */
    CHECK_INT(canopy_graph_set_float(b, 3, "value", 0.75), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(b, 3, "out", 9, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(b, 4, "out", 9, "in1"), CANOPY_OK);
    live = canopy_alloc_live();
    for (fail_at = 0; fail_at < 4000 && clean_runs < 3; fail_at++) {
        int ok;
        support_counters_reset();
        canopy_alloc_fail_after(fail_at);
        ok = adoption_scenario(registry, a, b, &serial_problems);
        canopy_alloc_fail_after(-1);
        if (ok) clean_runs++; else failures++;
        if (canopy_alloc_live() != live || support_state_created != support_state_destroyed || support_shared_created != support_shared_destroyed ||
            serial_problems != 0) {
            ctest_current_failed = 1;
            printf("    out of memory after %lld allocations: live %lld (expected %lld), states %d/%d, shared %d/%d, wrong answers %d\n",
                   (long long)fail_at, (long long)canopy_alloc_live(), (long long)live, support_state_created, support_state_destroyed,
                   support_shared_created, support_shared_destroyed, serial_problems);
            break;
        }
    }
    CHECK(failures > 100);
    CHECK_INT(clean_runs, 3);
    canopy_graph_free(a);
    canopy_graph_free(b);
    canopy_registry_free(registry);
}

/* ---- threads: instances in other threads keep answering while graphs are installed and knobs move ---- */

typedef struct {
    CanopyEngine *engine;
    volatile LONG *stop;
    volatile LONG blocks, bad;                      /* read by the installing thread while the reader counts */
} Reader;

static unsigned __stdcall reader_main(void *argument)
{
    Reader *reader = (Reader *)argument;
    CanopyInstance *instance = canopy_engine_new_instance(reader->engine);
    float out[64];
    int i;
    if (!instance) {
        InterlockedIncrement(&reader->bad);
        return 0;
    }
    while (!*reader->stop) {
        if (canopy_instance_inlet_span(instance, 9, 0, 0, 640, 64, out) != CANOPY_OK) {
            InterlockedIncrement(&reader->bad);
            continue;
        }
        for (i = 1; i < 64; i++)
            if (out[i] != out[0]) {
                InterlockedIncrement(&reader->bad);
                break;
            }
        if (out[0] != 0.5f && out[0] != 0.25f) InterlockedIncrement(&reader->bad);          /* the value of one graph or of the other, never a mixture */
        (void)host_inlet_at(instance, 9, 1, 0);                                  /* a state node in one graph, a knob in the other */
        InterlockedIncrement(&reader->blocks);
    }
    canopy_instance_free(instance);
    return 0;
}

/* true once every reader has answered more times than `before` says (false if that takes more than five seconds) */
static int wait_for_progress(const Reader *readers, int count, const LONG *before)
{
    ULONGLONG deadline = GetTickCount64() + 5000;
    int r;
    for (;;) {
        for (r = 0; r < count; r++)
            if (readers[r].blocks <= before[r]) break;
        if (r == count) return 1;
        if (GetTickCount64() > deadline) return 0;
        Sleep(0);
    }
}

static void test_c_instances_in_other_threads_keep_answering_while_graphs_are_installed_and_knobs_move(void)
{
    enum { READERS = 3, INSTALLS = 400 };
    Rig rig;
    CanopyGraph *b;
    volatile LONG stop = 0;
    Reader readers[READERS];
    HANDLE handles[READERS];
    long long blocks = 0, bad = 0;
    int i;
    support_counters_reset();
    rig_open(&rig);
    b = canopy_graph_new();
    rig_node(&rig, 1, "test.const");                       /* a: const 0.5 -> sink in0 */
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 1, "out", 9, "in0");
    CHECK_INT(canopy_graph_set_float(rig.graph, 1, "value", 0.5), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 1, "test.const"), CANOPY_OK);              /* b: const 0.25 -> in0, a state node -> in1, a source with a resource */
    CHECK_INT(canopy_graph_add_node(b, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 100, "test.state"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(b, 101, "test.source"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(b, 1, "value", 0.25), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(b, 1, "out", 9, "in0"), CANOPY_OK);
    CHECK_INT(canopy_graph_connect(b, 100, "out", 9, "in1"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);
    for (i = 0; i < READERS; i++) {
        readers[i].engine = rig.engine;
        readers[i].stop = &stop;
        readers[i].blocks = readers[i].bad = 0;
        handles[i] = (HANDLE)_beginthreadex(NULL, 0, reader_main, &readers[i], 0, NULL);
    }
    /* the installs are paced by the readers: every reader answers at least once between two installs (so each graph is really run, and
       the test cannot pass just because the readers got no time while 400 installs went by) */
    {
        LONG nothing_yet[READERS] = {0, 0, 0};
        CHECK(wait_for_progress(readers, READERS, nothing_yet));
    }
    for (i = 0; i < INSTALLS; i++) {
        LONG before[READERS];
        int r;
        for (r = 0; r < READERS; r++) before[r] = readers[r].blocks;
        CHECK_INT(canopy_engine_set_graph(rig.engine, (i & 1) ? rig.graph : b), CANOPY_OK);
        if (i % 10 == 0) (void)canopy_engine_set_knob(rig.engine, 9, 1, (i & 2) ? 0.5f : -0.5f);
        if (i % 50 == 0) (void)canopy_engine_collect(rig.engine);
        if (!wait_for_progress(readers, READERS, before)) {
            ctest_current_failed = 1;
            printf("    the readers stopped answering after install %d\n", i);
            break;
        }
    }
    InterlockedExchange(&stop, 1);
    WaitForMultipleObjects(READERS, handles, TRUE, INFINITE);
    for (i = 0; i < READERS; i++) {
        blocks += readers[i].blocks;
        bad += readers[i].bad;
        CloseHandle(handles[i]);
    }
    CHECK_INT(bad, 0);
    CHECK(blocks > 0);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);                              /* every instance is gone: only the installed graph is left */
    canopy_graph_free(b);
    rig_close(&rig);
    CHECK_INT(support_state_destroyed, support_state_created);
    CHECK_INT(support_shared_destroyed, support_shared_created);
}

/* ---- the engine's lock: who waits for it, and who never does ---- */

enum { PROBE_SET_KNOB, PROBE_GET_KNOB, PROBE_SET_BOUNDARY, PROBE_ACTION, PROBE_NODE_COUNT, PROBE_GRAPH_SERIAL, PROBE_BOUNDARY_COUNT, PROBE_BOUNDARY_AT,   /* use the lists: shared lock */
       PROBE_SET_GRAPH, PROBE_COLLECT, PROBE_NEW_INSTANCE, PROBE_FREE_INSTANCE, PROBE_ENGINE_FREE,                /* change them: exclusive lock */
       PROBE_QUERY_POINT, PROBE_QUERY_SPAN,                                                                        /* no lock at all */
       PROBE_COUNT };

static const char *const PROBE_NAMES[PROBE_COUNT] = {"set_knob", "get_knob", "set_boundary", "action", "node_count", "graph_serial",
                                                      "boundary_count", "boundary_at", "set_graph", "collect", "new_instance", "instance_free", "engine_free",
                                                      "instance_inlet_at", "instance_inlet_span"};
#define PROBES_SHARED ((1u << PROBE_SET_KNOB) | (1u << PROBE_GET_KNOB) | (1u << PROBE_SET_BOUNDARY) | (1u << PROBE_ACTION) | \
                       (1u << PROBE_NODE_COUNT) | (1u << PROBE_GRAPH_SERIAL) | (1u << PROBE_BOUNDARY_COUNT) | \
                       (1u << PROBE_BOUNDARY_AT))
#define PROBES_EXCLUSIVE ((1u << PROBE_SET_GRAPH) | (1u << PROBE_COLLECT) | (1u << PROBE_NEW_INSTANCE) | (1u << PROBE_FREE_INSTANCE) | \
                          (1u << PROBE_ENGINE_FREE))
#define PROBES_QUERY ((1u << PROBE_QUERY_POINT) | (1u << PROBE_QUERY_SPAN))

typedef struct {
    CanopyEngine *engine;
    CanopyGraph *graph;
    CanopyInstance *instance;                       /* a query uses this one */
    CanopyInstance *to_free;                        /* instance_free frees this one */
    CanopyInstance *made;                           /* new_instance made this one */
    int what;
    volatile LONG done;
    int32_t status;
} Probe;

static unsigned __stdcall probe_main(void *argument)
{
    Probe *probe = (Probe *)argument;
    float value = 0.0f, out[4];
    uint64_t generation = 0;
    switch (probe->what) {
    case PROBE_SET_KNOB: probe->status = canopy_engine_set_knob(probe->engine, 1, 0, 0.5f); break;
    case PROBE_GET_KNOB: probe->status = canopy_engine_get_knob(probe->engine, 1, 0, &value, &generation); break;
    case PROBE_SET_BOUNDARY: probe->status = canopy_engine_set_boundary(probe->engine, "b", 0.5f); break;
    case PROBE_BOUNDARY_COUNT: probe->status = canopy_engine_boundary_count(probe->engine) == 1 ? CANOPY_OK : -1; break;
    case PROBE_BOUNDARY_AT: probe->status = canopy_engine_boundary_at(probe->engine, 0, NULL, 0, NULL, NULL, NULL); break;
    case PROBE_ACTION: probe->status = canopy_engine_action(probe->engine, 2, "bump"); break;
    case PROBE_NODE_COUNT: probe->status = canopy_engine_node_count(probe->engine) == 5 ? CANOPY_OK : -1; break;
    case PROBE_GRAPH_SERIAL: probe->status = canopy_engine_graph_serial(probe->engine) >= 1 ? CANOPY_OK : -1; break;
    case PROBE_SET_GRAPH: probe->status = canopy_engine_set_graph(probe->engine, probe->graph); break;
    case PROBE_COLLECT: probe->status = canopy_engine_collect(probe->engine) >= 1 ? CANOPY_OK : -1; break;
    case PROBE_NEW_INSTANCE: probe->made = canopy_engine_new_instance(probe->engine); probe->status = probe->made ? CANOPY_OK : -1; break;
    case PROBE_FREE_INSTANCE: canopy_instance_free(probe->to_free); probe->status = CANOPY_OK; break;
    case PROBE_ENGINE_FREE: probe->status = canopy_engine_free(probe->engine); break;          /* instances are left: it says BUSY, once it gets in */
    case PROBE_QUERY_POINT: probe->status = host_inlet_at(probe->instance, 9, 0, 0) == 0.5f ? CANOPY_OK : -1; break;
    case PROBE_QUERY_SPAN: probe->status = canopy_instance_inlet_span(probe->instance, 9, 0, 0, 40, 4, out); break;
    default: probe->status = -1; break;
    }
    InterlockedExchange(&probe->done, 1);
    return 0;
}

static unsigned probes_done(const Probe *probes)
{
    unsigned mask = 0;
    int i;
    for (i = 0; i < PROBE_COUNT; i++)
        if (probes[i].done) mask |= 1u << i;
    return mask;
}

/* Holds the engine's lock (exclusively or shared) and starts the probes in `start`. Waits until the ones in `expected` have finished (they can
   even though the lock is held), then another 100 ms for the others to show that they cannot, and returns the probes that had finished by
   then. Then lets go of the lock and waits for all of them. */
static unsigned probe_under_lock(Probe *probes, unsigned start, unsigned expected, int exclusive)
{
    HANDLE handles[PROBE_COUNT];
    CanopyEngine *engine = probes[0].engine;
    unsigned seen;
    int i, n = 0;
    ULONGLONG deadline;
    for (i = 0; i < PROBE_COUNT; i++) {
        probes[i].done = 0;
        probes[i].status = 1;
    }
    if (exclusive) canopy_lock_exclusive(&engine->lock); else canopy_lock_shared(&engine->lock);
    for (i = 0; i < PROBE_COUNT; i++)
        if (start & (1u << i)) handles[n++] = (HANDLE)_beginthreadex(NULL, 0, probe_main, &probes[i], 0, NULL);
    deadline = GetTickCount64() + 5000;
    while ((probes_done(probes) & expected) != expected && GetTickCount64() < deadline) Sleep(1);
    Sleep(100);
    seen = probes_done(probes);
    if (exclusive) canopy_unlock_exclusive(&engine->lock); else canopy_unlock_shared(&engine->lock);
    WaitForMultipleObjects((DWORD)n, handles, TRUE, INFINITE);
    for (i = 0; i < n; i++) CloseHandle(handles[i]);
    return seen;
}

static void report_probes(const char *round, unsigned seen, unsigned expected)
{
    int i;
    if (seen == expected) return;
    ctest_current_failed = 1;
    for (i = 0; i < PROBE_COUNT; i++)
        if ((seen ^ expected) & (1u << i))
            printf("    %s: %s %s\n", round, PROBE_NAMES[i], (seen & (1u << i)) ? "went through although it had to wait" : "did not go through although it could");
}

static void test_c_calls_that_use_the_engines_lists_wait_for_its_lock_and_queries_never_do(void)
{
    Rig rig;
    Probe probes[PROBE_COUNT];
    CanopyInstance *for_span;
    int i;
    rig_open(&rig);
    rig_node(&rig, 1, "test.gain");
    rig_node(&rig, 2, "test.source");
    rig_node(&rig, 3, "boundary_inlet");
    rig_node(&rig, 4, "test.const");
    rig_node(&rig, 9, "test.sink");
    rig_connect(&rig, 4, "out", 9, "in0");
    CHECK_INT(canopy_graph_set_string(rig.graph, 3, "name", "b"), CANOPY_OK);
    CHECK_INT(canopy_graph_set_float(rig.graph, 4, "value", 0.5), CANOPY_OK);
    rig_install(&rig);
    for_span = canopy_engine_new_instance(rig.engine);
    CHECK(for_span != NULL);
    memset(probes, 0, sizeof probes);
    for (i = 0; i < PROBE_COUNT; i++) {
        probes[i].engine = rig.engine;
        probes[i].graph = rig.graph;
        probes[i].what = i;
        probes[i].instance = i == PROBE_QUERY_SPAN ? for_span : rig.instance;
    }
    /* the lock held exclusively (as an install holds it): everything that uses the lists waits, the queries of the audio thread do not */
    probes[PROBE_FREE_INSTANCE].to_free = canopy_engine_new_instance(rig.engine);
    report_probes("exclusive lock held", probe_under_lock(probes, (1u << PROBE_COUNT) - 1u, PROBES_QUERY, 1), PROBES_QUERY);
    CHECK_INT(probes[PROBE_QUERY_POINT].status, CANOPY_OK);
    CHECK_INT(probes[PROBE_QUERY_SPAN].status, CANOPY_OK);
    CHECK_INT(probes[PROBE_ENGINE_FREE].status, CANOPY_ERR_BUSY);                  /* (once it got in: there are instances) */
    CHECK(probes[PROBE_NEW_INSTANCE].made != NULL);
    canopy_instance_free(probes[PROBE_NEW_INSTANCE].made);
    probes[PROBE_NEW_INSTANCE].made = NULL;
    /* the lock held shared (as a knob write holds it): the calls that only read the lists go through, together */
    {
        unsigned wanted = PROBES_SHARED | PROBES_QUERY;
        report_probes("shared lock held, calls that read the lists", probe_under_lock(probes, wanted, wanted, 0), wanted);
        for (i = 0; i < PROBE_COUNT; i++)
            if (wanted & (1u << i)) CHECK_INT(probes[i].status, CANOPY_OK);
    }
    /* ...and the calls that change them wait for it */
    probes[PROBE_FREE_INSTANCE].to_free = canopy_engine_new_instance(rig.engine);
    report_probes("shared lock held, calls that change the lists", probe_under_lock(probes, PROBES_EXCLUSIVE, 0, 0), 0);
    CHECK_INT(probes[PROBE_ENGINE_FREE].status, CANOPY_ERR_BUSY);
    CHECK(probes[PROBE_NEW_INSTANCE].made != NULL);
    canopy_instance_free(probes[PROBE_NEW_INSTANCE].made);
    canopy_instance_free(for_span);
    rig_close(&rig);
}

/* ---- many nodes: the records of the engine are kept in order, found again and given up with their nodes ---- */

static void shuffle(int64_t *values, int n, uint32_t seed)
{
    uint32_t state = seed;
    int i;
    for (i = n - 1; i > 0; i--) {
        int j;
        int64_t swap;
        state = state * 1664525u + 1013904223u;
        j = (int)((state >> 8) % (uint32_t)(i + 1));
        swap = values[i];
        values[i] = values[j];
        values[j] = swap;
    }
}

static void add_source_and_sink_pairs(CanopyGraph *g, const int64_t *ids, int n)       /* a test.source with this id, read by the sink 1000 + id */
{
    int i;
    for (i = 0; i < n; i++) {
        CHECK_INT(canopy_graph_add_node(g, ids[i], "test.source"), CANOPY_OK);
        CHECK_INT(canopy_graph_add_node(g, 1000 + ids[i], "test.sink"), CANOPY_OK);
        CHECK_INT(canopy_graph_connect(g, ids[i], "out", 1000 + ids[i], "in0"), CANOPY_OK);
    }
}

static void test_c_many_nodes_added_in_any_order_keep_their_own_resources_across_installs_and_lose_them_with_the_node(void)
{
    enum { N = 40 };
    Rig rig;
    CanopyGraph *second, *third;
    int64_t old_ids[N], new_ids[N], order[N], odd_old[N / 2];
    int i, b, odd = 0;
    support_counters_reset();
    rig_open(&rig);
    second = canopy_graph_new();
    third = canopy_graph_new();
    for (i = 0; i < N; i++) {
        old_ids[i] = 10 * (i + 1);                      /* 10, 20, ... 400 */
        new_ids[i] = 10 * (i + 1) + 5;                  /* 15, 25, ... 405: each goes between two old ones, into the middle of the records */
        if (i % 2 == 1) odd_old[odd++] = old_ids[i];
    }
    memcpy(order, old_ids, sizeof order);
    shuffle(order, N, 1);
    add_source_and_sink_pairs(rig.graph, order, N);
    rig_install(&rig);                                  /* (more than the 16 records an array starts with: it grows three times) */
    for (i = 0; i < N; i++) CHECK(host_inlet_at(rig.instance, 1000 + old_ids[i], 0, 0) == 1.0f);
    for (i = 0; i < N; i++)
        for (b = 0; b < i % 3 + 1; b++) CHECK_INT(canopy_engine_action(rig.engine, old_ids[i], "bump"), CANOPY_OK);
    for (i = 0; i < N; i++) CHECK(host_inlet_at(rig.instance, 1000 + old_ids[i], 0, 0) == (float)(2 + i % 3));
    CHECK_INT(support_shared_created, N);
    /* all of them again, in another order, and as many new ones in between */
    memcpy(order, old_ids, sizeof order);
    shuffle(order, N, 2);
    add_source_and_sink_pairs(second, order, N);
    memcpy(order, new_ids, sizeof order);
    shuffle(order, N, 3);
    add_source_and_sink_pairs(second, order, N);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    for (i = 0; i < N; i++) CHECK(host_inlet_at(rig.instance, 1000 + old_ids[i], 0, 0) == (float)(2 + i % 3));   /* what was bumped stays */
    for (i = 0; i < N; i++) CHECK(host_inlet_at(rig.instance, 1000 + new_ids[i], 0, 0) == 1.0f);
    CHECK_INT(support_shared_created, 2 * N);                                                                              /* and nothing was made twice */
    /* half of the old ones leave: their resources go once nothing can use them, the others keep theirs */
    add_source_and_sink_pairs(third, odd_old, N / 2);
    memcpy(order, new_ids, sizeof order);
    shuffle(order, N, 4);
    add_source_and_sink_pairs(third, order, N);
    CHECK_INT(canopy_engine_set_graph(rig.engine, third), CANOPY_OK);
    for (i = 1; i < N; i += 2) CHECK(host_inlet_at(rig.instance, 1000 + old_ids[i], 0, 0) == (float)(2 + i % 3));
    for (i = 0; i < N; i++) CHECK(host_inlet_at(rig.instance, 1000 + new_ids[i], 0, 0) == 1.0f);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(support_shared_created, 2 * N);
    CHECK_INT(support_shared_destroyed, N / 2);
    canopy_graph_free(second);
    canopy_graph_free(third);
    rig_close(&rig);
    CHECK_INT(support_shared_destroyed, support_shared_created);
}

void register_test_swap(void)
{
    RUN(test_c_an_instance_adopts_a_newly_installed_graph_at_its_next_query_and_not_before);
    RUN(test_c_adopting_allocates_and_frees_nothing_the_editing_thread_has_done_it_all_beforehand);
    RUN(test_c_state_is_carried_over_by_node_id_new_nodes_start_fresh_and_state_of_removed_nodes_is_destroyed_later);
    RUN(test_c_a_node_whose_type_changes_gets_fresh_state_and_the_old_state_is_destroyed);
    RUN(test_c_several_installs_before_one_query_are_all_applied_in_order);
    RUN(test_c_a_bigger_arena_is_prepared_at_install_and_the_old_one_freed_when_collected);
    RUN(test_c_an_instance_that_never_queries_keeps_old_graphs_alive_until_it_adopts_or_is_freed);
    RUN(test_c_freeing_an_instance_with_installs_it_never_adopted_destroys_the_state_prepared_for_it);
    RUN(test_c_instances_adopt_independently_and_the_engine_waits_for_all_of_them_to_be_freed);
    RUN(test_c_the_serial_and_collect_functions_tolerate_null_and_an_empty_engine);
    RUN(test_c_the_shared_resource_of_a_removed_node_is_freed_once_no_instance_can_still_use_it);
    RUN(test_c_installing_and_freeing_an_instance_both_reclaim_what_no_instance_can_use_any_more);
    RUN(test_c_running_out_of_memory_while_installing_changes_nothing_and_leaks_nothing);
    RUN(test_c_instances_in_other_threads_keep_answering_while_graphs_are_installed_and_knobs_move);
    RUN(test_c_calls_that_use_the_engines_lists_wait_for_its_lock_and_queries_never_do);
    RUN(test_c_many_nodes_added_in_any_order_keep_their_own_resources_across_installs_and_lose_them_with_the_node);
}
