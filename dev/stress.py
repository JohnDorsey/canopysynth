# SPDX-License-Identifier: GPL-3.0-or-later
"""The Python-level multi-thread stress of plan step 13 for as long as asked: the real editor (in an off-screen window) makes random edits through the public API
while threads write a boundary inlet, read what it feeds, replace the file node's file and ask the engine what it holds (see tests/python/stress_threads.py for
what is checked). Prints what was done; exit code 0 if every check held, 1 if not (the problems are printed), 3 if the watchdog found the main thread or all the
others stalled for 20 seconds (the stacks of all threads are printed).
    python dev/stress.py [seconds] [--seed N] [--readers N]
The C-level stress, which has no GIL and hammers harder, is `build.ps1 -Stress` and build\\stress.exe."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "python"))


def main(argv):
    seconds, seed, readers = 10.0, 1, 3
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--seed" and index + 1 < len(argv):
            seed, index = int(argv[index + 1]), index + 2
        elif argument == "--readers" and index + 1 < len(argv):
            readers, index = int(argv[index + 1]), index + 2
        elif not argument.startswith("-") and float(argument) > 0:
            seconds, index = float(argument), index + 1
        else:
            print(__doc__)
            return 2
    import stress_threads
    print(f"python stress: {seconds} s, seed {seed}, {readers} readers", flush=True)
    try:
        counts = stress_threads.run(seconds=seconds, seed=seed, readers=readers)
    except AssertionError as error:
        print("PYTHON STRESS FAILED:\n" + str(error))
        return 1
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print("python stress: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
