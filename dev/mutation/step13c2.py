"""Fault T04 of step13c.py (collecting retired blocks does not wait for the queries that could read them) again, judged by the C tests of retiring (test_retire.c: the ones about replaced data, whose names do not say retire) instead of the stress:
the 2.5 s stress in the suite does not find it (the window is a query that is still reading a block that was retired a few milliseconds before, and the stress's file
spans are short), but the tests of retiring hold a query inside the node and then retire its data, which finds it at once. Run with
    python dev/mutation/mutate.py dev/mutation/step13c2.py
It should be reported as caught."""
ENV = {"CANOPY_C_TESTS": "replaced_data;retired;an_instance_freed_while_data_waits;retiring_cannot_note"}
ARGS = ["-k", "zz_no_python_test_has_this_in_its_name"]

MUTATIONS = [
    ("T04 collecting retired blocks does not wait for the queries that could read them", "src/canopy_retire.c",
     "            if ((uint64_t)atomic_load(&entry->waits[i].instance->epoch) == entry->waits[i].epoch) waiting = 1;", "            (void)i;"),
]
