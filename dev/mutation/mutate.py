"""Mutation check: breaks the library in small, specific ways, one at a time, runs the whole test suite after each, and reports whether the
tests noticed. A test suite that stays green with a deliberate fault in the code it covers is not testing that code.

    python dev/mutation/mutate.py dev/mutation/step3.py            every mutation of the spec
    python dev/mutation/mutate.py dev/mutation/step3.py I05 E13    only the mutations whose name starts with one of these words

A spec file defines MUTATIONS = [(name, file, old, new), ...]: `file` is relative to the project folder, `old` must occur exactly once in it
(written with \\n newlines; the file's CRLF is handled), `new` replaces it. Results:
    caught        some test failed (or the C test program crashed: a crash is a detection too)
    SURVIVED      the whole suite stayed green: either a weak test or an equivalent mutation; look at each one
    BUILD FAILED  the mutation does not compile (say, an unused variable under /WX): it proves nothing, rewrite it
Every file touched is restored afterwards, also if this script is interrupted (a backup file sits next to it meanwhile). If a run was killed
hard and left a *.mutation_backup file, this script refuses to start: copy the backup over the source file (it is the original) and delete it."""
import glob
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_suite(python_only=False):
    """The whole suite. For a mutation in a .py file the C code is unchanged, so `python_only` skips the build and the two extra C runs
    (the C tests still run once, and every Python test runs)."""
    command = [sys.executable, "run_tests.py"] + (["--no-build", "--no-debug", "--no-asan"] if python_only else [])
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


def totals(out):
    found = re.findall(r"\d+ passed, \d+ failed, \d+ total", out)
    return found[-1] if found else "(no total)"


def main(argv):
    leftovers = glob.glob(os.path.join(ROOT, "**", "*.mutation_backup"), recursive=True)
    if leftovers:
        raise SystemExit("an earlier run was interrupted; the original is in " + ", ".join(leftovers))
    namespace = {}
    with open(argv[0], encoding="utf-8") as handle:
        exec(handle.read(), namespace)                                    # noqa: S102 - a spec file written by us
    mutations = namespace["MUTATIONS"]
    only = set(argv[1:])
    backups, tally = {}, {"caught": 0, "SURVIVED": 0, "BUILD FAILED": 0, "SKIPPED": 0}
    try:
        state, failed, out = run_suite()
        print("before any mutation:", state, totals(out), flush=True)
        if state != "SURVIVED":
            raise SystemExit("the suite must be green before mutating")
        for name, path, old, new in mutations:
            if only and name.split()[0] not in only:
                continue
            full = os.path.join(ROOT, path)
            if full not in backups:
                backups[full] = full + ".mutation_backup"
                shutil.copy2(full, backups[full])
            original = open(backups[full], "rb").read().decode("utf-8").replace("\r\n", "\n")
            if original.count(old) != 1:
                print(f"{name}: SKIPPED, the text to replace occurs {original.count(old)} times", flush=True)
                tally["SKIPPED"] += 1
                continue
            with open(full, "wb") as handle:
                handle.write(original.replace(old, new).replace("\n", "\r\n").encode("utf-8"))
            started = time.time()
            state, failed, out = run_suite(python_only=full.endswith(".py"))
            shutil.copy2(backups[full], full)
            tally[state] += 1
            names = ", ".join(n.replace("test_c_", "c:").replace("test_py_", "py:")[:60] for n in failed[:3])
            print(f"{name}: {state}" + (f" ({len(failed)} failing: {names}{'...' if len(failed) > 3 else ''})" if failed else "")
                  + f" [{time.time() - started:.0f}s]", flush=True)
    finally:
        for full, backup in backups.items():
            shutil.copy2(backup, full)
            os.remove(backup)
    state, failed, out = run_suite()
    print("after restoring:", state, totals(out), flush=True)
    print("summary:", ", ".join(f"{count} {kind}" for kind, count in tally.items()))
    return 0 if state == "SURVIVED" and not tally["SURVIVED"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
