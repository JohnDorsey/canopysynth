/* A tiny C test harness. A test is `static void test_name(void)`; CHECK(cond) records a failure (and keeps going).
   List tests in a file's `void register_<file>(void)` with RUN(test_name); main() in run_c_tests.c calls every register function. */
#ifndef CTEST_H
#define CTEST_H

#include <stdio.h>

extern int ctest_passed, ctest_failed, ctest_current_failed;

#define CHECK(cond) do { if (!(cond)) { ctest_current_failed = 1; \
    printf("    check failed: %s (%s:%d)\n", #cond, __FILE__, __LINE__); } } while (0)

/* Compares two integers and prints both when they differ (statuses, counts, times...). */
#define CHECK_INT(actual, expected) do { long long ctest_a = (long long)(actual), ctest_e = (long long)(expected); \
    if (ctest_a != ctest_e) { ctest_current_failed = 1; \
        printf("    check failed: %s == %s: got %lld, expected %lld (%s:%d)\n", #actual, #expected, ctest_a, ctest_e, __FILE__, __LINE__); } } while (0)

/* In the debug-heap build (run_c_tests_debug.exe) this validates the whole C heap, so a write past the end of any malloc'd block is
   caught at once; in the normal build it is always true. */
int ctest_heap_ok(void);
#define CHECK_HEAP() CHECK(ctest_heap_ok())

/* The name of the test that is running: if the program crashes, the handler in run_c_tests.c says which test it was. */
extern const char *ctest_current_name;

#define RUN(fn) do { ctest_current_failed = 0; ctest_current_name = #fn; fn(); \
    if (ctest_current_failed) { ctest_failed++; printf("  FAIL  %s\n", #fn); } \
    else { ctest_passed++; printf("  PASS  %s\n", #fn); } \
    fflush(stdout); } while (0)

#endif
