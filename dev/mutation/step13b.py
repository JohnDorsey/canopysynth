"""The mutations for plan step 13's WAV tests (tests/c/test_wavfuzz.c, with the overrun sweep that also reads the file node), as a FOCUSED campaign (see mutate.py:
ARGS and ENV): only those tests judge each fault. Run with
    python dev/mutation/mutate.py dev/mutation/step13b.py
Every one of them should be reported as caught. They are faults in the file node's loader (canopy_fileread.c): memory it gets wrong (found by the debug heap and
AddressSanitizer, which the focused run reaches when the normal run passes), channels it reads wrongly (found by the first samples of the valid files), formats it
refuses, and what it forgets to free (found by the leak check of each rig)."""
F = "src/canopy_fileread.c"

ENV = {"CANOPY_C_TESTS": "every_valid_file_loads;valid_files_with_other_chunks;damaged_files_are_refused;no_span_query_writes_outside"}
ARGS = ["-k", "zz_no_python_test_has_this_in_its_name"]

MUTATIONS = [
    ("W01 the right channel starts one float late", F, "data->right = stored == 2 ? data->block + frames : data->block;", "data->right = stored == 2 ? data->block + frames + 1 : data->block;"),
    ("W02 the samples' memory is one float short", F, "(size_t)((frames ? frames : 1) * stored) * sizeof(float));", "(size_t)((frames ? frames : 1) * stored - 1) * sizeof(float));"),
    ("W03 dr_wav's read buffer is one float short", F, "buffer = (float *)canopy_alloc((size_t)(chunk * (uint64_t)channels) * sizeof(float));", "buffer = (float *)canopy_alloc((size_t)(chunk * (uint64_t)channels) * sizeof(float) - sizeof(float));"),
    ("W04 a stereo file is stored as mono", F, "stored = channels == 1 ? 1u : 2u;", "stored = 1u;"),
    ("W05 the right channel is read from the left", F, "data->right[got + i] = buffer[i * (uint64_t)channels + 1];", "data->right[got + i] = buffer[i * (uint64_t)channels];"),
    ("W06 24-bit files are refused", F, "wav.bitsPerSample == 24 ||", "wav.bitsPerSample == 25 ||"),
    ("W07 a time at the frame after the last reads past the samples", F, "if (k < 0 || k > data->frames - 1) return 0.0f;", "if (k < 0 || k > data->frames) return 0.0f;"),
    ("W08 the read buffer is not freed after a load", F, "    canopy_free(wide);\n    canopy_free(buffer);\n    if (ok) {", "    canopy_free(wide);\n    if (ok) {"),
    ("W09 the samples of a replaced file are not freed", F, "    canopy_free(data->block);\n    canopy_free(data);\n}", "    canopy_free(data);\n}"),
    ("W10 the first channel is read from the second column", F, "data->left[got + i] = buffer[i * (uint64_t)channels];", "data->left[got + i] = buffer[i * (uint64_t)channels + (channels > 1 ? 1 : 0)];"),
]
