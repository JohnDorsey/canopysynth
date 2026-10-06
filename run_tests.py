"""Builds the DLL, then runs every C test and every Python test, and prints one total.

    python run_tests.py                 build + all tests
    python run_tests.py skeleton        only the Python test files tests/python/test_<area>.py named (the C tests always run)
    python run_tests.py -k build        only Python tests whose name contains the text
    python run_tests.py --no-build      skip the build step
    python run_tests.py --no-debug      skip the second run of the C tests against the debug runtime
    python run_tests.py --no-asan       skip the third run of the C tests under AddressSanitizer
    python run_tests.py --no-c          skip the C tests altogether (for a run after a change to a Python file, which cannot change what they say)
    python run_tests.py --fail-fast     stop at the first failure: the C programs after a failing one are not run, and nor are the Python tests after one
                                        that fails (the total line then counts only what ran, and a line below it says so)
    python run_tests.py --record-times FILE      write how long each Python test that ran took, as JSON (test name: seconds), to FILE
    python run_tests.py --order-by-times FILE    run the Python tests cheapest first by the times in FILE (written by --record-times); a test that
                                                 FILE has no time for runs before all the others, and equal times keep the order of the names
The last three are for the mutation check (dev/mutation/mutate.py), which needs a verdict on each fault as soon as one test fails; none of them
changes what a test says, only which tests run, and in which order, after a failure.

A Python test is a plain function test_* (no arguments, raises AssertionError) in tests/python/test_<area>.py; it is found by name and run
in name order. C tests are in tests/c (see ctest.h); their output lines are "  PASS  name" / "  FAIL  name" and a final "N passed, M failed".
The C tests run up to three times: normally; as run_c_tests_debug.exe (MSVC debug runtime: the whole heap is validated at every heap
operation, so a write past the end of any block is caught, and leaked blocks are reported); and, if the "C++ AddressSanitizer" component of
Visual Studio is installed, as run_c_tests_asan.exe (out-of-bounds reads and writes, use after free). The extra runs are not added to the
total (same tests); any failure, leak or sanitizer report in them is counted as a failure.
A C test program that has not finished after CANOPY_TEST_TIMEOUT seconds (default 180) is stopped and the run ends with a message: a test that
waits for a lock forever must not hang the suite (or a mutation check).
Test names are unique across C and Python (C names start with test_c_, Python names with test_py_). Exit code 1 if anything failed."""
import glob
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "python"))


def build():
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "build.ps1")]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout + result.stderr)
        raise SystemExit("the build failed")


C_PROGRAM_SECONDS = int(os.environ.get("CANOPY_TEST_TIMEOUT", "180"))     # a whole C test program takes a few seconds; one that runs this long is stuck
PYTHON_TEST_SECONDS = max(30, C_PROGRAM_SECONDS // 2)                      # one Python test; the slowest takes a few seconds


def give_up(name):
    """Called by the timer of a Python test that does not finish: a test stuck in a wait must not hang the suite (or a mutation check)."""
    print(f"  FAIL  {name}", flush=True)
    print(f"    did not finish within {PYTHON_TEST_SECONDS} s and the run was stopped: the test is stuck", flush=True)
    os._exit(1)


def run_c_program(name, extra_env=None):
    """Runs a C test program; returns (stdout, passed, failed, leaked, stderr). Exits if it does not finish."""
    env = dict(os.environ, **(extra_env or {}))
    try:
        result = subprocess.run([os.path.join(ROOT, "build", name)], capture_output=True, text=True, env=env, timeout=C_PROGRAM_SECONDS)
    except subprocess.TimeoutExpired as stuck:
        partial = stuck.stdout.decode(errors="replace") if isinstance(stuck.stdout, bytes) else (stuck.stdout or "")
        print("\n".join(partial.splitlines()[-5:]))
        raise SystemExit(f"{name} did not finish within {C_PROGRAM_SECONDS} s and was stopped: a test is stuck (a deadlock, say); it is the test after "
                         "the last one printed above")
    match = re.search(r"(\d+) passed, (\d+) failed", result.stdout)
    if not match:
        print(result.stdout + result.stderr)
        raise SystemExit(f"{name} did not finish (it crashed, or a sanitizer or the debug runtime stopped it: see the report above)")
    return result.stdout, int(match.group(1)), int(match.group(2)), "memory leaks detected" in result.stdout, result.stderr


def run_c_tests(with_debug, with_asan, fail_fast=False):
    """Runs the C test programs in turn (the normal one, then the debug-heap one and the AddressSanitizer one if asked for); returns (passed,
    failed) as the normal run counted them and the extra runs added their failures. With `fail_fast`, a program is not run after one that failed."""
    out, passed, failed, _, _ = run_c_program("run_c_tests.exe")
    sys.stdout.write(out)
    if with_debug and not (fail_fast and failed):
        if not os.path.exists(os.path.join(ROOT, "build", "run_c_tests_debug.exe")):
            print("\n(the debug-heap test program is not built: run without --no-build)")
        else:
            out, debug_passed, debug_failed, leaked, _ = run_c_program("run_c_tests_debug.exe")
            for line in out.splitlines():           # only what went wrong: the passing lines are the same as above
                if (line.startswith("  FAIL") or line.startswith("    ") or line.startswith("CRASH") or "HEAP CORRUPTION" in line
                        or "memory leaks detected" in line or line.startswith("Detected memory leaks")):
                    print("  [debug heap] " + line.strip())
            print(f"\ndebug-heap run of the same C tests: {debug_passed} passed, {debug_failed} failed" + (", MEMORY LEAKS" if leaked else ""))
            failed += debug_failed + (1 if leaked else 0)
    if with_asan and not (fail_fast and failed):
        if not os.path.exists(os.path.join(ROOT, "build", "run_c_tests_asan.exe")):
            print("\n(no AddressSanitizer run: the component is not installed, or run without --no-build)")
        else:
            # the test that asks for an impossible allocation must get NULL, not a sanitizer abort
            out, asan_passed, asan_failed, _, err = run_c_program("run_c_tests_asan.exe", {"ASAN_OPTIONS": "allocator_may_return_null=1"})
            for line in out.splitlines():
                if line.startswith("  FAIL") or line.startswith("    ") or line.startswith("CRASH"):
                    print("  [asan] " + line.strip())
            reports = [line for line in err.splitlines() if "ERROR: AddressSanitizer" in line]
            for line in reports:
                print("  [asan] " + line.strip())
            print(f"\nAddressSanitizer run of the same C tests: {asan_passed} passed, {asan_failed} failed" + (", SANITIZER ERRORS" if reports else ""))
            failed += asan_failed + (1 if reports else 0)
    return passed, failed


def python_tests(areas, contains, times=None):
    """The Python tests to run, as (name, function): those of the test files named in `areas` (all of them if none), whose names contain one of the texts
    in `contains` (all if none); in name order, or, given `times` (test name -> seconds), cheapest first: a test with no time before all the others,
    and equal times in name order."""
    wanted = areas or sorted(os.path.basename(p)[5:-3] for p in glob.glob(os.path.join(ROOT, "tests", "python", "test_*.py")))
    tests = {}
    for area in wanted:
        module = importlib.import_module(f"test_{area}")
        for name, fn in vars(module).items():
            if name.startswith("test_") and callable(fn) and getattr(fn, "__module__", None) == module.__name__:
                if name in tests:
                    raise SystemExit(f"test {name} is defined twice")
                tests[name] = fn
    chosen = [(n, f) for n, f in sorted(tests.items()) if not contains or any(c in n for c in contains)]
    if times is not None:
        chosen.sort(key=lambda item: times.get(item[0], -1.0))          # (a stable sort: tests with equal times stay in name order)
    return chosen


def read_times(path):
    """The table of seconds per test name that --record-times wrote; the run ends, before any test, if the file cannot be used (a run that ordered
    its tests by something else without saying so is the one thing a verdict must not rest on)."""
    try:
        with open(path, encoding="utf-8") as handle:
            times = json.load(handle)
        if not isinstance(times, dict) or not all(isinstance(seconds, (int, float)) for seconds in times.values()):
            raise ValueError("it is not a table of seconds by test name")
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot use the times file {path}: {error}")
    return times


def write_times(path, times):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(times, handle, indent=1, sort_keys=True)
    os.replace(temporary, path)


def parse(argv):
    """(areas, contains, options) of the command line: the test files named, the texts after -k, and every option (a flag is True; an option that
    takes a file name has it)."""
    areas, contains, options, index = [], [], {}, 0
    while index < len(argv):
        argument = argv[index]
        if argument == "-k" and index + 1 < len(argv):
            contains.append(argv[index + 1])
            index += 2
        elif argument in ("--record-times", "--order-by-times"):
            if index + 1 >= len(argv):
                raise SystemExit(f"{argument} needs the name of a file")
            options[argument] = argv[index + 1]
            index += 2
        elif argument.startswith("-"):
            options[argument] = True
            index += 1
        else:
            areas.append(argument)
            index += 1
    return areas, contains, options


def main(argv):
    areas, contains, options = parse(argv)
    fail_fast = "--fail-fast" in options
    times = read_times(options["--order-by-times"]) if "--order-by-times" in options else None
    if "--no-build" not in options:
        build()
    passed, failed = (0, 0) if "--no-c" in options else run_c_tests("--no-debug" not in options, "--no-asan" not in options, fail_fast)
    stopped = fail_fast and failed > 0
    measured = {}
    for name, fn in [] if stopped else python_tests(areas, contains, times):
        timer = threading.Timer(PYTHON_TEST_SECONDS, give_up, args=(name,))
        timer.daemon = True
        timer.start()
        started = time.perf_counter()
        try:
            fn()
            timer.cancel()
            passed += 1
            print(f"  PASS  {name}")
        except Exception:                            # noqa: BLE001
            timer.cancel()
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc(limit=3, file=sys.stdout)
        measured[name] = time.perf_counter() - started
        if fail_fast and failed:
            stopped = True
            break
    if "--record-times" in options:
        write_times(options["--record-times"], measured)
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if stopped:
        print("(stopped at the first failure: --fail-fast; what was not run yet did not run)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
