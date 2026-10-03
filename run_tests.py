"""Builds the DLL, then runs every C test and every Python test, and prints one total.

    python run_tests.py                 build + all tests
    python run_tests.py skeleton        only the Python test files tests/python/test_<area>.py named (the C tests always run)
    python run_tests.py -k build        only Python tests whose name contains the text
    python run_tests.py --no-build      skip the build step
    python run_tests.py --no-debug      skip the second run of the C tests against the debug runtime
    python run_tests.py --no-asan       skip the third run of the C tests under AddressSanitizer

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
import os
import re
import subprocess
import sys
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


def run_c_tests(with_debug, with_asan):
    out, passed, failed, _, _ = run_c_program("run_c_tests.exe")
    sys.stdout.write(out)
    if with_debug:
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
    if with_asan:
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


def python_tests(areas, contains):
    wanted = areas or sorted(os.path.basename(p)[5:-3] for p in glob.glob(os.path.join(ROOT, "tests", "python", "test_*.py")))
    tests = {}
    for area in wanted:
        module = importlib.import_module(f"test_{area}")
        for name, fn in vars(module).items():
            if name.startswith("test_") and callable(fn) and getattr(fn, "__module__", None) == module.__name__:
                if name in tests:
                    raise SystemExit(f"test {name} is defined twice")
                tests[name] = fn
    return [(n, f) for n, f in sorted(tests.items()) if not contains or any(c in n for c in contains)]


def main(argv):
    if "--no-build" not in argv:
        build()
    areas = [a for i, a in enumerate(argv) if not a.startswith("-") and (i == 0 or argv[i - 1] != "-k")]
    contains = [argv[i + 1] for i, a in enumerate(argv) if a == "-k" and i + 1 < len(argv)]
    passed, failed = run_c_tests("--no-debug" not in argv, "--no-asan" not in argv)
    for name, fn in python_tests(areas, contains):
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception:                            # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc(limit=3, file=sys.stdout)
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
