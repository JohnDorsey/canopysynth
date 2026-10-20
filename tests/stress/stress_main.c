/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The stand-alone stress program (plan step 13): stress_run of tests/c/test_stress.c for as long as asked, with the figures printed at the end.
     stress.exe [seconds] [--seed N] [--readers N] [--no-preview] [--quiet]
   Built by `build.ps1 -Stress` in three flavours, like the C tests: build\stress.exe (optimised), build\stress_debug.exe (the MSVC debug runtime: the heap is
   validated at every 16th heap operation, and leaked blocks are reported at the end) and build\stress_asan.exe (AddressSanitizer).
   Exit code 0: every check passed; 1: a problem was found; 2: bad arguments; 3: the watchdog found that nothing had moved for 20 seconds. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef CANOPY_DEBUG_HEAP
#include <crtdbg.h>
#endif
#include <windows.h>
#include "../c/ctest.h"
#include "../c/stress.h"

/* what the C tests' harness (tests/c/run_c_tests.c) defines and the shared test code uses */
int ctest_passed = 0, ctest_failed = 0, ctest_current_failed = 0;
const char *ctest_current_name = "(stress)";

int ctest_selected(const char *name)
{
    (void)name;
    return 1;
}

int ctest_heap_ok(void)
{
#ifdef CANOPY_DEBUG_HEAP
    return _CrtCheckMemory();
#else
    return 1;
#endif
}

static int usage(void)
{
    printf("usage: stress [seconds] [--seed N] [--readers N] [--no-preview] [--quiet]\n");
    return 2;
}

int main(int argc, char **argv)
{
    StressOptions options;
    StressResult result;
    int i, ok, leaked = 0;
    options.seconds = 10.0;
    options.seed = 1;
    options.readers = 4;
    options.preview = 1;
    options.verbose = 1;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) options.seed = (uint64_t)strtoull(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--readers") == 0 && i + 1 < argc) options.readers = atoi(argv[++i]);
        else if (strcmp(argv[i], "--no-preview") == 0) options.preview = 0;
        else if (strcmp(argv[i], "--quiet") == 0) options.verbose = 0;
        else if (argv[i][0] != '-' && atof(argv[i]) > 0.0) options.seconds = atof(argv[i]);
        else return usage();
    }
#ifdef CANOPY_DEBUG_HEAP
    _CrtSetReportMode(_CRT_WARN, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_WARN, _CRTDBG_FILE_STDOUT);
    _CrtSetReportMode(_CRT_ERROR, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ERROR, _CRTDBG_FILE_STDOUT);
    _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDOUT);
    _CrtSetDbgFlag(_CRTDBG_ALLOC_MEM_DF | _CRTDBG_CHECK_EVERY_16_DF);
#endif
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    printf("stress: %.1f s, seed %llu, %d readers, preview %s\n", options.seconds, (unsigned long long)options.seed, options.readers, options.preview ? "on" : "off");
    fflush(stdout);
    ok = stress_run(&options, &result);
#ifdef CANOPY_DEBUG_HEAP
    if (_CrtDumpMemoryLeaks()) {
        printf("memory leaks detected\n");
        leaked = 1;
    }
#endif
    printf("stress: %s\n", ok && !leaked ? "PASSED" : "FAILED");
    return ok && !leaked ? 0 : 1;
}
