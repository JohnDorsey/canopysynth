# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations of plan step 13's new tests, as FOCUSED campaigns (see mutate.py: ARGS and ENV): only the tests under examination judge each fault, so that
what a campaign reports is what they catch on their own, not what the older tests would have caught first. Run with
    python dev/mutation/mutate.py dev/mutation/step13.py
Every one of them should be reported as caught. This file holds the faults for tests/c/test_overrun.c (a write one float past a buffer, a span or an n that
is accepted when it must not be, a failure that is not zero-filled, the preview's callback, the scratch arena's edge). Faults for the other new tests are
in step13b.py and step13c.py (they need other filters)."""
C = "src/canopy_instance.c"
F = "src/canopy_fileread.c"
P = "src/canopy_preview.c"
B = "src/canopy_boundary.c"
T = "src/canopy_test_nodes.c"
H = "src/canopy_internal.h"

ENV = {"CANOPY_C_TESTS": "no_span_query_writes_outside;a_span_with_a_bad_n_touches_nothing;point_queries_at_the_ends_of_time;preview_callback_writes_exactly"}
ARGS = ["-k", "zz_no_python_test_has_this_in_its_name"]

MUTATIONS = [
    # ---- a write past the end ----
    ("O01 a zero fill is one float too long", C, "    memset(out, 0, (size_t)n * sizeof(float));", "    memset(out, 0, (size_t)(n + 1) * sizeof(float));"),
    ("O02 a knob's span is one float too long", C, "        for (i = 0; i < n; i++) out[i] = knob;", "        for (i = 0; i <= n; i++) out[i] = knob;"),
    ("O03 a derived span runs one sample too far", C, "for (i = 0; i < n && status == CANOPY_OK; i++) {", "for (i = 0; i <= n && status == CANOPY_OK; i++) {"),
    ("O04 the file node's span is one float too long", F, "for (i = 0; i < n; i++) out[i] = data ? sample_at(", "for (i = 0; i <= n; i++) out[i] = data ? sample_at("),
    ("O05 a boundary inlet's span is one float too long", B, "for (i = 0; i < n; i++) out[i] = value;", "for (i = 0; i <= n; i++) out[i] = value;"),
    ("O06 the filter's span is one float too long", T, "for (i = 0; i < n; i++) out[i] = value_at(&run, canopy_span_plan_time(&plan, i));", "for (i = 0; i <= n; i++) out[i] = value_at(&run, canopy_span_plan_time(&plan, i));"),
    # ---- what is accepted ----
    ("O07 an n one above the limit is accepted", C, "if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;", "if (n < 1 || n > CANOPY_MAX_N + 1) return CANOPY_ERR_N;"),
    ("O08 an n of zero is accepted", C, "if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;", "if (n < 0 || n > CANOPY_MAX_N) return CANOPY_ERR_N;"),
    ("O09 a span whose length is one past INT64_MAX is accepted", H, "(t0 < 0 && t1 > INT64_MAX + t0)", "(t0 < 0 && t1 > INT64_MAX + t0 + 1)"),
    ("O10 a backward span one beyond INT64_MIN is accepted", H, "(t0 > 0 && t1 < INT64_MIN + t0)", "(t0 > 0 && t1 < INT64_MIN + t0 - 1)"),
    ("O11 a span that fits exactly is refused", H, "(t0 < 0 && t1 > INT64_MAX + t0)", "(t0 < 0 && t1 >= INT64_MAX + t0)"),
    # ---- what a failure leaves behind ----
    ("O12 an overflowing span is not zero-filled", C, "        zero_fill(out, n);\n        return CANOPY_ERR_OVERFLOW;", "        return CANOPY_ERR_OVERFLOW;"),
    ("O13 a span that failed is not zero-filled", C, "    if (status != CANOPY_OK) zero_fill(out, n);", "    if (status != CANOPY_OK) {}"),
    ("O14 a point query that failed keeps what the node wrote", C, "    *out = status == CANOPY_OK ? value : 0.0f;", "    *out = value;"),
    # ---- the scratch arena's edge ----
    ("O15 the last scratch buffer that fits exactly is refused", C, "if (instance->arena_top + rounded > instance->arena_floats) return NULL;", "if (instance->arena_top + rounded >= instance->arena_floats) return NULL;"),
    # ---- the preview's callback ----
    ("O16 the preview writes one frame too many", P, "    for (i = 0; i < frames; i++) {\n        stereo[2 * i] = clip", "    for (i = 0; i <= frames; i++) {\n        stereo[2 * i] = clip"),
    ("O17 the preview's chunk is one frame too big", P, "#define BUFFER_FLOATS CANOPY_MAX_N", "#define BUFFER_FLOATS (CANOPY_MAX_N + 1)"),
    ("O18 a paused preview leaves its buffer alone", P, "if (!play_chunk(p, where, n)) memset(where, 0, (size_t)n * 2 * sizeof(float));", "if (!play_chunk(p, where, n)) {}"),
    ("O19 a paused preview's silence is one float short", P, "if (!play_chunk(p, where, n)) memset(where, 0, (size_t)n * 2 * sizeof(float));", "if (!play_chunk(p, where, n)) memset(where, 0, (size_t)n * 2 * sizeof(float) - sizeof(float));"),
    ("O20 the preview forgets the center inlet", P, "stereo[2 * i] = clip(left[i] + center[i]);", "stereo[2 * i] = clip(left[i]);"),
]
