"""Mutation check: breaks the library in small, specific ways, one at a time, runs the test suite after each, and reports whether the
tests noticed. A test suite that stays green with a deliberate fault in the code it covers is not testing that code.

    python dev/mutation/mutate.py dev/mutation/step3.py            every mutation of the spec
    python dev/mutation/mutate.py dev/mutation/step3.py I05 E13    only the mutations whose name starts with one of these words
    python dev/mutation/mutate.py dev/mutation/step3.py --thorough the slow way: every test of every run, whatever fails (see below)

A spec file defines MUTATIONS = [(name, file, old, new), ...]: `file` is relative to the project folder, `old` must occur exactly once in it
(written with \\n newlines; the file's CRLF is handled), `new` replaces it. Results:
    caught        some test failed (or the C test program crashed: a crash is a detection too)
    SURVIVED      the whole suite stayed green: either a weak test or an equivalent mutation; look at each one
    BUILD FAILED  the mutation does not compile (say, an unused variable under /WX): it proves nothing, rewrite it
The exit code is 0 only if every mutation was caught and the suite is green again after the files are restored: a survivor, a build failure and a mutation
that was SKIPPED (its `old` text is not in the file any more, because the code moved: the spec needs a new anchor) all make it 1.
A spec may also define AREAS = ["editor", ...]: the test files to run after a mutation of a .py file (see run_suite).
Every file touched is restored afterwards, also if this script is interrupted (a backup file sits next to it meanwhile). If a run was killed
hard and left a *.mutation_backup file, this script refuses to start: copy the backup over the source file (it is the original) and delete it.

Speed. A verdict needs only the first test that fails, so unless --thorough is given each mutation's run is a fast one (`run_tests.py --fail-fast
--order-by-times`): it stops at the first failing test, runs the Python tests cheapest first (by the times the first, whole run of the campaign
records in a private file), and, after a mutation of a Python file, leaves out the C tests, which that cannot change. None of this can turn a
survivor into a detection: a run that finds nothing wrong still runs every test, and the fast order is itself run once before the first mutation and
must pass. A mutation of run_tests.py itself is always run the thorough way (the campaign would otherwise be judged by the runner it has just broken:
a run that stops after the first passing test looks green). After a mutation of a C file the DLL and the test programs are built again, from the
restored sources, before the next mutation of a Python file (the Python tests run against the DLL as it was last built)."""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_suite(python_only=False, areas=None, times=None, record=None):
    """The suite, as one run of run_tests.py: (verdict, the names of the failing tests, the output). For a mutation in a .py file the C code is
    unchanged, so `python_only` skips the build and the two extra C runs (the C tests still run once, and every Python test runs unless `areas`
    names the test files, as `run_tests.py` takes them: a spec of mutations that only the editor's tests could notice can say so with AREAS = [...]
    and each run is several times shorter; a mutation then reported as SURVIVED is run again against the whole suite by hand before it is believed).
    `times` is the path of a file written by an earlier run with `record`: it asks for the fast run, which stops at its first failing test, runs the
    cheapest tests first by those times and, when `python_only`, leaves out the C tests altogether. `record` is a path the run writes how long each
    Python test took to."""
    command = [sys.executable, "run_tests.py"]
    if python_only:
        command += list(areas or [])
        command += ["--no-build", "--no-c"] if times is not None else ["--no-build", "--no-debug", "--no-asan"]
    if times is not None:
        command += ["--fail-fast", "--order-by-times", times]
    if record is not None:
        command += ["--record-times", record]
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    out = result.stdout + result.stderr
    if "the build failed" in out or "Build failed" in out:
        return "BUILD FAILED", [], out
    failed = sorted(set(re.findall(r"^\s*(?:\[debug heap\] )?FAIL  (\S+)", out, re.M)))
    if "did not finish" in out:
        return "caught", failed or ["(the C test program crashed)"], out
    summary = re.findall(r"(\d+) passed, (\d+) failed, (\d+) total", out)
    if not summary:                                                       # no total at all: the run itself crashed, which is a detection too
        return "caught", failed or ["(the test run crashed)"], out
    return ("caught" if failed or (summary and summary[-1][1] != "0") else "SURVIVED"), failed, out


def rebuild():
    """Builds the DLL and the test programs from the sources as they are now."""
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "build.ps1")]
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit("the build after a mutation of a C file failed, so the next run would meet the mutated DLL:\n" + result.stdout + result.stderr)


def totals(out):
    found = re.findall(r"\d+ passed, \d+ failed, \d+ total", out)
    return found[-1] if found else "(no total)"


def python_runs(mutations, areas):
    """The different sets of Python test files the runs of these mutations use (a list of file names, or None for every test file): the Python
    tests of a run after a mutation of a .py file are those of `areas`, and after a mutation of a C file all of them."""
    kinds = []
    for _, path, _, _ in mutations:
        wanted = areas if path.endswith(".py") else None
        if wanted not in kinds:
            kinds.append(wanted)
    return kinds


def main(argv):
    thorough = "--thorough" in argv
    argv = [a for a in argv if a != "--thorough"]
    leftovers = glob.glob(os.path.join(ROOT, "**", "*.mutation_backup"), recursive=True)
    if leftovers:
        raise SystemExit("an earlier run was interrupted; the original is in " + ", ".join(leftovers))
    namespace = {}
    with open(argv[0], encoding="utf-8") as handle:
        exec(handle.read(), namespace)                                    # noqa: S102 - a spec file written by us
    only = set(argv[1:])
    mutations = [m for m in namespace["MUTATIONS"] if not only or m[0].split()[0] in only]
    backups, tally = {}, {"caught": 0, "SURVIVED": 0, "BUILD FAILED": 0, "SKIPPED": 0}
    times = None
    if not thorough:
        handle, times = tempfile.mkstemp(prefix="canopy_times_", suffix=".json")
        os.close(handle)
    try:
        print("runs:", "thorough (every test of every run, in name order)" if thorough else
              "fast (stop at the first failing test, cheapest tests first, no C tests after a change to a Python file)", flush=True)
        state, failed, out = run_suite(record=times)
        print("before any mutation:", state, totals(out), flush=True)
        if state != "SURVIVED":
            raise SystemExit("the suite must be green before mutating")
        if times is not None:                                             # the order the fast runs use must itself be a green run, before any mutation
            for areas in python_runs(mutations, namespace.get("AREAS")):
                state, failed, out = run_suite(python_only=True, areas=areas, times=times)
                print(f"before any mutation, in the fast order ({', '.join(areas) if areas else 'every Python test'}):", state, totals(out), flush=True)
                if state != "SURVIVED":
                    raise SystemExit("the suite must be green in the fast order too before mutating")
        dll_mutated = False                                               # True while the DLL was last built from a mutated C file
        for name, path, old, new in mutations:
            full = os.path.join(ROOT, path)
            if full not in backups:
                backups[full] = full + ".mutation_backup"
                shutil.copy2(full, backups[full])
            original = open(backups[full], "rb").read().decode("utf-8").replace("\r\n", "\n")
            if original.count(old) != 1:
                print(f"{name}: SKIPPED, the text to replace occurs {original.count(old)} times", flush=True)
                tally["SKIPPED"] += 1
                continue
            python_file = full.endswith(".py")
            if python_file and dll_mutated:                               # (the Python tests run against the DLL as it was last built)
                rebuild()
                dll_mutated = False
            with open(full, "wb") as handle:
                handle.write(original.replace(old, new).replace("\n", "\r\n").encode("utf-8"))
            fast = None if os.path.normpath(path) == "run_tests.py" else times        # (the fast flags are what a mutation of run_tests.py may break: it is run the thorough way)
            started = time.time()
            state, failed, out = run_suite(python_only=python_file, areas=namespace.get("AREAS") if python_file else None, times=fast)
            shutil.copy2(backups[full], full)
            dll_mutated = dll_mutated or not python_file
            tally[state] += 1
            names = ", ".join(n.replace("test_c_", "c:").replace("test_py_", "py:")[:60] for n in failed[:3])
            print(f"{name}: {state}" + (f" ({len(failed)} failing: {names}{'...' if len(failed) > 3 else ''})" if failed else "")
                  + f" [{time.time() - started:.0f}s]", flush=True)
    finally:
        for full, backup in backups.items():
            shutil.copy2(backup, full)
            os.remove(backup)
        for leftover in (times, times and times + ".tmp"):
            if leftover and os.path.exists(leftover):
                os.remove(leftover)
    state, failed, out = run_suite()
    print("after restoring:", state, totals(out), flush=True)
    print("summary:", ", ".join(f"{count} {kind}" for kind, count in tally.items()))
    all_caught = tally["SURVIVED"] == 0 and tally["BUILD FAILED"] == 0 and tally["SKIPPED"] == 0       # (a mutation that did not run proves nothing, so it is not a success)
    return 0 if state == "SURVIVED" and all_caught else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
