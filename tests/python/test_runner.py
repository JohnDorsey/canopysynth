"""Tests: the test runner (`run_tests.py`) and the mutation runner (`dev/mutation/mutate.py`) themselves, which every claim of the project rests on. The test runner's
options for mutation campaigns (--fail-fast, --no-c, --record-times, --order-by-times) are tried on a copy of it in a throwaway project that has six tiny tests of its
own, so that nothing here depends on the real suite; its C phases and the mutation runner's way of asking for a run and of reading the result are tried with the
programs and `subprocess.run` replaced by stubs. What all of it must keep true: a fast run never reports a failure that is not there and never hides one that is."""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALL_SIX = ["test_py_a_fast_pass", "test_py_b_slow_pass", "test_py_c_fails", "test_py_d_pass", "test_py_e_fails_too", "test_py_f_pass"]

FAKE_TESTS = '''import time


def test_py_a_fast_pass():
    pass


def test_py_b_slow_pass():
    time.sleep(0.3)


def test_py_c_fails():
    assert False, "c fails"


def test_py_d_pass():
    pass


def test_py_e_fails_too():
    raise AssertionError("e fails")


def test_py_f_pass():
    pass
'''


@contextlib.contextmanager
def fake_project():
    """A folder holding a copy of run_tests.py and tests/python/test_fake.py (the six tests above): yields its path."""
    folder = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(ROOT, "run_tests.py"), os.path.join(folder, "run_tests.py"))
        os.makedirs(os.path.join(folder, "tests", "python"))
        with open(os.path.join(folder, "tests", "python", "test_fake.py"), "w") as handle:
            handle.write(FAKE_TESTS)
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run(folder, *arguments, c=False):
    """Runs the copy of the runner in the throwaway project (without the C tests, which that project does not have, unless `c`)."""
    command = [sys.executable, "run_tests.py", "--no-build"] + ([] if c else ["--no-c"]) + list(arguments)
    return subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=120)


def ran(result):
    """[(PASS or FAIL, test name)] in the order the tests ran, as the runner printed them."""
    return re.findall(r"^  (PASS|FAIL)  (test_\w+)", result.stdout, re.M)


def total(result):
    """(passed, failed, total) of the runner's last line, or None if it printed none: the line the mutation runner reads."""
    match = re.search(r"(\d+) passed, (\d+) failed, (\d+) total", result.stdout)
    return tuple(int(group) for group in match.groups()) if match else None


def load(path, name):
    """A fresh copy of a Python file as a module (the project folder has no package for these scripts)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(folder, name, data):
    path = os.path.join(folder, name)
    with open(path, "w") as handle:
        json.dump(data, handle)
    return path


# ---------------------------------------------------------------- the test runner

def test_py_the_runner_runs_every_python_test_in_name_order_and_a_failure_does_not_stop_the_rest():
    with fake_project() as folder:
        result = run(folder)
        assert ran(result) == [("PASS", ALL_SIX[0]), ("PASS", ALL_SIX[1]), ("FAIL", ALL_SIX[2]), ("PASS", ALL_SIX[3]), ("FAIL", ALL_SIX[4]), ("PASS", ALL_SIX[5])]
        assert total(result) == (4, 2, 6) and result.returncode == 1 and "stopped" not in result.stdout


def test_py_fail_fast_stops_after_the_first_failing_test_says_so_and_still_prints_the_total_line_the_mutation_runner_reads():
    with fake_project() as folder:
        result = run(folder, "--fail-fast")
        assert ran(result) == [("PASS", ALL_SIX[0]), ("PASS", ALL_SIX[1]), ("FAIL", ALL_SIX[2])]
        assert total(result) == (2, 1, 3) and result.returncode == 1
        assert "stopped at the first failure" in result.stdout
        assert ALL_SIX[3] not in result.stdout and ALL_SIX[4] not in result.stdout and ALL_SIX[5] not in result.stdout          # nothing after it ran
        result = run(folder, "--fail-fast", "-k", "fails")                                                                        # a filter that picks failing tests: the first one stops it
        assert ran(result) == [("FAIL", ALL_SIX[2])] and total(result) == (0, 1, 1)


def test_py_fail_fast_changes_nothing_for_a_run_with_no_failure_and_works_with_a_name_filter():
    with fake_project() as folder:
        everything = run(folder, "-k", "pass")
        fast = run(folder, "--fail-fast", "-k", "pass")
        passing = [ALL_SIX[0], ALL_SIX[1], ALL_SIX[3], ALL_SIX[5]]
        assert [name for _, name in ran(everything)] == passing == [name for _, name in ran(fast)]
        assert total(everything) == total(fast) == (4, 0, 4) and everything.returncode == fast.returncode == 0
        assert "stopped" not in fast.stdout
        either = run(folder, "-k", "fast", "-k", "d_pass")                                       # several texts: a test that has any of them
        assert [name for _, name in ran(either)] == [ALL_SIX[0], ALL_SIX[3]] and total(either) == (2, 0, 2)


def test_py_no_c_leaves_out_the_c_tests_and_without_it_the_runner_does_look_for_them():
    with fake_project() as folder:
        assert total(run(folder)) == (4, 2, 6)                                                    # (this project has no build folder: nothing was looked for)
        without = run(folder, c=True)                                                             # the C test program is not there: the run cannot finish
        assert total(without) is None and without.returncode != 0


def test_py_record_times_writes_how_long_each_test_that_ran_took():
    with fake_project() as folder:
        times = os.path.join(folder, "times.json")
        run(folder, "--record-times", times)
        recorded = json.load(open(times))
        assert sorted(recorded) == ALL_SIX and all(isinstance(seconds, float) and seconds >= 0 for seconds in recorded.values())
        assert recorded["test_py_b_slow_pass"] >= 0.25 and recorded["test_py_b_slow_pass"] == max(recorded.values())          # (it sleeps 0.3 s; the rest do nothing)
        run(folder, "--fail-fast", "--record-times", times)                                       # a run that stops early records the tests that ran, and only them
        assert sorted(json.load(open(times))) == ALL_SIX[:3]
        run(folder, "-k", "fast", "--record-times", times)
        assert sorted(json.load(open(times))) == [ALL_SIX[0]]


def test_py_order_by_times_runs_the_cheapest_first_by_name_among_equals_and_the_tests_it_has_no_time_for_before_all_of_them():
    with fake_project() as folder:
        given = {ALL_SIX[0]: 0.5, ALL_SIX[1]: 0.3, ALL_SIX[2]: 0.9, ALL_SIX[3]: 0.1, ALL_SIX[4]: 0.2, ALL_SIX[5]: 0.1}
        result = run(folder, "--order-by-times", write_json(folder, "times.json", given))
        assert [name for _, name in ran(result)] == [ALL_SIX[3], ALL_SIX[5], ALL_SIX[4], ALL_SIX[1], ALL_SIX[0], ALL_SIX[2]]         # d and f tie: by name
        assert total(result) == (4, 2, 6)                                                         # the same tests ran, in another order
        del given[ALL_SIX[5]]
        del given[ALL_SIX[3]]
        result = run(folder, "--order-by-times", write_json(folder, "times.json", given))
        assert [name for _, name in ran(result)] == [ALL_SIX[3], ALL_SIX[5], ALL_SIX[4], ALL_SIX[1], ALL_SIX[0], ALL_SIX[2]]         # d and f have no time: they come first, by name
        given[ALL_SIX[3]], given[ALL_SIX[5]] = 0.1, 0.1
        result = run(folder, "--fail-fast", "--order-by-times", write_json(folder, "times.json", given))      # the order is the order of the early stop too
        assert ran(result) == [("PASS", ALL_SIX[3]), ("PASS", ALL_SIX[5]), ("FAIL", ALL_SIX[4])] and total(result) == (2, 1, 3)
        result = run(folder, "-k", "pass", "--order-by-times", write_json(folder, "times.json", given))      # and with a filter, only the tests it picks
        assert [name for _, name in ran(result)] == [ALL_SIX[3], ALL_SIX[5], ALL_SIX[1], ALL_SIX[0]]


def test_py_a_times_file_that_is_missing_or_unreadable_stops_the_run_with_no_total_so_that_it_cannot_pass_for_a_detection():
    with fake_project() as folder:
        files = {"nowhere.json": None, "broken.json": "{not json", "a list.json": "[1, 2]", "words.json": '{"test_py_a_fast_pass": "slow"}'}
        for name, text in files.items():                                                          # missing; not JSON; JSON that is not a table; a table of something other than seconds
            path = os.path.join(folder, name)
            if text is not None:
                with open(path, "w") as handle:
                    handle.write(text)
            result = run(folder, "--order-by-times", path)
            assert total(result) is None and ran(result) == [] and result.returncode != 0
            assert result.stderr.startswith("cannot use the times file ") and path in result.stderr and "Traceback" not in result.stderr      # (a sentence, not a crash)


def test_py_an_option_that_needs_a_file_name_and_has_none_stops_the_run_with_a_sentence_and_a_k_with_no_text_picks_nothing():
    with fake_project() as folder:
        for option in ("--record-times", "--order-by-times"):
            result = run(folder, option)
            assert total(result) is None and ran(result) == [] and result.returncode != 0
            assert result.stderr.startswith(f"{option} needs the name of a file") and "Traceback" not in result.stderr
        assert total(run(folder, "-k")) == (4, 2, 6)                                              # (a -k with no text after it narrows nothing: every test runs)


def test_py_after_a_failure_in_the_c_programs_fail_fast_skips_the_ones_after_it_and_without_it_all_three_run():
    runner = load(os.path.join(ROOT, "run_tests.py"), "run_tests_under_test")
    for fail_fast, results, leaks, called, failed in (
            (False, {"run_c_tests.exe": 1}, (), 3, 1),                                           # the normal run fails: the heap and sanitizer runs still happen
            (True, {"run_c_tests.exe": 1}, (), 1, 1),                                            # ...unless a run is to stop at the first failure
            (True, {"run_c_tests_debug.exe": 2}, (), 2, 2),                                      # the debug-heap run fails: the sanitizer run is skipped
            (True, {}, ("run_c_tests_debug.exe",), 2, 1),                                        # so does a leak the debug-heap run reports (it counts as a failure)
            (True, {"run_c_tests_asan.exe": 1}, (), 3, 1),                                       # the last one fails: all three ran
            (True, {}, (), 3, 0),                                                                # nothing fails: nothing is skipped
            (False, {"run_c_tests_debug.exe": 1, "run_c_tests_asan.exe": 1}, (), 3, 2)):
        calls = []

        def program(name, extra_env=None):
            calls.append(name)
            return "  FAIL  test_c_stub\n" * bool(results.get(name)), 9, results.get(name, 0), name in leaks, ""
        with mock.patch.object(runner, "run_c_program", program), mock.patch.object(runner.os.path, "exists", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):                                       # (the stub's FAIL lines must not reach the real run's output)
            passed, found = runner.run_c_tests(True, True, fail_fast)
        assert (len(calls), found) == (called, failed), (fail_fast, results, leaks, calls)
        assert calls == ["run_c_tests.exe", "run_c_tests_debug.exe", "run_c_tests_asan.exe"][:called]


def test_py_a_failing_c_run_with_fail_fast_starts_no_python_test_and_says_so_and_without_it_the_python_tests_follow():
    runner = load(os.path.join(ROOT, "run_tests.py"), "run_tests_under_test")
    started, asked = [], []
    tests = [("test_py_one", lambda: started.append("one")), ("test_py_two", lambda: started.append("two"))]
    for fail_fast, c_failures, expected, code, note in ((True, 1, [], 1, True), (False, 1, ["one", "two"], 1, False), (True, 0, ["one", "two"], 0, False)):
        started.clear()
        asked.clear()
        output = io.StringIO()
        arguments = ["--no-build"] + (["--no-debug"] if fail_fast else []) + ["--no-asan"] + (["--fail-fast"] if fail_fast else [])

        def c_tests(debug, asan, fast, c_failures=c_failures):
            asked.append((debug, asan, fast))                                                    # (what the run asked the C phases to do)
            return 5, c_failures
        with mock.patch.object(runner, "run_c_tests", c_tests), mock.patch.object(runner, "python_tests", lambda areas, contains, times=None: tests), \
                contextlib.redirect_stdout(output):
            result = runner.main(arguments)
        assert (started, result) == (expected, code), (fail_fast, c_failures, started)
        assert asked == [(not fail_fast, False, fail_fast)]                                      # --no-debug and --no-asan reach the C phases, and so does --fail-fast
        assert ("stopped at the first failure" in output.getvalue()) == note
        assert f"{5 + len(expected)} passed, {c_failures} failed, {5 + len(expected) + c_failures} total" in output.getvalue()


# ---------------------------------------------------------------- the mutation runner

def test_py_the_mutation_runner_rebuilds_with_the_build_script_and_stops_if_that_fails():
    mutate = load(os.path.join(ROOT, "dev", "mutation", "mutate.py"), "mutate_under_test")
    asked = []

    def stub(returncode):
        def run(command, **options):
            asked.append((command, options.get("cwd")))
            return types.SimpleNamespace(returncode=returncode, stdout="out text", stderr="error text")
        return run
    with mock.patch.object(mutate.subprocess, "run", stub(0)):
        mutate.rebuild()
    assert asked == [(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "build.ps1")], ROOT)]
    with mock.patch.object(mutate.subprocess, "run", stub(1)):
        try:
            mutate.rebuild()
        except SystemExit as stop:
            assert "mutated DLL" in str(stop) and "out text" in str(stop) and "error text" in str(stop)
        else:
            raise AssertionError("a build that fails must stop the campaign")


def test_py_the_mutation_runner_asks_for_the_fast_run_only_with_a_times_file_and_otherwise_asks_as_it_always_did():
    mutate = load(os.path.join(ROOT, "dev", "mutation", "mutate.py"), "mutate_under_test")
    asked = []

    def stub(command, **options):
        asked.append(command)
        return types.SimpleNamespace(stdout="  PASS  test_py_x\n\n1 passed, 0 failed, 1 total\n", stderr="")
    python = sys.executable
    with mock.patch.object(mutate.subprocess, "run", stub):
        mutate.run_suite()                                                                       # the whole suite, nothing skipped or reordered
        mutate.run_suite(python_only=True, areas=["editor", "editor_link"])                      # a Python file was broken: no build, the C tests once, the two extra C runs skipped
        mutate.run_suite(record="R.json")                                                        # the first, whole run of a campaign also notes how long each test takes
        mutate.run_suite(python_only=True, areas=["editor"], times="T.json")                     # fast, for a broken Python file: no build, no C tests, cheapest first, stop at a failure
        mutate.run_suite(python_only=True, times="T.json")                                       # (every Python test)
        mutate.run_suite(times="T.json")                                                         # fast, for a broken C file: the build and the C programs in turn, then the Python tests
    assert asked == [
        [python, "run_tests.py"],
        [python, "run_tests.py", "editor", "editor_link", "--no-build", "--no-debug", "--no-asan"],
        [python, "run_tests.py", "--record-times", "R.json"],
        [python, "run_tests.py", "editor", "--no-build", "--no-c", "--fail-fast", "--order-by-times", "T.json"],
        [python, "run_tests.py", "--no-build", "--no-c", "--fail-fast", "--order-by-times", "T.json"],
        [python, "run_tests.py", "--fail-fast", "--order-by-times", "T.json"]]


SPEC = '''AREAS = ["editor", "editor_link"]
MUTATIONS = [
    ("C1 first, a C file", "src/engine.c", "int x = 1;", "int x = 99;"),
    ("P1 second, a Python file", "pkg/one.py", "A = 1", "A = 99"),
    ("P2 third, another", "pkg/two.py", "C = 3", "C = 99"),
    ("S1 not there", "pkg/two.py", "NOT THERE", "x"),
    ("C2 fourth, a C file again", "src/engine.c", "int y = 2;", "int y = 99;"),
    ("P3 fifth, a Python file again", "pkg/one.py", "B = 2", "B = 99"),
    ("T1 sixth, the test runner itself", "run_tests.py", "X = 1", "X = 99"),
]
'''
SOURCES = {"src/engine.c": b"int x = 1;\r\nint y = 2;\r\n", "pkg/one.py": b"A = 1\r\nB = 2\r\n", "pkg/two.py": b"C = 3\r\n", "run_tests.py": b"X = 1\r\n"}
GREEN = ("SURVIVED", [], "  PASS  test_py_x\n\n1 passed, 0 failed, 1 total\n")


def mutation_campaign(arguments, final_fails=False):
    """Runs the mutation runner's main on SPEC over SOURCES in a throwaway folder, with every run of the suite and every rebuild replaced by a stub that notes
    what was asked and which files were changed at that moment (and, if `final_fails`, answers the run after the files are restored with a failure); returns
    (the notes, the exit code, what was printed, the folder's files as bytes, the path of the times file the first run was asked to write, and whether it was
    gone afterwards)."""
    mutate = load(os.path.join(ROOT, "dev", "mutation", "mutate.py"), "mutate_under_test")
    folder = tempfile.mkdtemp()
    try:
        for relative, data in SOURCES.items():
            os.makedirs(os.path.dirname(os.path.join(folder, relative)), exist_ok=True)
            with open(os.path.join(folder, relative), "wb") as handle:
                handle.write(data)
        spec = os.path.join(folder, "spec.py")
        with open(spec, "w") as handle:
            handle.write(SPEC)
        notes, times_paths = [], []
        verdicts = {b"x = 99": ("caught", ["test_c_a"]), b"A = 99": ("SURVIVED", []), b"C = 99": ("caught", ["test_py_b"]),
                    b"y = 99": ("BUILD FAILED", []), b"B = 99": ("caught", ["test_py_c"]), b"X = 99": ("caught", ["test_py_d"])}
        mutated_once = []

        def changed():
            return sorted(relative for relative, data in SOURCES.items() if open(os.path.join(folder, relative), "rb").read() != data)

        def stub_run_suite(python_only=False, areas=None, times=None, record=None):
            now = changed()
            notes.append(("run", python_only, areas, times is not None, record is not None, now))
            for path in (times, record):
                if path is not None:
                    assert os.path.exists(path), "the times file must exist while the campaign runs"
                    times_paths.append(path)
            if not now:
                if final_fails and mutated_once:                                                  # (the run after the files are put back)
                    return "caught", ["test_py_left_broken"], "1 failed"
                return GREEN[0], GREEN[1], GREEN[2]
            mutated_once.append(now)
            text = b"".join(open(os.path.join(folder, relative), "rb").read() for relative in now)
            state, names = next(v for marker, v in verdicts.items() if marker in text)
            return state, names, f"{len(names)} failed"

        def stub_rebuild():
            notes.append(("rebuild", changed()))

        output = io.StringIO()
        with mock.patch.object(mutate, "ROOT", folder), mock.patch.object(mutate, "run_suite", stub_run_suite), \
                mock.patch.object(mutate, "rebuild", stub_rebuild), contextlib.redirect_stdout(output):
            code = mutate.main([spec] + arguments)
        after = {relative: open(os.path.join(folder, relative), "rb").read() for relative in SOURCES}
        leftovers = [name for _, _, names in os.walk(folder) for name in names if name.endswith(".mutation_backup")]
        gone = not any(os.path.exists(path) for path in times_paths)
        return notes, code, output.getvalue(), after, times_paths, gone and not leftovers
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_py_the_mutation_runner_checks_the_fast_order_before_mutating_rebuilds_before_a_python_mutation_that_follows_a_c_one_and_puts_every_file_back():
    notes, code, printed, after, times_paths, clean = mutation_campaign([])
    areas = ["editor", "editor_link"]
    assert notes == [
        ("run", False, None, False, True, []),                                       # the whole suite once, as it always was, also writing how long each Python test takes
        ("run", True, None, True, False, []),                                        # the fast order, for the Python tests that follow a C file's mutation: it must pass
        ("run", True, areas, True, False, []),                                       # ...and for the ones that follow a Python file's: AREAS
        ("run", False, None, True, False, ["src/engine.c"]),                         # C1: a fast run, the C file mutated
        ("rebuild", []),                                                             # the DLL was built from it: built again from the restored source
        ("run", True, areas, True, False, ["pkg/one.py"]),                           # P1
        ("run", True, areas, True, False, ["pkg/two.py"]),                           # P2: no rebuild needed now
        ("run", False, None, True, False, ["src/engine.c"]),                         # C2 (S1, which matches nothing, was skipped without a run)
        ("rebuild", []),
        ("run", True, areas, True, False, ["pkg/one.py"]),                           # P3
        ("run", True, areas, False, False, ["run_tests.py"]),                        # T1: the runner itself is mutated, so this run is the old, thorough one (no fast flags: they are what T1 breaks)
        ("run", False, None, False, False, [])]                                      # the whole suite again once everything is restored, in the old way
    assert len(set(times_paths)) == 1 and clean                                       # one times file, written by the first run and read by the others, and removed
    assert after == SOURCES                                                           # every file is back byte for byte (the CRLF endings too)
    assert code == 1 and "P1 second, a Python file: SURVIVED" in printed and "C2 fourth, a C file again: BUILD FAILED" in printed
    assert "S1 not there: SKIPPED" in printed and "summary: 4 caught, 1 SURVIVED, 1 BUILD FAILED, 1 SKIPPED" in printed


def test_py_with_thorough_the_mutation_runner_asks_for_every_run_the_old_way_and_a_name_list_picks_the_mutations_to_run():
    notes, code, printed, after, times_paths, clean = mutation_campaign(["--thorough", "C1", "P2"])
    areas = ["editor", "editor_link"]
    assert notes == [
        ("run", False, None, False, False, []),                                      # no times file: nothing is recorded, and no fast order to check
        ("run", False, None, False, False, ["src/engine.c"]),
        ("rebuild", []),                                                             # (the Python tests must not meet a mutated DLL in this mode either)
        ("run", True, areas, False, False, ["pkg/two.py"]),
        ("run", False, None, False, False, [])]
    assert times_paths == [] and clean and after == SOURCES and code == 0 and "thorough" in printed
    assert "P1" not in printed and "P3" not in printed and "C2" not in printed
    notes, code, printed, after, times_paths, clean = mutation_campaign(["--thorough"])        # with no names, every mutation runs (--thorough is not taken for a name)
    assert notes == [
        ("run", False, None, False, False, []),
        ("run", False, None, False, False, ["src/engine.c"]),
        ("rebuild", []),
        ("run", True, areas, False, False, ["pkg/one.py"]),
        ("run", True, areas, False, False, ["pkg/two.py"]),
        ("run", False, None, False, False, ["src/engine.c"]),
        ("rebuild", []),
        ("run", True, areas, False, False, ["pkg/one.py"]),
        ("run", True, areas, False, False, ["run_tests.py"]),
        ("run", False, None, False, False, [])]
    assert times_paths == [] and clean and after == SOURCES


def test_py_the_mutation_runner_exits_with_0_only_when_every_mutation_was_caught():
    for names, final_fails, code in ((["C1", "P2"], False, 0),                           # both caught, and the suite is green again after the files are put back: success
                                     (["C1", "P2"], True, 1),                            # ...but if the suite is not green after that, it is not
                                     (["C1", "P1"], False, 1),                           # P1 survives
                                     (["C1", "C2"], False, 1),                           # C2 does not build: it proved nothing
                                     (["C1", "S1"], False, 1),                           # S1's text is not in the file (the code moved): it did not run
                                     (["P2", "P3", "T1"], False, 0)):
        notes, found, printed, after, times_paths, clean = mutation_campaign(names, final_fails)
        assert found == code, (names, final_fails, found, printed)
        assert after == SOURCES and clean


def test_py_the_mutation_runner_refuses_to_mutate_when_the_suite_or_the_fast_order_is_not_green_and_still_puts_every_file_back():
    mutate = load(os.path.join(ROOT, "dev", "mutation", "mutate.py"), "mutate_under_test")
    folder = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(folder, "pkg"))
        with open(os.path.join(folder, "pkg", "one.py"), "wb") as handle:
            handle.write(b"A = 1\r\n")
        spec = os.path.join(folder, "spec.py")
        with open(spec, "w") as handle:
            handle.write('MUTATIONS = [("P1 one", "pkg/one.py", "A = 1", "A = 99")]\n')
        for green_runs in (0, 1):                                                    # the whole suite fails; the fast order fails (the whole suite passed)
            runs = []

            def stub_run_suite(python_only=False, areas=None, times=None, record=None):
                runs.append(python_only)
                return ("SURVIVED", [], "1 passed, 0 failed, 1 total") if len(runs) <= green_runs else ("caught", ["test_py_x"], "1 failed")
            with mock.patch.object(mutate, "ROOT", folder), mock.patch.object(mutate, "run_suite", stub_run_suite), contextlib.redirect_stdout(io.StringIO()):
                try:
                    mutate.main([spec])
                except SystemExit as stop:
                    assert "must be green" in str(stop) and ("fast order" in str(stop)) == (green_runs == 1)
                else:
                    raise AssertionError("the runner must stop")
            assert len(runs) == green_runs + 1                                       # nothing was mutated or run after that
            assert open(os.path.join(folder, "pkg", "one.py"), "rb").read() == b"A = 1\r\n" and not os.path.exists(os.path.join(folder, "pkg", "one.py.mutation_backup"))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_py_the_mutation_runner_puts_the_file_back_and_removes_its_backup_and_its_times_file_when_a_run_fails_in_the_middle_of_a_campaign():
    mutate = load(os.path.join(ROOT, "dev", "mutation", "mutate.py"), "mutate_under_test")
    folder = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(folder, "pkg"))
        target = os.path.join(folder, "pkg", "one.py")
        with open(target, "wb") as handle:
            handle.write(b"A = 1\r\nB = 2\r\n")
        spec = os.path.join(folder, "spec.py")
        with open(spec, "w") as handle:
            handle.write('MUTATIONS = [("P1 one", "pkg/one.py", "A = 1", "A = 99"), ("P2 two", "pkg/one.py", "B = 2", "B = 99")]\n')
        runs, paths = [], []

        def stub_run_suite(python_only=False, areas=None, times=None, record=None):
            runs.append(open(target, "rb").read())
            paths.append(times or record)
            if len(runs) == 3:                                                           # the third run is the first mutation's
                raise RuntimeError("the machine went to sleep")
            return GREEN
        with mock.patch.object(mutate, "ROOT", folder), mock.patch.object(mutate, "run_suite", stub_run_suite), contextlib.redirect_stdout(io.StringIO()):
            try:
                mutate.main([spec])
            except RuntimeError as error:
                assert "went to sleep" in str(error)
            else:
                raise AssertionError("the error must go on")
        assert runs[2] == b"A = 99\r\nB = 2\r\n"                                         # (it was the mutated file that run saw)
        assert open(target, "rb").read() == b"A = 1\r\nB = 2\r\n" and not os.path.exists(target + ".mutation_backup")
        assert len(runs) == 3 and not os.path.exists(paths[0])
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_py_the_mutation_runner_reads_a_failing_test_a_stuck_test_a_crash_a_build_failure_and_a_green_run_the_same_in_every_mode():
    mutate = load(os.path.join(ROOT, "dev", "mutation", "mutate.py"), "mutate_under_test")
    outputs = {                                                                                   # what the run printed -> the verdict and the failing tests it names
        "one failure among passes": ("  PASS  test_py_a\n  FAIL  test_py_b\n    Traceback\n  PASS  test_py_c\n\n2 passed, 1 failed, 3 total\n", "caught", ["test_py_b"]),
        "a run stopped at its first failure": ("  PASS  test_py_a\n  FAIL  test_py_b\n    Traceback\n\n1 passed, 1 failed, 2 total\n(stopped at the first failure: --fail-fast)\n",
                                               "caught", ["test_py_b"]),
        "a failure in the debug heap run": ("  PASS  test_c_a\n  [debug heap] FAIL  test_c_b\n\n1 passed, 1 failed, 2 total\n", "caught", ["test_c_b"]),
        "a green run": ("  PASS  test_py_a\n\n1 passed, 0 failed, 1 total\n", "SURVIVED", []),
        "a test that never finished": ("  FAIL  test_py_stuck\n    did not finish within 90 s and the run was stopped: the test is stuck\n", "caught", ["test_py_stuck"]),
        "a C test program that did not finish": ("run_c_tests.exe did not finish (it crashed)", "caught", ["(the C test program crashed)"]),
        "a run that crashed": ("Traceback (most recent call last):\nImportError: nothing", "caught", ["(the test run crashed)"]),
        "a build that failed": ("the build failed", "BUILD FAILED", []),
    }
    for fast in (None, "T.json"):
        for what, (output, state, names) in outputs.items():
            stub = lambda command, output=output, **options: types.SimpleNamespace(stdout=output, stderr="")
            with mock.patch.object(mutate.subprocess, "run", stub):
                found = mutate.run_suite(python_only=True, areas=["editor"], times=fast)
            assert found[:2] == (state, names), (fast, what, found[:2])
