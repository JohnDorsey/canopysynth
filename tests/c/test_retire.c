/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Tests: what a node needs when other threads are around: retiring data it has replaced (canopy_ctx_retire: freed only when no query that began
   before can still be reading it) and the message a node keeps about itself (canopy_ctx_set_message, canopy_engine_node_message). */
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <process.h>
#include "support.h"

/* retire(1) -> sink(9).in0 */
static void retire_rig(Rig *rig)
{
    rig_open(rig);
    support_counters_reset();
    rig_node(rig, 1, "test.retire");
    rig_node(rig, 9, "test.sink");
    rig_connect(rig, 1, "out", 9, "in0");
    rig_install(rig);
}

static float number_seen(CanopyInstance *instance)
{
    return host_inlet_at(instance, 9, 0, 0);
}

static int local_released;

static void local_release(void *block)
{
    free(block);
    local_released++;
}

static void test_c_data_retired_with_no_context_is_released_at_once_and_nothing_is_a_no_op(void)
{
    local_released = 0;
    canopy_ctx_retire(NULL, malloc(8), local_release);                                  /* no engine to ask: nothing can be reading it */
    CHECK_INT(local_released, 1);
    canopy_ctx_retire(NULL, NULL, local_release);
    CHECK_INT(local_released, 1);
    canopy_ctx_retire(NULL, (void *)&local_released, NULL);                             /* no release function: nothing to do */
    CHECK_INT(local_released, 1);
}

static void test_c_replaced_data_is_freed_at_once_when_no_query_is_running(void)
{
    Rig rig;
    retire_rig(&rig);
    CHECK(number_seen(rig.instance) == 1.0f);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "swap"), CANOPY_OK);
    CHECK_INT(atomic_load(&support_released), 1);
    CHECK(number_seen(rig.instance) == 2.0f);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "swap"), CANOPY_OK);
    CHECK_INT(atomic_load(&support_released), 2);
    CHECK(number_seen(rig.instance) == 3.0f);
    rig_close(&rig);
    CHECK_INT(support_shared_destroyed, 1);
}

typedef struct {
    CanopyInstance *instance;
    float seen;
} Holder;

static unsigned __stdcall holder_main(void *argument)
{
    Holder *holder = (Holder *)argument;
    holder->seen = number_seen(holder->instance);
    return 0;
}

static void wait_until_inside(void)
{
    ULONGLONG deadline = GetTickCount64() + 5000;
    while (!atomic_load(&support_inside) && GetTickCount64() < deadline) Sleep(0);
    CHECK(atomic_load(&support_inside));
}

static void test_c_replaced_data_stays_until_the_query_that_may_be_reading_it_is_over(void)
{
    Rig rig;
    CanopyInstance *idle;
    Holder holder;
    HANDLE thread;
    retire_rig(&rig);
    idle = canopy_engine_new_instance(rig.engine);                                     /* an instance that is in no query does not matter */
    CHECK(idle != NULL);
    holder.instance = rig.instance;
    holder.seen = 0.0f;
    atomic_store(&support_hold, 1);
    thread = (HANDLE)_beginthreadex(NULL, 0, holder_main, &holder, 0, NULL);
    wait_until_inside();
    CHECK_INT(canopy_engine_action(rig.engine, 1, "swap"), CANOPY_OK);               /* the query inside has the old number in its hands */
    CHECK_INT(atomic_load(&support_released), 0);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(atomic_load(&support_released), 0);                                      /* collecting does not free what is still in use */
    atomic_store(&support_hold, 0);
    WaitForSingleObject(thread, INFINITE);
    CloseHandle(thread);
    CHECK(holder.seen == 1.0f);                                                        /* it read the old block, whole */
    CHECK_INT(atomic_load(&support_released), 0);                                      /* nobody has freed it yet: that is the editing thread's job */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(atomic_load(&support_released), 1);
    CHECK(number_seen(idle) == 2.0f);                                                  /* and a query that begins after the swap reads the new one */
    canopy_instance_free(idle);
    rig_close(&rig);
}

static void test_c_a_query_that_begins_after_the_swap_does_not_hold_the_old_data_back(void)
{
    Rig rig;
    CanopyInstance *second;
    Holder first, later;
    HANDLE threads[2];
    retire_rig(&rig);
    second = canopy_engine_new_instance(rig.engine);
    CHECK(second != NULL);
    first.instance = rig.instance; first.seen = 0.0f;
    later.instance = second; later.seen = 0.0f;
    atomic_store(&support_hold, 1);
    threads[0] = (HANDLE)_beginthreadex(NULL, 0, holder_main, &first, 0, NULL);
    wait_until_inside();
    CHECK_INT(canopy_engine_action(rig.engine, 1, "swap"), CANOPY_OK);
    threads[1] = (HANDLE)_beginthreadex(NULL, 0, holder_main, &later, 0, NULL);       /* begins after the swap, and waits in the hold too */
    Sleep(50);
    atomic_store(&support_hold, 0);
    WaitForMultipleObjects(2, threads, TRUE, INFINITE);
    CloseHandle(threads[0]);
    CloseHandle(threads[1]);
    CHECK(first.seen == 1.0f && later.seen == 2.0f);
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(atomic_load(&support_released), 1);
    canopy_instance_free(second);
    rig_close(&rig);
}

static void test_c_an_instance_freed_while_data_waits_for_it_is_forgotten_not_read_after_it_is_gone(void)
{
    Rig rig;
    CanopyInstance *held;
    Holder holder;
    HANDLE thread;
    retire_rig(&rig);
    held = canopy_engine_new_instance(rig.engine);
    CHECK(held != NULL);
    holder.instance = held; holder.seen = 0.0f;
    atomic_store(&support_hold, 1);
    thread = (HANDLE)_beginthreadex(NULL, 0, holder_main, &holder, 0, NULL);
    wait_until_inside();
    CHECK_INT(canopy_engine_action(rig.engine, 1, "swap"), CANOPY_OK);               /* the data now waits for `held` */
    atomic_store(&support_hold, 0);
    WaitForSingleObject(thread, INFINITE);                                             /* its query is over; nothing has collected yet */
    CloseHandle(thread);
    CHECK_INT(atomic_load(&support_released), 0);
    canopy_instance_free(held);                                                        /* freeing it collects: the data goes, and nothing looks at the freed instance */
    CHECK_INT(atomic_load(&support_released), 1);
    CHECK(number_seen(rig.instance) == 2.0f);
    rig_close(&rig);
}

static unsigned __stdcall swapper_main(void *argument)
{
    Rig *rig = (Rig *)argument;
    (void)canopy_engine_action(rig->engine, 1, "swap");
    return 0;
}

static void test_c_when_retiring_cannot_note_who_to_wait_for_it_waits_for_the_queries_itself(void)
{
    Rig rig;
    Holder holder;
    HANDLE reader, swapper;
    retire_rig(&rig);
    holder.instance = rig.instance;
    holder.seen = 0.0f;
    atomic_store(&support_hold, 1);
    reader = (HANDLE)_beginthreadex(NULL, 0, holder_main, &holder, 0, NULL);
    wait_until_inside();
    canopy_alloc_fail_after(0);                                                        /* no memory for the note: the call has to wait */
    swapper = (HANDLE)_beginthreadex(NULL, 0, swapper_main, &rig, 0, NULL);
    CHECK(WaitForSingleObject(swapper, 150) == WAIT_TIMEOUT);                          /* still waiting for the query in the reader */
    CHECK_INT(atomic_load(&support_released), 0);
    atomic_store(&support_hold, 0);
    WaitForSingleObject(reader, INFINITE);
    WaitForSingleObject(swapper, INFINITE);
    canopy_alloc_fail_after(-1);
    CloseHandle(reader);
    CloseHandle(swapper);
    CHECK(holder.seen == 1.0f);
    CHECK_INT(atomic_load(&support_released), 1);                                      /* freed once the query was over, with nothing left to collect */
    CHECK(number_seen(rig.instance) == 2.0f);
    rig_close(&rig);
}

static void test_c_retiring_works_when_memory_runs_out_and_leaks_nothing(void)
{
    int64_t n;
    for (n = 0; n < 4; n++) {
        Rig rig;
        retire_rig(&rig);
        canopy_alloc_fail_after(n);
        CHECK_INT(canopy_engine_action(rig.engine, 1, "swap"), CANOPY_OK);
        canopy_alloc_fail_after(-1);
        CHECK_INT(atomic_load(&support_released), 1);                                  /* (nothing was running: the fallback frees it at once) */
        CHECK(number_seen(rig.instance) == 2.0f);
        rig_close(&rig);
    }
}

static void test_c_a_node_message_is_kept_read_cut_to_the_buffer_and_cleared(void)
{
    Rig rig;
    char buffer[16];
    int32_t length = -1;
    retire_rig(&rig);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 0 && buffer[0] == '\0');                                           /* nothing said yet */
    CHECK_INT(canopy_engine_action(rig.engine, 1, "say"), CANOPY_OK);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 5 && strcmp(buffer, "hello") == 0);
    memset(buffer, 'q', sizeof buffer);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, 3, &length), CANOPY_OK);          /* too small: cut, terminated, full length */
    CHECK(length == 5 && strcmp(buffer, "he") == 0 && buffer[3] == 'q');
    length = -1;
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, NULL, 0, &length), CANOPY_OK);
    CHECK_INT(length, 5);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, NULL, 0, NULL), CANOPY_OK);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, NULL, 4, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, -1, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_node_message(NULL, 1, buffer, sizeof buffer, &length), CANOPY_ERR_ARGUMENT);
    CHECK_INT(canopy_engine_node_message(rig.engine, 77, buffer, sizeof buffer, &length), CANOPY_ERR_NODE);
    CHECK_INT(canopy_engine_node_message(rig.engine, 9, buffer, sizeof buffer, &length), CANOPY_OK);   /* a node that never spoke */
    CHECK(length == 0 && buffer[0] == '\0');
    CHECK_INT(canopy_engine_action(rig.engine, 1, "clear"), CANOPY_OK);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 0 && buffer[0] == '\0');
    canopy_ctx_set_message(NULL, "x");                                                 /* harmless */
    rig_close(&rig);
}

static void test_c_a_node_message_stays_with_the_node_across_installs_and_goes_with_it(void)
{
    Rig rig;
    CanopyGraph *without, *again;
    char buffer[16];
    int32_t length = -1;
    retire_rig(&rig);
    without = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(without, 9, "test.sink"), CANOPY_OK);
    again = canopy_graph_new();
    CHECK_INT(canopy_graph_add_node(again, 1, "test.retire"), CANOPY_OK);
    CHECK_INT(canopy_graph_add_node(again, 9, "test.sink"), CANOPY_OK);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "say"), CANOPY_OK);
    CHECK_INT(canopy_engine_set_graph(rig.engine, rig.graph), CANOPY_OK);              /* the same node, in another graph */
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 5);
    CHECK_INT(canopy_engine_set_graph(rig.engine, without), CANOPY_OK);                /* the node leaves... */
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_ERR_NODE);
    CHECK(number_seen(rig.instance) == 0.0f);                                          /* (the sink's inlet is a knob now; adopts the graph) */
    CHECK_INT(canopy_engine_collect(rig.engine), 1);
    CHECK_INT(canopy_engine_set_graph(rig.engine, again), CANOPY_OK);                  /* ...and comes back as a new node with nothing to say */
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 0);
    canopy_graph_free(without);
    canopy_graph_free(again);
    rig_close(&rig);
}

static void test_c_a_long_message_is_cut_at_a_character_boundary_and_a_message_needs_no_memory(void)
{
    Rig rig;
    char buffer[400];
    int32_t length = -1;
    retire_rig(&rig);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "long"), CANOPY_OK);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 255 && strlen(buffer) == 255);                                      /* cut to 255 bytes */
    CHECK_INT(canopy_engine_action(rig.engine, 1, "long_utf8"), CANOPY_OK);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 254 && (unsigned char)buffer[252] == 0xC3 && (unsigned char)buffer[253] == 0xA9);   /* not in the middle of a two-byte character */
    canopy_alloc_fail_after(0);
    CHECK_INT(canopy_engine_action(rig.engine, 1, "say"), CANOPY_OK);                  /* with no memory at all, a node can still say why */
    canopy_alloc_fail_after(-1);
    CHECK_INT(canopy_engine_node_message(rig.engine, 1, buffer, sizeof buffer, &length), CANOPY_OK);
    CHECK(length == 5 && strcmp(buffer, "hello") == 0);
    rig_close(&rig);
}

void register_test_retire(void)
{
    RUN(test_c_data_retired_with_no_context_is_released_at_once_and_nothing_is_a_no_op);
    RUN(test_c_replaced_data_is_freed_at_once_when_no_query_is_running);
    RUN(test_c_replaced_data_stays_until_the_query_that_may_be_reading_it_is_over);
    RUN(test_c_a_query_that_begins_after_the_swap_does_not_hold_the_old_data_back);
    RUN(test_c_an_instance_freed_while_data_waits_for_it_is_forgotten_not_read_after_it_is_gone);
    RUN(test_c_when_retiring_cannot_note_who_to_wait_for_it_waits_for_the_queries_itself);
    RUN(test_c_retiring_works_when_memory_runs_out_and_leaks_nothing);
    RUN(test_c_a_node_message_is_kept_read_cut_to_the_buffer_and_cleared);
    RUN(test_c_a_node_message_stays_with_the_node_across_installs_and_goes_with_it);
    RUN(test_c_a_long_message_is_cut_at_a_character_boundary_and_a_message_needs_no_memory);
}
