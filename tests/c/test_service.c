/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The engine's own instances for nodes that run a thread of their own (CANOPY_FLAG_SERVICE, plan step 7): who may make one and when, how it is
   counted, how installs keep it up to date, and the order in which the engine lets go of it. The realtime preview node is the real user
   (test_preview.c); here a node type of the tests stands in for it. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "support.h"
#include "../../src/canopy_core.h"

static CanopyEngine *svc_engine;               /* the engine the test node types act on (a node has no way to reach its engine) */
static int svc_shared_available;               /* set by the actions: could this thread also have taken the lock shared? (0: it holds it exclusively) */
static int svc_destroyed, svc_graphs_at_destroy;
static CanopyInstance *svc_instance;           /* the instance the last "make" made */

typedef struct { CanopyInstance *instance; } SvcShared;

static void probe_lock(void)
{
    svc_shared_available = TryAcquireSRWLockShared(&svc_engine->lock) ? 1 : 0;
    if (svc_shared_available) ReleaseSRWLockShared(&svc_engine->lock);
}

static void *svc_create(CanopyCtx *ctx)
{
    (void)ctx;
    return calloc(1, sizeof(SvcShared));
}

static void svc_destroy(CanopyCtx *ctx, void *shared)
{
    SvcShared *s = (SvcShared *)shared;
    (void)ctx;
    svc_graphs_at_destroy = svc_engine->n_compiled;
    if (s->instance) {
        (void)canopy_instance_graph_serial(s->instance);          /* reads the graph the instance runs: it must still be there */
        canopy_service_instance_free(svc_engine, s->instance);
    }
    free(s);
    svc_destroyed++;
}

static void svc_action(CanopyCtx *ctx, const char *action)
{
    SvcShared *s = (SvcShared *)canopy_ctx_shared(ctx);
    probe_lock();
    if (!s) return;
    if (strcmp(action, "make") == 0 && !s->instance) {
        s->instance = canopy_service_instance_new(svc_engine);
        svc_instance = s->instance;
    } else if (strcmp(action, "drop") == 0 && s->instance) {
        canopy_service_instance_free(svc_engine, s->instance);
        s->instance = NULL;
        svc_instance = NULL;
    }
}

static void shared_action(CanopyCtx *ctx, const char *action)
{
    (void)ctx; (void)action;
    probe_lock();
}

/* a rig whose registry also has test_service (flag SERVICE) and test_shared (an ordinary node with an action) */
static void service_rig(Rig *rig)
{
    CanopyNodeType type;
    rig_open(rig);
    type = support_base_type("test_service", "Service");
    type.flags = CANOPY_FLAG_SERVICE;
    type.handlers.create_shared = svc_create; type.handlers.destroy_shared = svc_destroy; type.handlers.on_action = svc_action;
    support_add_builtin(rig->registry, &type);
    type = support_base_type("test_shared", "Shared");
    type.handlers.on_action = shared_action;
    support_add_builtin(rig->registry, &type);
    svc_engine = rig->engine;
    svc_shared_available = -1;
    svc_destroyed = 0;
    svc_graphs_at_destroy = -1;
    svc_instance = NULL;
}

/* a description with the service node 1, the sink 9, and `extra` constants (to make descriptions that differ) */
static CanopyGraph *service_graph(int with_service, int extra)
{
    CanopyGraph *graph = canopy_graph_new();
    int i;
    CHECK(graph != NULL);
    if (with_service) CHECK_INT(canopy_graph_add_node(graph, 1, "test_service"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(graph, 9, "test.sink"), CANOPY_OK);
    for (i = 0; i < extra; i++) CHECK_INT(canopy_graph_add_node(graph, 20 + i, "test.const"), CANOPY_OK);
    return graph;
}

static void test_c_the_actions_of_a_service_node_run_under_the_exclusive_lock_and_those_of_other_nodes_under_the_shared_one(void)
{
    Rig rig;
    service_rig(&rig);
    rig_node(&rig, 1, "test_service");
    rig_node(&rig, 2, "test_shared");
    rig_node(&rig, 9, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "nothing"), CANOPY_OK);
    CHECK_INT(svc_shared_available, 0);                                 /* the lock was held exclusively: this thread could not take it shared too */
    svc_shared_available = -1;
    CHECK_INT(canopy_engine_action(rig.engine, 2, "nothing"), CANOPY_OK);
    CHECK_INT(svc_shared_available, 1);                                 /* an ordinary node: held shared, as before */
    svc_shared_available = -1;
    CHECK_INT(canopy_engine_action(rig.engine, 77, "nothing"), CANOPY_ERR_NODE);
    CHECK_INT(svc_shared_available, -1);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "nothing"), CANOPY_OK);           /* the lock was let go again: this would hang otherwise */
    CHECK_INT(canopy_engine_node_count(rig.engine), 3);
    rig_close(&rig);
}

static void test_c_a_service_node_makes_an_instance_in_its_action_that_is_counted_apart_from_the_hosts_and_kept_up_to_date(void)
{
    Rig rig;
    CanopyGraph *second;
    service_rig(&rig);
    rig_node(&rig, 1, "test_service");
    rig_node(&rig, 9, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_service_count(rig.engine), 0);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "make"), CANOPY_OK);
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    CHECK(svc_instance != NULL);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "make"), CANOPY_OK);              /* the node decides; it has one */
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    second = service_graph(1, 3);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);
    if (svc_instance) {
        CHECK_INT(canopy_instance_graph_serial(svc_instance), canopy_engine_graph_serial(rig.engine) - 1);    /* not yet: it adopts at its next query */
        (void)host_inlet_at(svc_instance, 9, 0, 0);
        CHECK_INT(canopy_instance_graph_serial(svc_instance), canopy_engine_graph_serial(rig.engine));
    }
    CHECK_INT(canopy_engine_action(rig.engine, 1, "drop"), CANOPY_OK);
    CHECK_INT(canopy_engine_service_count(rig.engine), 0);
    canopy_graph_free(second);
    rig_close(&rig);
}

static void test_c_freeing_the_engine_is_refused_while_a_host_instance_exists_but_service_instances_do_not_count(void)
{
    Rig rig;
    service_rig(&rig);
    rig_node(&rig, 1, "test_service");
    rig_node(&rig, 9, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "make"), CANOPY_OK);
    CHECK_INT(canopy_engine_free(rig.engine), CANOPY_ERR_BUSY);                     /* the host's instance is still there; nothing was freed */
    CHECK_INT(svc_destroyed, 0);
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    canopy_instance_free(rig.instance);                                              /* the host's instance goes: the service instance alone does not hold the engine */
    rig.instance = NULL;
    rig_close(&rig);                                                                 /* canopy_engine_free must succeed, and free the service instance too */
    CHECK_INT(svc_destroyed, 1);
}

static void test_c_freeing_the_engine_stops_service_nodes_first_while_every_graph_they_may_refer_to_is_still_there(void)
{
    Rig rig;
    CanopyGraph *second, *third;
    service_rig(&rig);
    rig_node(&rig, 1, "test_service");
    rig_node(&rig, 9, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "make"), CANOPY_OK);              /* the service instance runs the first graph... */
    second = service_graph(1, 1);
    third = service_graph(1, 2);
    CHECK_INT(canopy_engine_set_graph(rig.engine, second), CANOPY_OK);              /* ...and never queries, so it stays there while two more are installed */
    CHECK_INT(canopy_engine_set_graph(rig.engine, third), CANOPY_OK);
    (void)host_inlet_at(rig.instance, 9, 0, 0);                           /* the host's instance has moved on */
    CHECK_INT(canopy_engine_collect(rig.engine), 3);                                 /* all three graphs are held, for the service instance's sake */
    canopy_instance_free(rig.instance);
    rig.instance = NULL;
    canopy_graph_free(second);
    canopy_graph_free(third);
    rig_close(&rig);
    CHECK_INT(svc_destroyed, 1);
    CHECK_INT(svc_graphs_at_destroy, 3);                                             /* it was destroyed before the first graph was freed (ASan sees the rest) */
}

static void test_c_a_service_instance_is_freed_with_its_node_once_every_graph_that_has_the_node_is_unused(void)
{
    Rig rig;
    CanopyGraph *without;
    service_rig(&rig);
    rig_node(&rig, 1, "test_service");
    rig_node(&rig, 9, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "make"), CANOPY_OK);
    without = service_graph(0, 0);
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);             /* the node is deleted */
    (void)host_inlet_at(rig.instance, 9, 0, 0);
    CHECK_INT(canopy_engine_collect(rig.engine), 2);                                 /* the first graph is held: the service instance still runs it */
    CHECK_INT(svc_destroyed, 0);
    CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    if (svc_instance) (void)host_inlet_at(svc_instance, 9, 0, 0);        /* its thread has moved on */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(svc_destroyed, 1);                                                     /* the node's resource went, and the instance with it */
    CHECK_INT(canopy_engine_service_count(rig.engine), 0);
    canopy_graph_free(without);
    rig_close(&rig);
}

static void test_c_installing_prepares_a_service_instance_like_a_hosts_and_running_out_of_memory_leaves_it_as_it_was(void)
{
    Rig rig;
    CanopyGraph *second;
    int k, failures = 0;
    int64_t serial_before;
    service_rig(&rig);
    rig_node(&rig, 1, "test_service");
    rig_node(&rig, 9, "test.sink");
    rig_install(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "make"), CANOPY_OK);
    second = service_graph(1, 4);
    for (k = 0; k < 400; k++) {
        int32_t status;
        serial_before = canopy_engine_graph_serial(rig.engine);
        canopy_alloc_fail_after(k);
        status = canopy_engine_set_graph(rig.engine, second);
        canopy_alloc_fail_after(-1);
        if (status == CANOPY_OK) break;
        failures++;
        CHECK_INT(status, CANOPY_ERR_MEMORY);
        CHECK_INT(canopy_engine_graph_serial(rig.engine), serial_before);            /* the old graph is still the installed one */
        if (svc_instance) {
            (void)host_inlet_at(svc_instance, 9, 0, 0);
            CHECK(canopy_instance_graph_serial(svc_instance) <= serial_before);      /* nothing was prepared for the service instance that it could adopt */
        }
        CHECK_INT(canopy_engine_service_count(rig.engine), 1);
    }
    CHECK(failures > 0);
    CHECK(k < 400);
    if (svc_instance) {
        (void)host_inlet_at(svc_instance, 9, 0, 0);
        CHECK_INT(canopy_instance_graph_serial(svc_instance), canopy_engine_graph_serial(rig.engine));    /* the install that worked reached it */
    }
    canopy_graph_free(second);
    rig_close(&rig);
}

static void test_c_the_service_flag_is_refused_to_third_party_types_and_accepted_for_built_in_ones(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type;
    CHECK(registry != NULL);
    type = support_base_type("vendor.service", "Service");
    type.flags = CANOPY_FLAG_SERVICE;
    CHECK_INT(canopy_registry_register(registry, &type), CANOPY_ERR_DESCRIPTOR);
    CHECK_INT(canopy_registry_count(registry), 0);
    type = support_base_type("service_node", "Service");
    type.flags = CANOPY_FLAG_SERVICE;
    CHECK_INT(canopy_registry_register_builtin(registry, &type), CANOPY_OK);
    CHECK_INT(canopy_registry_count(registry), 1);
    canopy_registry_free(registry);
}

void register_test_service(void)
{
    RUN(test_c_the_actions_of_a_service_node_run_under_the_exclusive_lock_and_those_of_other_nodes_under_the_shared_one);
    RUN(test_c_a_service_node_makes_an_instance_in_its_action_that_is_counted_apart_from_the_hosts_and_kept_up_to_date);
    RUN(test_c_freeing_the_engine_is_refused_while_a_host_instance_exists_but_service_instances_do_not_count);
    RUN(test_c_freeing_the_engine_stops_service_nodes_first_while_every_graph_they_may_refer_to_is_still_there);
    RUN(test_c_a_service_instance_is_freed_with_its_node_once_every_graph_that_has_the_node_is_unused);
    RUN(test_c_installing_prepares_a_service_instance_like_a_hosts_and_running_out_of_memory_leaves_it_as_it_was);
    RUN(test_c_the_service_flag_is_refused_to_third_party_types_and_accepted_for_built_in_ones);
}
