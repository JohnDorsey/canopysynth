/* Runs every C test. Output: one "  PASS  name" / "  FAIL  name" line per test, then "N passed, M failed". Exit code 1 if any failed.
   Built twice by build.ps1: normally (run_c_tests.exe) and, with CANOPY_DEBUG_HEAP, against the MSVC debug runtime (run_c_tests_debug.exe):
   there every heap operation validates the whole heap, ctest_heap_ok() can be asked at any time, and leaked blocks are reported at the end. */
#include <stdio.h>
#include "ctest.h"

#ifdef CANOPY_DEBUG_HEAP
#include <crtdbg.h>
#endif
#ifdef _WIN32
#include <windows.h>
#endif

int ctest_passed = 0, ctest_failed = 0, ctest_current_failed = 0;
const char *ctest_current_name = "(none yet)";

#ifdef _WIN32
static LONG WINAPI crash_handler(EXCEPTION_POINTERS *info)
{
    printf("\nCRASH in test %s (exception 0x%08lx)\n", ctest_current_name, (unsigned long)info->ExceptionRecord->ExceptionCode);
    fflush(stdout);
    return EXCEPTION_EXECUTE_HANDLER;
}
#endif

#ifdef CANOPY_DEBUG_HEAP
int ctest_heap_ok(void)
{
    return _CrtCheckMemory();
}
#else
int ctest_heap_ok(void)
{
    return 1;
}
#endif

void register_test_skeleton(void);
void register_test_time(void);
void register_test_registry(void);
void register_test_alloc(void);
void register_test_graph(void);
void register_test_query(void);
void register_test_scratch(void);
void register_test_state(void);
void register_test_swap(void);

int main(void)
{
    int leaked = 0;
#ifdef _WIN32
    SetUnhandledExceptionFilter(crash_handler);
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);        /* no "program has stopped working" dialog */
#endif
#ifdef CANOPY_DEBUG_HEAP
    _CrtSetReportMode(_CRT_WARN, _CRTDBG_MODE_FILE);                /* reports go to stdout, not into a dialog box */
    _CrtSetReportFile(_CRT_WARN, _CRTDBG_FILE_STDOUT);
    _CrtSetReportMode(_CRT_ERROR, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ERROR, _CRTDBG_FILE_STDOUT);
    _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDOUT);
    _CrtSetDbgFlag(_CRTDBG_ALLOC_MEM_DF | _CRTDBG_CHECK_ALWAYS_DF);
#endif
    register_test_skeleton();
    register_test_time();
    register_test_registry();
    register_test_alloc();
    register_test_graph();
    register_test_query();
    register_test_scratch();
    register_test_state();
    register_test_swap();
    printf("\n%d passed, %d failed\n", ctest_passed, ctest_failed);
#ifdef CANOPY_DEBUG_HEAP
    if (_CrtDumpMemoryLeaks()) {
        printf("memory leaks detected\n");
        leaked = 1;
    }
#endif
    return (ctest_failed || leaked) ? 1 : 0;
}
