# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations for plan step 13's multi-thread stress (tests/c/test_stress.c), as a FOCUSED campaign (see mutate.py: ARGS and ENV): only the stress test judges
each fault, in the three C builds (normal, debug heap, AddressSanitizer). Run with
    python dev/mutation/mutate.py dev/mutation/step13c.py
They are faults in the concurrency core that no single-threaded test can show: memory that is freed while a thread still uses it (a graph an instance still
runs, the payload of a package its instance has not applied, retired file data a query still reads, an instance a retired block waits for) and an adoption
that does not keep up with the installs. The stress is statistical, and a fault whose window is a few nanoseconds can pass a 2.5 s run: the report of the
step says which of these the test in the suite catches and what the longer runs of the stand-alone program (build.ps1 -Stress) add. """
ENV = {"CANOPY_C_TESTS": "a_short_stress"}
ARGS = ["-k", "zz_no_python_test_has_this_in_its_name"]

MUTATIONS = [
    ("T01 reclaim frees graphs that an instance still runs", "src/canopy_install.c",
     "        if (oldest < floor) floor = oldest;", "        (void)oldest;"),
    ("T02 reap frees a package's payload before its instance has applied it", "src/canopy_package.c",
     "        if (!next || !atomic_load_explicit(&next->done, memory_order_acquire)) break;", "        if (!next) break;"),
    ("T03 a query does not mark its epoch odd (parity inverted: retiring waits for the idle instances, not the busy ones)", "src/canopy_instance.c",
     "    atomic_fetch_add_explicit(&instance->epoch, 1, memory_order_seq_cst);          /* odd: a query is running (see canopy_ctx_retire) */\n    return 1;",
     "    return 1;"),
    ("T04 collecting retired blocks does not wait for the queries that could read them", "src/canopy_retire.c",
     "            if ((uint64_t)atomic_load(&entry->waits[i].instance->epoch) == entry->waits[i].epoch) waiting = 1;", "            (void)i;"),
    ("T05 freeing an instance does not take it off the retired blocks' wait lists", "src/canopy_package.c",
     "    canopy_retire_forget(engine, instance);\n    instance_teardown(instance);", "    instance_teardown(instance);"),
    ("T06 an instance applies only one waiting package at the start of a query", "src/canopy_package.c",
     "    while ((next = atomic_load_explicit(&instance->applied->next, memory_order_acquire)) != NULL) {",
     "    if ((next = atomic_load_explicit(&instance->applied->next, memory_order_acquire)) != NULL) {"),
]
