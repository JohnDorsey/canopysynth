# CLAUDE.md

Guidance for Claude Code when working in this folder. canopysynth is a standalone package (C engine + Python tkinter editor); it does not depend on
light_bounces. The specification is `docs/canopy_design.md` (FINAL; any change needs the author's permission) and the build plan, its rules and its
progress log are `docs/canopy_plan.md`: read the plan before every step and follow its reporting rule (end every step's summary with the next step and
the effort level to recommend).

## Commands

```
python run_tests.py                 # builds the DLL and three C test programs with MSVC, runs the C tests three times (normal, against the debug
                                    # heap, under AddressSanitizer) and the Python tests; one total (the extra runs add failures, leaks and
                                    # sanitizer reports to it, not passes)
python run_tests.py engine          # only the Python test file tests/python/test_engine.py (the C tests always run)
python run_tests.py -k build        # only Python tests whose name contains the text
python run_tests.py --no-build      # skip the build
python run_tests.py --no-debug      # skip the second, debug-heap run of the C tests
python run_tests.py --no-asan       # skip the third, AddressSanitizer run of the C tests
powershell -ExecutionPolicy Bypass -File build.ps1    # only the build
python dev/mutation/mutate.py dev/mutation/step3.py   # mutation check: breaks the C code in 83 specific ways, one at a time, and requires the
                                                      # suite to notice each (about 15 s each; add a spec file per step; step4.py has 134, step5.py 53, step6.py 64)
python dev/mutation/mutate.py dev/mutation/step4.py N01 P30  # only the mutations whose first word is one of these (here N01 and P30)
                                                      # (a mutation that deadlocks, like the lock ones K01 to K06, is stopped by the runner after
                                                      # CANOPY_TEST_TIMEOUT seconds, default 180: set it to 30 for such a run)
```

- Platform: Windows 64-bit, Python 3.9 or newer (tested on the installed 3.11), MSVC 2022 found through vswhere. Other operating systems are later.
- Layout:
  - `src/` the C library. Headers: `canopy.h` (status codes, time helpers), `canopy_node.h` (node-type descriptor, registry, and the context calls a
    node handler makes), `canopy_engine.h` (graph description, engine, instances: what a host calls), `canopy_internal.h` (allocation wrappers, pool,
    span plan, the boundary-slot flag: shared with the C tests, not exported), `canopy_core.h` (the private structures and the engine's lock).
    Sources: `canopy_alloc.c`, `canopy_time.c`, `canopy_registry.c`, `canopy_graph.c` (the description), `canopy_engine.c` (compile, the engine's
    host calls: knobs, boundary values, actions, collect), `canopy_install.c` (records per node ID and type, generation numbers, the sources
    upstream of each node, installing a graph as a transaction, reclaiming old graphs), `canopy_package.c` (instances, and the packages that move an
    instance to a newly installed graph), `canopy_instance.c` (queries, context calls, scratch arena), `canopy_test_nodes.c` (the hidden
    test-only node types, registered only by `canopy_registry_add_test_nodes`), `canopy_boundary.c` (the built-in boundary node types, registered
    by `canopy_registry_new`; tests that count types use `canopy_registry_new_empty`), `canopy_fileread.c` (the file node, with dr_wav), `canopy_retire.c`
    (retiring replaced data by per-instance epochs, and node messages), `canopy_version.c`.
  - `third_party/` vendored single headers, kept byte for byte as downloaded (LF line endings; provenance and hashes in its README): dr_wav.h is in;
    miniaudio.h is added at plan step 7. Each download needs the author's permission.
  - `canopysynth/` the Python package (the built `canopysynth.dll` is written into it).
  - `tests/c/` plain C: `ctest.h` (`CHECK`, `CHECK_INT`, `CHECK_HEAP`, `RUN`), `support.c/.h` (guarded output buffers, the `test.*` node types, the `Rig`
    that builds a graph, engine and instance and checks for leaks on `rig_close`), one `test_<area>.c` per area registered in `run_c_tests.c`.
  - `tests/python/` plain `test_*` functions; `engine_dll.py` has the ctypes bindings and a way to write node types in Python (tests only).
  - `dev/mutation/` the mutation check; `docs/`; `build/` (generated).
- Test names are unique: C tests start with `test_c_`, Python tests with `test_py_`.
- Delivery counter: `CANOPYSYNTH_BUILD`, bumped by exactly 1 once per finished prompt that changed code. It lives in `src/canopy.h` and
  `canopysynth/version.py` (a test checks they agree); the DLL exports it.
- Compiler flags: C11 with `/experimental:c11atomics`, /O2 /W4 /WX, `/fp:precise` (no fast-math: the determinism rule), `_CRT_SECURE_NO_WARNINGS`. No
  128-bit integers. Atomics: C11 `<stdatomic.h>`. No Python-tier nodes in version 1.
- Memory checks: `run_c_tests_debug.exe` (/Od /RTC1, MSVC debug runtime, whole-heap validation at every heap operation, leak report) and
  `run_c_tests_asan.exe` (`/fsanitize=address`: out-of-bounds reads and writes, use after free, with a report naming the line; needs the "C++
  AddressSanitizer" Visual Studio component, installed here; `build.ps1` skips it quietly where it is missing, and copies the runtime DLL next to
  the program; it runs with `ASAN_OPTIONS=allocator_may_return_null=1` because one test asks for an impossible allocation).
- Rules for the C code: every allocation in `src/` goes through `canopy_alloc`, `canopy_realloc`, `canopy_free` or a `CanopyPool` (never `malloc`,
  `calloc` or `free` directly), so that tests can count live blocks and make the Nth allocation fail; the query path allocates nothing, frees
  nothing and takes no lock (a C test holds the engine's lock itself and checks that queries go through while every other call waits); a span query
  that fails leaves `out` zero-filled (all n floats when n is valid); the knob and boundary slots store the value first and bump the generation
  second (see `canopy_core.h`). The engine's lock (`CanopyLock`, an SRW lock) is taken exclusively by installing, making and freeing instances and
  collecting, and shared by the host calls that only use the lists (knob and boundary writes, actions, counts); an instance applies the packages
  prepared for it at the start of a query by swapping pointers, and the editing thread frees what it has finished with (`canopy_instance_reap`).
- Tests of threads must not depend on the scheduler: pace the writer by the readers' progress (see `wait_for_progress` in `test_swap.c`), never by
  hoping that the readers got time. A test that holds the lock itself is deterministic for the correct code (it waits for the calls that must go
  through and then 100 ms for the ones that must not).
- The shell tool mangles backslashes in heredocs: edit files with the Edit/Write tools or run a script file, not an inline `python - <<EOF`.
- Line endings: CRLF for all source and text files (Windows); the Write tool makes LF files, so convert new ones (a script that rewrites `\r\n`).
- No git for now.
