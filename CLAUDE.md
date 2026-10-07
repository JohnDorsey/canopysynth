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
python run_tests.py --no-c          # skip the C tests altogether (for a run after a change to a Python file, which cannot change what they say)
python run_tests.py --fail-fast     # stop at the first failing test, and skip the C programs after a failing one; with --record-times FILE (write how long
                                    # each Python test took) and --order-by-times FILE (cheapest first by those times) it is what the mutation check runs
powershell -ExecutionPolicy Bypass -File build.ps1    # only the build (-Stress also builds build\stress.exe, stress_debug.exe and stress_asan.exe, the C multi-thread stress of plan
                                                      # step 13: `stress.exe [seconds] [--seed N] [--readers N] [--no-preview] [--quiet]`, exit code 3 when its watchdog finds
                                                      # that nothing moved for 20 s; -Bench also builds build\bench.exe, the timing measurements: `python dev/measure.py [bridge|editor|c|device]`)
python dev/stress.py [seconds] [--seed N]             # the Python-level stress (plan step 13): the real editor, off-screen, makes random edits through the public API while
                                                      # threads write a boundary inlet, read what it feeds, replace the file node's file and ask the engine what it holds
python dev/package.py [--no-build] [--out DIR]       # plan step 14: builds, then writes dist/canopysynth-1.0.0-py3-none-win_amd64.whl (a wheel written by hand: pip installs it) and
                                                      # dist/canopysynth-1.0.0-windows-x64.zip (the unzip-and-run folder: run_editor.bat, the package, docs, examples); checks the DLL's build number first
python -m canopysynth [graph.json] [--audio null]     # the stand-alone editor (canopysynth/app.py: a File menu round the Editor and a real Engine); run_editor.bat starts it from an unzipped folder
powershell -ExecutionPolicy Bypass -File dev/analyze.ps1   # static analysis of src/ (cl /analyze, the output filtered); a clean run prints no warning of ours
python dev/mutation/mutate.py dev/mutation/step3.py   # mutation check: breaks the C code in 83 specific ways, one at a time, and requires the
                                                      # suite to notice each (add a spec file per step; step4.py has 134, step5.py 53, step6.py 64,
                                                      # step7.py 142, step8.py 141, step9.py 76, step10.py 113, step11.py 178, step11b.py 39, step12.py 112,
                                                      # step12b.py 26, runner.py 75 (the two runners themselves), known.py 4 (two survivors and two
                                                      # detections, to check the runner); the step 13 specs are FOCUSED campaigns, judged by the new tests alone: step13.py 20 (the overrun
                                                      # sweep), step13b.py 10 (the WAV loader), step13c.py 6 and step13c2.py 1 (the stress), step13d.py 7 (determinism), step13e.py 7 (the argument
                                                      # checks of Engine) and step13f.py 11 (the sweep of the C API); the step 14 specs: step14.py 26 (dev/package.py and canopysynth/app.py, Python files) and step14b.py 12 (run_editor.bat, the example node, the documents: FOCUSED, ARGS package docs): a spec's `ENV` (for example CANOPY_C_TESTS) and `ARGS` (for example -k text) say which tests judge;
                                                      # step8.py (but for 9 of its faults), most of step9.py and every spec from step10.py on break Python files,
                                                      # for which the runner skips the build and the C tests, and a spec with AREAS = [...] (step11.py) runs only those
                                                      # Python test files; a run that crashes without a total is "caught"; the exit code is 0 only if every mutation was caught)
                                                      # Each run is a fast one: it stops at the first failing test, runs the cheapest tests first (by the times the
                                                      # campaign's first, whole run recorded) and after a mutation of a Python file leaves out the C tests; none of that can
                                                      # turn a survivor into a detection (see mutate.py). Add --thorough for the old way: every test of every run.
python dev/mutation/mutate.py dev/mutation/step4.py N01 P30  # only the mutations whose first word is one of these (here N01 and P30)
set CANOPY_C_TESTS=text;text  &  build\run_c_tests.exe      # (an environment variable of the C programs, also of the debug and sanitizer ones: only the C tests whose name contains one of the
                                                      # pieces run, so one or a few can be tried alone; python run_tests.py passes it on. Others: CANOPY_RECORD=1 prints the table of recorded hashes of
                                                      # test_determinism.c (rerecord only after a deliberate change of a node's arithmetic), CANOPY_FUZZ_ITERATIONS for the WAV fuzz,
                                                      # CANOPY_API_FUZZ_OPS and CANOPY_API_FUZZ_DICTS for the fuzz of the Python API)
                                                      # (a mutation that deadlocks, like the lock ones K01 to K06, is stopped by the runner after
                                                      # CANOPY_TEST_TIMEOUT seconds, default 180: set it to 30 for such a run)
python dev/listen_check.py --list                     # the audio devices of this machine; without --list: the listening check of plan step 7 (needs a person
                                                      # with ears: it plays test tones through the real preview node; --auto --backend null runs it silently)
python dev/editor_check.py                            # the real-window check of the editor (plan steps 10 and 11): a visible window driven by synthetic mouse events
                                                      # (--try leaves it open to use by hand; --offscreen --fast is what the tests run; --screenshot F.png)
```

- Other compilers (plan step 14b, an experiment): clang 19 (clang-cl, and the GNU driver with `-ffp-contract=off`) builds all 238 C tests and gives the same bits as MSVC for the twelve recorded graphs; letting the compiler fuse multiply-add (`-march=native` with clang's default) or using fast-math changes them, and the determinism test fails loudly. gcc and Linux were not tried (not installed here). The project's one supported compiler is MSVC.
- Platform: Windows 64-bit, Python 3.9 or newer (tested on the installed 3.11), MSVC 2022 found through vswhere. Other operating systems are later.
- Distribution (step 14): `README.md`, `run_editor.bat`, `docs/user_guide.md`, `docs/node_author_guide.md`, `docs/THIRD_PARTY_NOTICES.txt`, `examples/` (`section15.py`: the design's section 15 snippet that runs; `example_node.c`: a node type written
  in C and `use_example_node.py`, which registers it and queries it; build.ps1 builds `build\examples\example_node.dll` every time, so the example always compiles), `dev/package.py` (the wheel and the folder: the headers and the import library go into the package
  under `include/` and `lib/`), `canopysynth/app.py` and `__main__.py` (the stand-alone editor). `dist/` is generated (not in git). Every ```python block of README.md and docs/user_guide.md is run by `tests/python/test_docs.py`
  (write `# not run` on the first line of one that opens a window), and `tests/python/test_package.py` installs the wheel into a fresh virtual environment with pip, unzips the folder and runs `run_editor.bat` and the example.
  When a document says what a call prints, `test_docs.py` has the piece it must print (`EXPECTED`). The DLL imports only KERNEL32.dll (`/LD` links the C runtime statically): a test fails if that changes, because the packages promise no redistributable.
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
    (retiring replaced data by per-instance epochs, and node messages), `canopy_audio.c` (the only code that includes miniaudio: opens and lists
    playback devices; `canopy_audio.h`), `canopy_preview.c` (the realtime preview node and its exported calls), `canopy_version.c`.
  - `third_party/` vendored single headers, kept byte for byte as downloaded (LF line endings; provenance and hashes in its README): dr_wav.h and
    miniaudio.h are in. Each download needs the author's permission.
  - `canopysynth/` the Python package (the built `canopysynth.dll` is written into it): `helpers.py` (the public helper functions), `_lib.py`
    (loads and version-checks the DLL), `_descriptor.py` (ctypes mirror of the node-type descriptor), `errors.py` (`GraphError`, `BoundaryError`, `QueryError`), `catalog.py` (the
    node types a graph may name, read from a registry, and the migrations by type version), `_values.py` (checks of settings, knobs, positions),
    `graph.py` (the graph model: `Graph`, `Node`, `Port`, `to_dict` / `from_dict`), `_native.py` (the DLL with every function's types declared and
    the status codes), `engine.py` (the bridge: `Engine`, `Instance`; `QueryError` is in `errors.py`), `editor/` (the node editor: `theme.py` colours and sizes,
    `geometry.py` view, layout of nodes, ports, knobs and widgets, hit testing and shapes with no Tk in it, `canvas.py` the `Editor` Frame; `canopysynth.Editor` is imported when first
    used, so that importing the package does not load tkinter). Importing the package does not load the DLL;
    the first `Graph()` or `Engine()` does.
  - `tests/c/` plain C: `ctest.h` (`CHECK`, `CHECK_INT`, `CHECK_HEAP`, `RUN`), `support.c/.h` (guarded output buffers, the `test.*` node types, the `Rig`
    that builds a graph, engine and instance and checks for leaks on `rig_close`), one `test_<area>.c` per area registered in `run_c_tests.c`. Step 13 added
    `test_overrun.c` (every node and graph shape asked at every count and time shape, with canaries round the buffer and an oracle of its own for what overflows),
    `test_wavfuzz.c` (damaged WAV files: refused or played, never a crash, an overrun or a leak, and the same decision in every build), `test_stress.c` + `stress.h`
    (the multi-thread stress: `stress_run` is the test of the suite for 2.5 s and the stand-alone program of `tests/stress/stress_main.c` for as long as asked) and
    `test_determinism.c` (twelve whole graphs asked a fixed list of queries and their hashes recorded in a table, checked by all three C programs; and the properties:
    asked again, in reverse, by a cold instance, by other threads, after installs that cannot matter). `tests/bench/bench_main.c` is the timing program.
  - `tests/python/` plain `test_*` functions; `engine_dll.py` has the ctypes bindings and a way to write node types in Python (tests only); step 13 added
    `test_determinism.py` (the public API against the hash the C table records), `test_api_fuzz.py` (garbage arguments to every public call, and saved graphs damaged in
    random places: only the documented exceptions), `test_c_api.py` (the DLL's export table against the headers and against every ctypes declaration, and every one of the
    63 exported functions called with NULL and extreme arguments), `test_shutdown.py` (a process that ends while the preview plays; memory that runs out for real, with a
    job object), `stress_threads.py` + `test_stress_py.py` (the Python-level stress) and `fixtures`-free recordings: the only recorded outputs are in the C table;
    `graph_dll.py` builds a catalog of Python, built-in and hidden test types and converts a `Graph` into the C description to compile it in a real
    engine; `fixtures/graph_v1.json` is the hand-written version 1 file the saved format is pinned by (a format change must keep it loading);
    `test_editor_geometry.py` tests the editor's geometry, `test_editor.py` the widget in a real tkinter window placed at +6000+6000 (a withdrawn
    window gets no synthetic events; an off-screen one does, and nothing flashes) driven with `event_generate`, and `test_editor_controls.py` its knobs,
    widgets and menus (node types written as descriptor dicts there, no DLL rig), `test_editor_selection.py` rectangle selection and moving a selection, `test_editor_link.py` the editor with an Engine over the same graph
    (null audio), `test_editor_time.py` the hh:mm:ss.mmm text, `test_engine_controls.py` the Engine calls the editor uses, `test_runner.py` the test
    runner and the mutation runner themselves (a copy of run_tests.py in a throwaway project, and stubs for the programs and for `subprocess.run`).
    `python run_tests.py editor` runs only test_editor.py: use `editor_geometry`, `editor_controls` and `editor_selection` for the others. Tk gives every generated event the time 0, so two presses at one spot are a double click
    however far apart: the tests' `send` and the check script's `event` give each event a time of its own (a double-click test passes close times). The
    editor finds double clicks itself from the events' times (500 ms, 5 pixels), never through Tk's `<Double-...>` bindings, which proved unreliable.
  - A mutation campaign changes the project's own source files while it runs, so each campaign runs in a copy of the project of its own (`robocopy` the
    folder without `.git` and `__pycache__` and without a renamed `*.build*-in-use` DLL, run `mutate.py` there with `CANOPY_TEST_TIMEOUT=300`, log to a file),
    not more than three at a time (each starts with a whole run of the suite: since step 13 the C programs alone take 17 s, 52 s under the debug heap and 72 s under AddressSanitizer on a quiet machine, the Python tests 54 s, so the whole suite 209 s with the build), started about 75 s apart; and the machine must stay awake: call
    `request_keep_awake` with `session_idle` before waiting between turns (a sleeping machine killed the processes silently). A spec whose `old` text is no
    longer in its file is SKIPPED, which `mutate.py` reports and answers with exit code 1: the code moved, so the spec needs a new anchor (the runner
    cannot see that from a green total). The runner builds again before a mutation of a Python file that follows one of a C file. A log written with
    PowerShell's `*>` is UTF-16 here: read it with `Get-Content` (or decode it as `utf-16`); `grep` and `tail | grep` find nothing in it.
  - A running `python dev/editor_check.py --try` window keeps `canopysynth/canopysynth.dll` open, and the linker then cannot overwrite it: a loaded DLL
    can be renamed (`canopysynth.dll.build13-in-use` was, at step 11, and `build16-in-use` at build 17), after which the build writes a fresh one. Close the window and delete the old file.
  - `dev/mutation/` the mutation check; `dev/` also has `analyze.ps1`, `stress.py`, `measure.py`, `package.py`; `docs/` (`step13_measurements.txt` is the raw output of the measurements); `build/` (generated).
- Test names are unique: C tests start with `test_c_`, Python tests with `test_py_`.
- The Python bridge checks the arguments of `Engine.action`, `node_message` and the `preview_*` calls like those of `set_knob` (a node ID is a whole number in 64 bits, an action is
  text: `GraphError` otherwise; a closed engine is `RuntimeError` first): ctypes cuts an int to 64 bits without a word, so an unchecked ID presses another node's button.
- Version numbers: five independent ones (release `1.0.0` in MAJOR.MINOR.PATCH form, saved-graph format, descriptor layout, node type version, delivery counter); what raises each is in
  `docs/canopy_plan.md`, "Versioning rules". A change raises the number of the contract it breaks and no other; a new file format version must keep reading the old ones, with a fixture.
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
  second (see `canopy_core.h`). A query of either kind reports a status and writes its answer (ABI 2): after a failure a point's float is 0.0 and a span is zero-filled; in tests, `host_inlet_at`, `host_read_at` and `inlet_value` give just the answer. The engine's lock (`CanopyLock`, an SRW lock) is taken exclusively by installing, making and freeing instances and
  collecting, and shared by the host calls that only use the lists (knob and boundary writes, actions, counts), except the buttons of a node with
  `CANOPY_FLAG_SERVICE` (the realtime preview), which take it exclusively because they make and free the node's own instance; an instance applies
  the packages prepared for it at the start of a query by swapping pointers, and the editing thread frees what it has finished with
  (`canopy_instance_reap`). The preview's audio callback follows the query rules too (no allocation, no lock: tests count allocations while it plays
  and hold the engine's locks).
- What an install does while a query runs (read in `canopy_install.c`, relied on by the stress's oracle): the new knob positions are written BEFORE the graph is
  published, so an instance that has not adopted yet reads the new knobs with the old wiring; a node with only a point handler (`test.sum`) is asked for each sample
  of a span in turn and reads its sources each time, so a boundary value written meanwhile can change between two samples of one span, while a node with a span
  handler reads a source once; a file node's span is one file whatever is opened meanwhile. Design section 5 promises no consistent snapshot, and none is given.
- Audio in tests: they choose the null backend (`canopy_engine_set_audio_backend(engine, CANOPY_AUDIO_NULL)`) and never open the machine's real
  device (a bug or a mutation that sent them there would play their signals on it). miniaudio's own allocations are counted but not failed by the
  tests' failure hook (it leaks when they fail inside `ma_device_init`: see the plan's step 7 decisions). Allocation hooks: `canopy_alloc_fail_after(n)`
  fails everything after n, `canopy_alloc_fail_once(n)` fails exactly one.
- Tests of threads must not depend on the scheduler: pace the writer by the readers' progress (see `wait_for_progress` in `test_swap.c`), never by
  hoping that the readers got time. A test that holds the lock itself is deterministic for the correct code (it waits for the calls that must go
  through and then 100 ms for the ones that must not).
- The shell tool mangles backslashes in heredocs: edit files with the Edit/Write tools or run a script file, not an inline `python - <<EOF`.
- Line endings: CRLF for all source and text files (Windows); the Write tool makes LF files, so convert new ones (a script that rewrites `\r\n`).
- Batch files: CRLF (labels and `goto` fail with LF), and `%errorlevel%` inside a parenthesised block is the value from before the block (found at step 14: use a label and `goto` instead).
- No git for now.
