# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations of plan step 6 (retiring replaced data, node messages, the FileReadNode): run with
    python dev/mutation/mutate.py dev/mutation/step6.py
Every one of them should be reported as caught; see mutate.py. (A name starting T is canopy_retire.c, F canopy_fileread.c, I canopy_instance.c,
K canopy_install.c, P canopy_package.c.) A mutation that hangs a test is stopped by run_tests.py after CANOPY_TEST_TIMEOUT seconds (C programs) or
30 s (a Python test): run with CANOPY_TEST_TIMEOUT=60."""
T = "src/canopy_retire.c"
F = "src/canopy_fileread.c"
I = "src/canopy_instance.c"
K = "src/canopy_install.c"
P = "src/canopy_package.c"

MUTATIONS = [
    # ---- retiring ----
    ("T01 retired data is freed at once whatever runs", T, "        if (epoch & 1u) {\n            waits[count].instance", "        if ((epoch & 1u) && count < 0) {\n            waits[count].instance"),
    ("T02 only instances between queries are waited for", T, "        if (epoch & 1u) {\n            waits[count].instance", "        if (!(epoch & 1u)) {\n            waits[count].instance"),
    ("T03 retired data is never freed by a collect", T, "        if (waiting) {\n            link = &entry->next;", "        if (waiting || 1) {\n            link = &entry->next;"),
    ("T04 collect frees data a query is still in", T, "if ((uint64_t)atomic_load(&entry->waits[i].instance->epoch) == entry->waits[i].epoch) waiting = 1;",
     "if ((uint64_t)atomic_load(&entry->waits[i].instance->epoch) != entry->waits[i].epoch) waiting = 1;"),
    ("T05 an instance that is freed is still waited for", T, "            if (entry->waits[i].instance == instance) entry->waits[i] = entry->waits[--entry->n_waits];\n            else i++;",
     "            if (entry->waits[i].instance == instance && i < 0) entry->waits[i] = entry->waits[--entry->n_waits];\n            else i++;"),
    ("T06 retired entry is not linked in", T, "    entry->next = engine->retired;\n    engine->retired = entry;\n", "    entry->next = engine->retired;\n"),
    ("T07 the fallback does not wait for the queries", T, "            while ((epoch & 1u) && (uint64_t)atomic_load(&engine->instances[k]->epoch) == epoch) SwitchToThread();",
     "            (void)epoch;"),
    ("T08 entry leaks its list of waits", T, "    canopy_free(entry->waits);\n    canopy_free(entry);\n}", "    canopy_free(entry);\n}"),
    ("T09 data with no engine is never released", T, "    if (!engine) {                                       /* no engine to ask: nothing can be in a query that reads it */\n        release(block);\n        return;\n    }",
     "    if (!engine) {\n        return;\n    }"),
    ("T10 the block is not released when nothing runs", T, "    if (count == 0) {                                    /* no query is running: the old block is already unreachable */\n        canopy_free(entry);\n        canopy_free(waits);\n        release(block);\n        return;\n    }",
     "    if (count == 0) {\n        canopy_free(entry);\n        canopy_free(waits);\n        return;\n    }"),
    # ---- the epoch of an instance ----
    ("I30 a query does not make the epoch odd", I, "    atomic_fetch_add_explicit(&instance->epoch, 1, memory_order_seq_cst);          /* odd: a query is running (see canopy_ctx_retire) */\n", ""),
    ("I31 a query leaves the epoch odd", I, "    atomic_fetch_add_explicit(&instance->epoch, 1, memory_order_seq_cst);          /* even again */\n", ""),
    ("K01 reclaiming does not collect retired data", K, "        canopy_free_graph(engine, oldest);\n    }\n    canopy_retire_collect(engine);\n}", "        canopy_free_graph(engine, oldest);\n    }\n}"),
    ("P40 freeing an instance does not forget it", P, "    canopy_retire_forget(engine, instance);\n", ""),
    # ---- messages ----
    ("T20 a message is not cut", T, "    if (length > CANOPY_MESSAGE_BYTES - 1) {", "    if (length > CANOPY_MESSAGE_BYTES * 10) {"),
    ("T21 a message is cut one byte too long", T, "        length = CANOPY_MESSAGE_BYTES - 1;\n", "        length = CANOPY_MESSAGE_BYTES;\n"),
    ("T22 a message is cut in the middle of a character", T, "        while (length > 0 && ((unsigned char)text[length] & 0xC0u) == 0x80u) length--;\n", ""),
    ("T23 a message is not terminated", T, "    record->message[length] = '\\0';\n", ""),
    ("T24 the message length reported is the cut length", T, "        if (length) *length = (int32_t)size;", "        if (length) *length = (int32_t)(size < (size_t)capacity ? size : (size_t)capacity);"),
    ("T25 a cut message is not terminated", T, "            buffer[copied] = '\\0';\n", ""),
    ("T26 an unknown node gives an empty message", T, "    if (!node) {\n        status = CANOPY_ERR_NODE;\n    } else {\n        size_t size;", "    if (!node) {\n        status = CANOPY_OK;\n    } else {\n        size_t size;"),
    ("T27 NULL buffer with a capacity is accepted", T, "    if (!engine || capacity < 0 || (capacity > 0 && !buffer)) return CANOPY_ERR_ARGUMENT;", "    if (!engine || capacity < 0) return CANOPY_ERR_ARGUMENT;"),
    ("T28 a message is copied one byte short", T, "            size_t copied = size < (size_t)capacity - 1 ? size : (size_t)capacity - 1;\n            if (copied) memcpy(buffer, node->record->message, copied);",
     "            size_t copied = size < (size_t)capacity - 1 ? size : (size_t)capacity - 1;\n            if (copied) memcpy(buffer, node->record->message, copied - 1);"),
    # ---- loading ----
    ("F01 relative paths accepted", F, "    if (!absolute_path(path)) {", "    if (absolute_path(path) && absolute_path(path) < 0) {"),
    ("F02 a missing file is not told apart", F, "    if (attributes == INVALID_FILE_ATTRIBUTES) {", "    if (attributes == 0x12345u) {"),
    ("F03 a directory is not told apart", F, "    if (attributes & FILE_ATTRIBUTE_DIRECTORY) {", "    if (attributes & 0x40000000u) {"),
    ("F04 24-bit PCM refused", F, "wav.bitsPerSample == 16 || wav.bitsPerSample == 24 ||\n                                                              wav.bitsPerSample == 32)) ||",
     "wav.bitsPerSample == 16 ||\n                                                              wav.bitsPerSample == 32)) ||"),
    ("F05 64-bit float accepted", F, "(wav.translatedFormatTag == DR_WAVE_FORMAT_IEEE_FLOAT && wav.bitsPerSample == 32))", "(wav.translatedFormatTag == DR_WAVE_FORMAT_IEEE_FLOAT))"),
    ("F06 any format tag accepted", F, "if (!((wav.translatedFormatTag == DR_WAVE_FORMAT_PCM && (wav.bitsPerSample", "if (!((wav.translatedFormatTag != 12345 && (wav.bitsPerSample"),
    ("F07 mono stored as two channels", F, "    stored = channels == 1 ? 1u : 2u;", "    stored = 2u;"),
    ("F08 the right channel is the left", F, "                if (stored == 2) data->right[got + i] = buffer[i * (uint64_t)channels + 1];", "                if (stored == 2) data->right[got + i] = buffer[i * (uint64_t)channels];"),
    ("F09 the left channel is the second one", F, "                data->left[got + i] = buffer[i * (uint64_t)channels];", "                data->left[got + i] = buffer[i * (uint64_t)channels + (channels > 1 ? 1 : 0)];"),
    ("F11 the sample rate is not kept", F, "        data->rate = wav.sampleRate;", "        data->rate = 48000;"),
    ("F13 the data block leaks when loading fails", F, "    } else if (data) {\n        data_release(data);\n    }", "    }"),
    ("F14 the temporary buffer leaks", F, "    canopy_free(wide);\n    canopy_free(buffer);\n    if (ok) {", "    canopy_free(wide);\n    if (ok) {"),
    ("F15 the wide path leaks", F, "    canopy_free(wide);\n    canopy_free(buffer);\n    if (ok) {", "    canopy_free(buffer);\n    if (ok) {"),
    # ---- the node ----
    ("F20 the file of the first graph is not loaded", F, "    if (shared && path[0]) {", "    if (shared && path[0] && 0 == 1) {"),
    ("F21 a failed first load says nothing", F, "        else canopy_ctx_set_message(ctx, why);           /* the node is silent and flagged */\n", "\n"),
    ("F22 destroying the node keeps its samples", F, "    if (data) data_release(data);                        /* (no graph has the node any more: no query can be reading it) */\n", "    (void)data;\n"),
    ("F23 any action opens the file", F, "    if (strcmp(action, \"open\") != 0) return;\n", "    (void)action;\n"),
    ("F24 open with no path does not say so", F, "    if (path[0] == '\\0') {\n        canopy_ctx_set_message(ctx, \"no file chosen\");\n        return;\n    }", "    if (path[0] == '\\0') {\n        return;\n    }"),
    ("F25 a failed open does not say why", F, "        canopy_ctx_set_message(ctx, why);                /* the old file stays */\n", ""),
    ("F26 a failed open drops the old file", F, "        canopy_ctx_set_message(ctx, why);                /* the old file stays */\n        return;", "        canopy_ctx_set_message(ctx, why);\n        old = atomic_exchange(&shared->data, (FileData *)NULL);\n        if (old) canopy_ctx_retire(ctx, old, data_release);\n        return;"),
    ("F27 a good open keeps the old message", F, "    canopy_ctx_set_message(ctx, \"\");\n    canopy_ctx_shared_changed(ctx);", "    canopy_ctx_shared_changed(ctx);"),
    ("F28 a good open does not tell downstream", F, "    canopy_ctx_shared_changed(ctx);\n    if (old) canopy_ctx_retire(ctx, old, data_release);", "    if (old) canopy_ctx_retire(ctx, old, data_release);"),
    ("F29 the old samples are never freed", F, "    if (old) canopy_ctx_retire(ctx, old, data_release);\n}", "}"),
    ("F30 the old samples are freed at once", F, "    if (old) canopy_ctx_retire(ctx, old, data_release);\n}", "    if (old) data_release(old);\n}"),
    ("F31 the new samples are not published", F, "    old = atomic_exchange(&shared->data, fresh);", "    old = atomic_load(&shared->data); data_release(fresh);"),
    # ---- the answers ----
    ("F40 the last frame is silent", F, "    if (k < 0 || k > data->frames - 1) return 0.0f;", "    if (k < 0 || k >= data->frames - 1) return 0.0f;"),
    ("F41 one frame beyond the last is read", F, "    if (k < 0 || k > data->frames - 1) return 0.0f;", "    if (k < 0 || k > data->frames) return 0.0f;"),
    ("F42 time before the file is not silence", F, "    if (k < 0 || k > data->frames - 1) return 0.0f;", "    if (k < -1 || k > data->frames - 1) return 0.0f;"),
    ("F43 after the last frame the last value goes on", F, "    if (k == data->frames - 1) return fraction == 0.0 ? samples[k] : 0.0f;", "    if (k == data->frames - 1) return samples[k];"),
    ("F44 no interpolation", F, "    return (float)(a + fraction * (b - a));", "    return (float)a;"),
    ("F45 interpolation towards the wrong frame", F, "    b = (double)samples[k + 1];", "    b = (double)samples[k > 0 ? k - 1 : 0];"),
    ("F46 interpolation in float arithmetic", F, "    return (float)(a + fraction * (b - a));", "    return (float)((float)a + (float)fraction * ((float)b - (float)a));"),
    ("F47 the outlets are swapped", F, '    *out = data ? sample_at(data, outlet == 1, t) : 0.0f;\n    return CANOPY_OK;\n}\n\nstatic int32_t file_span', '    *out = data ? sample_at(data, outlet == 0, t) : 0.0f;\n    return CANOPY_OK;\n}\n\nstatic int32_t file_span'),
    ("F48 a span of the right channel gives the left", F, "out[i] = data ? sample_at(data, outlet == 1, canopy_span_plan_time(&plan, i)) : 0.0f;", "out[i] = data ? sample_at(data, 0 * outlet, canopy_span_plan_time(&plan, i)) : 0.0f;"),
    ("F49 a span without a file is not silence", F, "out[i] = data ? sample_at(data, outlet == 1, canopy_span_plan_time(&plan, i)) : 0.0f;", "out[i] = data ? sample_at(data, outlet == 1, canopy_span_plan_time(&plan, i)) : 1.0f;"),
    ("F50 a span is placed from t1", F, "canopy_span_plan_time(&plan, i)) : 0.0f;", "canopy_span_plan_time(&plan, i) + 1) : 0.0f;"),
    ("F51 a span leaves its last sample", F, "    for (i = 0; i < n; i++) out[i] = data ? sample_at", "    for (i = 0; i < n - 1; i++) out[i] = data ? sample_at"),
    ("F52 a span writes one past out", F, "    for (i = 0; i < n; i++) out[i] = data ? sample_at", "    for (i = 0; i <= n; i++) out[i] = data ? sample_at"),
    ("F53 the node is not registered under file_read", F, "    type.key = \"file_read\";", "    type.key = \"file_reader\";"),
    ("F54 the node has no open button", F, "    type.n_widgets = 1; type.widgets = FILE_WIDGETS;\n", ""),
    ("F55 the right outlet is called differently", F, "{\"left\", \"Left\"}, {\"right\", \"Right\"}", "{\"left\", \"Left\"}, {\"right_channel\", \"Right\"}"),
]
