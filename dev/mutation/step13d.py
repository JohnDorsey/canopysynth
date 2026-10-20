# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations for plan step 13's determinism tests (tests/c/test_determinism.c), as a FOCUSED campaign (see mutate.py: ARGS and ENV): only those tests judge each
fault. Run with
    python dev/mutation/mutate.py dev/mutation/step13d.py
Every one of them should be reported as caught. They are changes of arithmetic by one rounding (found by the recorded hashes: the formulas of the tests, which
use the library's own sample times, cannot see a change of the times themselves), faults that make an answer depend on what was asked before (found by the
cold instance, the random queries and the changes that cannot matter) and a span that leaves a float unwritten (found by the guarded buffers)."""
ENV = {"CANOPY_C_TESTS": "recorded_outputs_of_whole;recorded_graphs_answer;every_recorded_graph_gives;random_queries_of_a_long;installing_the_same_description_again_or;span_is_the_point"}
ARGS = ["-k", "zz_no_python_test_has_this_in_its_name"]

MUTATIONS = [
    ("E01 the file's interpolation is done in float, not in double", "src/canopy_fileread.c",
     "    return (float)(a + fraction * (b - a));", "    return (float)((float)a + (float)fraction * ((float)b - (float)a));"),
    ("E02 the filter's blend between two samples is done in float", "src/canopy_test_nodes.c",
     "    return (float)((double)y0 + fraction * ((double)y1 - (double)y0));", "    return (float)(y0 + (float)fraction * (y1 - y0));"),
    ("E03 the sample times of a span are rounded, not floored", "src/canopy_time.c",
     "    return plan->t0 + (i * plan->q + (i * plan->r) / plan->n);", "    return plan->t0 + (i * plan->q + (i * plan->r + plan->n / 2) / plan->n);"),
    ("E04 the filter resumes from the wrong one of the two values its cursor keeps", "src/canopy_test_nodes.c",
     "        if (filter->cursor_k + 1 <= k && filter->cursor_k + 1 > s) {\n            s = filter->cursor_k + 1;\n            y = filter->cursor_y[1];",
     "        if (filter->cursor_k + 1 <= k && filter->cursor_k + 1 > s) {\n            s = filter->cursor_k + 1;\n            y = filter->cursor_y[0];"),
    ("E05 checkpoints made under other settings are kept when a setting of the filter changes", "src/canopy_test_nodes.c",
     "    if (!filter->have_stamp || stamp != filter->stamp) {", "    if (!filter->have_stamp) {"),
    ("E06 before its first sample the filter answers 0 instead of its initial value", "src/canopy_test_nodes.c",
     "        *y0 = run->initial;\n        *y1 = k + 1 < 0 ? run->initial : y_at(run, 0);", "        *y0 = 0.0f;\n        *y1 = k + 1 < 0 ? 0.0f : y_at(run, 0);"),
    ("E07 a span of a boundary inlet leaves its last float unwritten", "src/canopy_boundary.c",
     "    for (i = 0; i < n; i++) out[i] = value;", "    for (i = 0; i < n - 1; i++) out[i] = value;"),
]
